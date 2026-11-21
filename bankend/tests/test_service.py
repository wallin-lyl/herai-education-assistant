import json
import unittest

from config import Settings
from gemini_service import GeminiTutorService
from main import sse_event
from request_guard import SlidingWindowLimiter
from schemas import ChatRequest
from zhipu_service import ZhipuTutorService


class GeminiServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GeminiTutorService(Settings(gemini_api_key=None))

    def test_history_starts_with_user_and_merges_current_question(self):
        history = [
            {"role": "assistant", "text": "欢迎"},
            {"role": "user", "text": "问题一"},
            {"role": "assistant", "text": "回答一"},
            {"role": "user", "text": "补充"},
        ]
        contents = self.service.build_contents("问题二", history)

        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0].role, "user")
        self.assertEqual(contents[-1].role, "user")
        self.assertIn("补充", contents[-1].parts[0].text)
        self.assertIn("问题二", contents[-1].parts[0].text)

    def test_transient_and_quota_errors_are_mapped_without_paid_fallback(self):
        overloaded = self.service.map_error(Exception("503 UNAVAILABLE"))
        limited = self.service.map_error(Exception("429 RESOURCE_EXHAUSTED"))
        network = self.service.map_error(Exception("ConnectError connection failed"))

        self.assertEqual(overloaded.code, "service_overloaded")
        self.assertTrue(overloaded.retryable)
        self.assertEqual(limited.code, "quota_limited")
        self.assertIn("不会切换到付费模型", limited.user_message)
        self.assertEqual(network.code, "upstream_network_error")
        self.assertTrue(network.retryable)

    def test_request_validation_and_sse_encoding(self):
        request = ChatRequest(message="  如何复习？  ", history=[])
        self.assertEqual(request.message, "如何复习？")

        encoded = sse_event({"type": "delta", "text": "你好"}).decode("utf-8")
        self.assertTrue(encoded.startswith("data: "))
        self.assertTrue(encoded.endswith("\n\n"))
        payload = json.loads(encoded.removeprefix("data: ").strip())
        self.assertEqual(payload["type"], "delta")

    def test_rate_limiter_releases_slots_after_the_window(self):
        limiter = SlidingWindowLimiter(limit=2, window_seconds=10)
        self.assertIsNone(limiter.allow("client", now=100))
        self.assertIsNone(limiter.allow("client", now=101))
        self.assertIsNotNone(limiter.allow("client", now=102))
        self.assertIsNone(limiter.allow("client", now=111))

    def test_zhipu_free_provider_uses_domestic_chat_messages(self):
        service = ZhipuTutorService(Settings(zhipu_api_key="test-only"))
        messages = service.build_messages(
            "问题二",
            [
                {"role": "assistant", "text": "欢迎"},
                {"role": "user", "text": "问题一"},
                {"role": "assistant", "text": "回答一"},
            ],
        )

        self.assertEqual(service.provider_name, "zhipu")
        self.assertEqual(service.model_name, "glm-4.7-flash")
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "问题二")

    def test_zhipu_rate_limit_never_falls_back_to_paid_model(self):
        error = ZhipuTutorService.map_http_error(429, "rate limited")
        self.assertEqual(error.code, "quota_limited")
        self.assertIn("不会切换到付费模型", error.user_message)


if __name__ == "__main__":
    unittest.main()
