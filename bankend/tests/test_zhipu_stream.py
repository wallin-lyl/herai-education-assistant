import unittest

import httpx

from config import Settings
from zhipu_service import ZhipuTutorService


class ZhipuStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_stream_is_parsed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                str(request.url),
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            )
            self.assertIn("Bearer test-only", request.headers["authorization"])
            body = await request.aread()
            self.assertIn(b'"glm-4.7-flash"', body)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"第二段"}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )

        service = ZhipuTutorService(Settings(zhipu_api_key="test-only"))
        await service.client.aclose()
        service.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        try:
            chunks = [
                chunk
                async for chunk in service.stream_reply("解释条件概率", [])
            ]
        finally:
            await service.client.aclose()

        self.assertEqual("".join(chunks), "第一段第二段")


if __name__ == "__main__":
    unittest.main()
