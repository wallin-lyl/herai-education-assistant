import asyncio
import re
from collections.abc import AsyncIterator, Sequence

from google import genai
from google.genai import types

from ai_common import AIServiceError, SYSTEM_INSTRUCTION
from config import Settings


class GeminiTutorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider_name = "gemini"
        self.model_name = settings.gemini_model
        self.configured = bool(settings.gemini_api_key)
        self.client = (
            genai.Client(api_key=settings.gemini_api_key)
            if self.configured
            else None
        )

    def build_contents(
        self,
        message: str,
        history: Sequence[dict],
    ) -> list[types.Content]:
        compact: list[dict[str, str]] = []
        for item in history[-self.settings.max_history_messages :]:
            role = item.get("role")
            text = str(item.get("text", "")).strip()
            if role not in {"user", "assistant"} or not text:
                continue
            compact.append({"role": role, "text": text[:8000]})

        while compact and compact[0]["role"] != "user":
            compact.pop(0)

        merged: list[dict[str, str]] = []
        for item in compact:
            if merged and merged[-1]["role"] == item["role"]:
                merged[-1]["text"] += f"\n{item['text']}"
            else:
                merged.append(dict(item))

        merged.append({"role": "user", "text": message})
        if len(merged) >= 2 and merged[-2]["role"] == "user":
            merged[-2]["text"] += f"\n{merged[-1]['text']}"
            merged.pop()

        return [
            types.Content(
                role="model" if item["role"] == "assistant" else "user",
                parts=[types.Part(text=item["text"])],
            )
            for item in merged
        ]

    async def stream_reply(
        self,
        message: str,
        history: Sequence[dict],
    ) -> AsyncIterator[str]:
        if not self.client:
            raise AIServiceError(
                code="not_configured",
                user_message="后端尚未配置 Gemini API Key。",
            )

        contents = self.build_contents(message, history)
        last_error: AIServiceError | None = None

        for attempt in range(self.settings.max_retries + 1):
            stream = None
            try:
                stream = await self.client.aio.models.generate_content_stream(
                    model=self.settings.gemini_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.6,
                        max_output_tokens=self.settings.max_output_tokens,
                    ),
                )
                iterator = stream.__aiter__()
                first_chunk = await asyncio.wait_for(
                    anext(iterator),
                    timeout=self.settings.connect_timeout_seconds,
                )
                first_text = getattr(first_chunk, "text", None)
                if first_text:
                    yield first_text

                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            anext(iterator),
                            timeout=self.settings.idle_timeout_seconds,
                        )
                    except StopAsyncIteration:
                        break
                    text = getattr(chunk, "text", None)
                    if text:
                        yield text
                return
            except asyncio.TimeoutError as exc:
                last_error = AIServiceError(
                    code="timeout",
                    user_message="AI 响应超时，请稍后重试。你的问题已保留。",
                    retryable=True,
                )
                if attempt >= self.settings.max_retries:
                    raise last_error from exc
            except AIServiceError:
                raise
            except Exception as exc:
                error = self.map_error(exc)
                if not error.retryable or attempt >= self.settings.max_retries:
                    raise error from exc
                last_error = error
            finally:
                close = getattr(stream, "aclose", None)
                if close:
                    try:
                        await close()
                    except Exception:
                        pass

            await asyncio.sleep(0.8 * (2**attempt))

        if last_error:
            raise last_error
        raise AIServiceError(
            code="unavailable",
            user_message="AI 服务暂时不可用，请稍后重试。",
            retryable=True,
        )

    @staticmethod
    def map_error(exc: Exception) -> AIServiceError:
        raw = f"{type(exc).__name__} {exc}"
        detail = raw[:1500]
        status_match = re.search(r"\b(429|500|502|503|504|401|403|404)\b", raw)
        status = int(status_match.group(1)) if status_match else None

        if status == 429 or "RESOURCE_EXHAUSTED" in raw:
            return AIServiceError(
                code="quota_limited",
                user_message=(
                    "Gemini 免费额度当前受限（429），系统不会切换到付费模型。"
                    "请稍后重试。"
                ),
                retryable=True,
                technical_detail=detail,
            )
        if status in {500, 502, 503, 504} or "UNAVAILABLE" in raw:
            return AIServiceError(
                code="service_overloaded",
                user_message=(
                    "Gemini 当前繁忙（503/服务过载），自动重试后仍未成功。"
                    "请稍后再试。"
                ),
                retryable=True,
                technical_detail=detail,
            )
        if status in {401, 403} or "API_KEY_INVALID" in raw:
            return AIServiceError(
                code="auth_error",
                user_message="后端 Gemini 密钥无效或无权限，请检查服务器配置。",
                retryable=False,
                technical_detail=detail,
            )
        if status == 404:
            return AIServiceError(
                code="model_unavailable",
                user_message="当前 Gemini 模型不可用，请检查后端模型配置。",
                retryable=False,
                technical_detail=detail,
            )
        if any(
            marker in raw
            for marker in ("ConnectError", "ConnectionError", "connection refused")
        ):
            return AIServiceError(
                code="upstream_network_error",
                user_message=(
                    "后端暂时无法连接 Gemini，请检查网络或稍后重试。"
                    "系统不会切换到付费模型。"
                ),
                retryable=True,
                technical_detail=detail,
            )
        return AIServiceError(
            code="ai_error",
            user_message="AI 服务暂时不可用，请稍后重试。",
            retryable=False,
            technical_detail=detail,
        )
