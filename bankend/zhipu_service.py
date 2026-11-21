import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence

import httpx

from ai_common import AIServiceError, SYSTEM_INSTRUCTION
from config import Settings


class ZhipuTutorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider_name = "zhipu"
        self.model_name = settings.zhipu_model
        self.configured = bool(settings.zhipu_api_key)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.settings.idle_timeout_seconds,
                connect=self.settings.connect_timeout_seconds,
            )
        )

    def build_messages(
        self,
        message: str,
        history: Sequence[dict],
    ) -> list[dict[str, str]]:
        compact: list[dict[str, str]] = []
        for item in history[-self.settings.max_history_messages :]:
            role = item.get("role")
            text = str(item.get("text", "")).strip()
            if role not in {"user", "assistant"} or not text:
                continue
            compact.append({"role": role, "content": text[:8000]})

        while compact and compact[0]["role"] != "user":
            compact.pop(0)

        merged: list[dict[str, str]] = []
        for item in compact:
            if merged and merged[-1]["role"] == item["role"]:
                merged[-1]["content"] += f"\n{item['content']}"
            else:
                merged.append(dict(item))

        merged.append({"role": "user", "content": message})
        if len(merged) >= 2 and merged[-2]["role"] == "user":
            merged[-2]["content"] += f"\n{merged[-1]['content']}"
            merged.pop()

        return [{"role": "system", "content": SYSTEM_INSTRUCTION}, *merged]

    async def stream_reply(
        self,
        message: str,
        history: Sequence[dict],
    ) -> AsyncIterator[str]:
        if not self.settings.zhipu_api_key:
            raise AIServiceError(
                code="not_configured",
                user_message="后端尚未配置智谱 API Key。",
            )

        payload = {
            "model": self.settings.zhipu_model,
            "messages": self.build_messages(message, history),
            "stream": True,
            "temperature": 0.6,
            "max_tokens": self.settings.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.zhipu_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        endpoint = f"{self.settings.zhipu_base_url}/chat/completions"
        last_error: AIServiceError | None = None

        for attempt in range(self.settings.max_retries + 1):
            emitted = False
            try:
                async with self.client.stream(
                    "POST",
                    endpoint,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(
                            "utf-8",
                            errors="replace",
                        )
                        raise self.map_http_error(response.status_code, body)

                    lines = response.aiter_lines()
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                anext(lines),
                                timeout=(
                                    self.settings.connect_timeout_seconds
                                    if not emitted
                                    else self.settings.idle_timeout_seconds
                                ),
                            )
                        except StopAsyncIteration:
                            return
                        except asyncio.TimeoutError as exc:
                            if emitted:
                                raise AIServiceError(
                                    code="timeout",
                                    user_message=(
                                        "智谱免费模型响应超时，请重新生成。"
                                        "系统不会切换到付费模型。"
                                    ),
                                    retryable=True,
                                ) from exc
                            raise

                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        if data == "[DONE]":
                            return
                        try:
                            payload_data = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if payload_data.get("error"):
                            error = payload_data["error"]
                            message_text = (
                                error.get("message")
                                if isinstance(error, dict)
                                else str(error)
                            )
                            raise AIServiceError(
                                code="ai_error",
                                user_message="智谱免费模型暂时不可用，请稍后重试。",
                                retryable=False,
                                technical_detail=str(message_text)[:1500],
                            )

                        choices = payload_data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            emitted = True
                            yield text
                return
            except AIServiceError as error:
                if emitted or not error.retryable:
                    raise
                last_error = error
            except asyncio.TimeoutError:
                if emitted:
                    raise AIServiceError(
                        code="timeout",
                        user_message=(
                            "智谱免费模型响应超时，请重新生成。"
                            "系统不会切换到付费模型。"
                        ),
                        retryable=True,
                    )
                last_error = AIServiceError(
                    code="timeout",
                    user_message="连接智谱免费模型超时，请稍后重试。",
                    retryable=True,
                )
            except httpx.HTTPError as exc:
                if emitted:
                    raise AIServiceError(
                        code="stream_interrupted",
                        user_message="智谱免费模型流式连接中断，请重新生成。",
                        retryable=True,
                        technical_detail=str(exc)[:1500],
                    ) from exc
                last_error = self.map_exception(exc)
                if not last_error.retryable:
                    raise last_error from exc
            except Exception as exc:
                if emitted:
                    raise AIServiceError(
                        code="stream_interrupted",
                        user_message="智谱免费模型流式连接中断，请重新生成。",
                        retryable=True,
                        technical_detail=str(exc)[:1500],
                    ) from exc
                last_error = self.map_exception(exc)
                if not last_error.retryable:
                    raise last_error from exc

            if attempt < self.settings.max_retries:
                await asyncio.sleep(0.8 * (2**attempt))

        if last_error:
            raise last_error
        raise AIServiceError(
            code="unavailable",
            user_message="智谱免费模型暂时不可用，请稍后重试。",
            retryable=True,
        )

    @staticmethod
    def map_http_error(status: int, body: str) -> AIServiceError:
        detail = body[:1500]
        if status == 429:
            if any(
                marker in body
                for marker in ("访问量过大", "1305", "并发", "overloaded")
            ):
                return AIServiceError(
                    code="service_overloaded",
                    user_message=(
                        "智谱免费模型当前访问量过大，已自动重试。"
                        "请稍后重新生成。"
                    ),
                    retryable=True,
                    technical_detail=detail,
                )
            return AIServiceError(
                code="quota_limited",
                user_message=(
                    "智谱免费模型当前请求过多或触发免费额度限制，"
                    "系统不会切换到付费模型。请稍后重试。"
                ),
                retryable=False,
                technical_detail=detail,
            )
        if status in {401, 403}:
            return AIServiceError(
                code="auth_error",
                user_message="后端智谱 API Key 无效或无权限，请检查服务器配置。",
                retryable=False,
                technical_detail=detail,
            )
        if status == 404:
            return AIServiceError(
                code="model_unavailable",
                user_message="当前智谱免费模型不可用，请检查模型配置。",
                retryable=False,
                technical_detail=detail,
            )
        if status >= 500:
            return AIServiceError(
                code="service_overloaded",
                user_message="智谱免费模型当前繁忙，请稍后重新生成。",
                retryable=True,
                technical_detail=detail,
            )
        return AIServiceError(
            code="ai_error",
            user_message="智谱免费模型请求失败，请稍后重试。",
            retryable=False,
            technical_detail=detail,
        )

    @staticmethod
    def map_exception(exc: Exception) -> AIServiceError:
        raw = f"{type(exc).__name__} {exc}"
        if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
            return AIServiceError(
                code="upstream_network_error",
                user_message=(
                    "后端暂时无法连接智谱，请检查网络或稍后重试。"
                    "系统不会切换到付费模型。"
                ),
                retryable=True,
                technical_detail=raw[:1500],
            )
        status_match = re.search(r"\b(400|401|403|404|429|500|502|503|504)\b", raw)
        if status_match:
            return ZhipuTutorService.map_http_error(
                int(status_match.group(1)),
                raw,
            )
        return AIServiceError(
            code="ai_error",
            user_message="智谱免费模型暂时不可用，请稍后重试。",
            retryable=False,
            technical_detail=raw[:1500],
        )
