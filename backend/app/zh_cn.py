import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

try:
    import opencc

    _CONVERTER = opencc.OpenCC("tw2sp")
except ImportError:
    _CONVERTER = None
    logger.warning("opencc 未安裝：簡中介面的 API 回應會維持繁體（pip install opencc）")

class ZhCnMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if (
            _CONVERTER is None
            or request.headers.get("x-locale") != "zh-CN"
            or not request.url.path.startswith("/api/")
            or not response.headers.get("content-type", "").startswith("application/json")
        ):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        converted = _CONVERTER.convert(body.decode("utf-8")).encode("utf-8")
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(converted, status_code=response.status_code, headers=headers)
