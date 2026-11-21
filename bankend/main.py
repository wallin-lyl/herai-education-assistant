import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ai_common import AIServiceError
from config import settings
from gemini_service import GeminiTutorService
from request_guard import SlidingWindowLimiter
from schemas import ChatRequest
from zhipu_service import ZhipuTutorService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("herai")

if settings.ai_provider == "zhipu":
    service = ZhipuTutorService(settings)
elif settings.ai_provider == "gemini":
    service = GeminiTutorService(settings)
else:
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")

rate_limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)
chat_slots = asyncio.Semaphore(settings.max_concurrent_chats)
web_build_dir = Path(__file__).resolve().parents[1] / "build" / "web"
web_index = web_build_dir / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if service.configured:
        logger.info(
            "HerAI API started provider=%s model=%s",
            service.provider_name,
            service.model_name,
        )
    else:
        logger.warning("GEMINI_API_KEY is not configured")
    yield


app = FastAPI(
    title="HerAI API",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


def sse_event(payload: dict) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


def request_client_key(request: Request) -> str:
    if settings.trust_proxy_headers:
        cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cloudflare_ip:
            return cloudflare_ip
        forwarded = request.headers.get("x-forwarded-for", "").strip()
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/")
async def home():
    if web_index.exists():
        return FileResponse(web_index)
    return {
        "message": "HerAI 后端运行正常",
        "version": app.version,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ai_configured": service.configured,
        "provider": service.provider_name,
        "model": service.model_name,
        "paid_model_fallback": False,
    }


@app.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    if not service.configured:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "not_configured",
                    "message": "后端尚未配置免费 AI 模型 API Key，请检查 bankend/.env。",
                    "retryable": False,
                }
            },
        )

    client_key = request_client_key(request)
    retry_after = rate_limiter.allow(client_key)
    if retry_after is not None:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
            content={
                "error": {
                    "code": "rate_limited",
                    "message": "请求过于频繁，已暂停本次请求以保护免费额度。请稍后重试。",
                    "retryable": True,
                }
            },
        )

    try:
        await asyncio.wait_for(chat_slots.acquire(), timeout=0.05)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "concurrent_limited",
                    "message": "已有一个 AI 回答正在生成，请等待完成或先停止当前回答。",
                    "retryable": True,
                }
            },
        )

    request_id = uuid.uuid4().hex[:12]

    async def generate():
        try:
            yield sse_event(
                {
                    "type": "meta",
                    "provider": service.provider_name,
                    "model": service.model_name,
                    "request_id": request_id,
                }
            )
            async for text in service.stream_reply(
                message=payload.message,
                history=[item.model_dump() for item in payload.history],
            ):
                yield sse_event({"type": "delta", "text": text})
            yield sse_event({"type": "done"})
        except asyncio.CancelledError:
            logger.info("Client cancelled the current chat request")
            raise
        except AIServiceError as exc:
            logger.warning(
                "AI request failed code=%s retryable=%s",
                exc.code,
                exc.retryable,
            )
            yield sse_event(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": exc.user_message,
                    "retryable": exc.retryable,
                }
            )
        except Exception:
            logger.exception("Unexpected chat stream failure")
            yield sse_event(
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": "AI 服务出现未预期错误，请稍后重试。",
                    "retryable": True,
                }
            )
        finally:
            chat_slots.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


if web_index.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(web_build_dir), html=True),
        name="web",
    )
