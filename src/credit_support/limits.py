from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from credit_support.parsers import MAX_FILE_BYTES


class RequestSizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = MAX_FILE_BYTES + 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
            return
        if length > limit:
            await JSONResponse({"detail": "Request exceeds upload limit"}, 413)(
                scope, receive, send
            )
            return
        total = 0

        async def bounded_receive() -> Message:
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise HTTPException(413, "Request exceeds upload limit")
            return message

        await self.app(scope, bounded_receive, send)
