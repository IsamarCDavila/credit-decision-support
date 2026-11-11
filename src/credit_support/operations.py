"""Bounded process telemetry and admission controls; never retain request credentials."""

import json
import logging
import threading
import time
from collections import Counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from credit_support.db import get_engine
from credit_support.ingestion_api import Actor
from credit_support.settings import get_settings

logger = logging.getLogger("credit_support.operations")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
router = APIRouter()


class Telemetry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.counts: Counter[tuple[str, str, int]] = Counter()
        self.total_ms = 0.0
        self.max_ms = 0.0

    def observe(self, method: str, route: str, status: int, elapsed: float) -> None:
        with self.lock:
            self.counts[method, route, status] += 1
            self.total_ms += elapsed
            self.max_ms = max(self.max_ms, elapsed)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "scope": "current_api_process",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "requests": [
                    {"method": m, "route": r, "status": s, "count": n}
                    for (m, r, s), n in sorted(self.counts.items())
                ],
                "total_request_ms": round(self.total_ms, 3),
                "max_request_ms": round(self.max_ms, 3),
            }


telemetry = Telemetry()


class DemoAdmission:
    """Fixed-window per-peer limiter, bounded memory, no forwarded-header trust."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.peers: dict[str, tuple[float, int]] = {}

    def allow(self, peer: str, maximum: int, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        with self.lock:
            self.peers = {p: v for p, v in self.peers.items() if current - v[0] < 60}
            start, count = self.peers.get(peer, (current, 0))
            if count >= maximum or (peer not in self.peers and len(self.peers) >= 1024):
                return False, max(1, int(60 - (current - start)) + 1)
            self.peers[peer] = (start, count + 1)
            return True, 0


demo_admission = DemoAdmission()


class ServiceBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.admission = demo_admission

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        started, status = time.perf_counter(), 500
        method = scope.get("method", "OTHER")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            method = "OTHER"

        async def tracked_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            if scope["path"] == "/v1/demo/sessions" and method == "POST":
                peer = (scope.get("client") or ("unknown", 0))[0]
                allowed, retry = self.admission.allow(peer, get_settings().demo_requests_per_minute)
                if not allowed:
                    await JSONResponse(
                        {"detail": "Demo request rate exceeded"},
                        429,
                        headers={"Retry-After": str(retry)},
                    )(scope, receive, tracked_send)
                    return
            await self.app(scope, receive, tracked_send)
        finally:
            matched = scope.get("route")
            route = getattr(matched, "path", "__unmatched__")
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            telemetry.observe(method, route, status, elapsed)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": method,
                        "route": route,
                        "status": status,
                        "elapsed_ms": elapsed,
                    },
                    separators=(",", ":"),
                )
            )


@router.get("/v1/operations")
def operations(actor: Actor) -> dict[str, Any]:
    if actor.role != "admin" or actor.demo_session_id is not None:
        raise HTTPException(403, "Operations administrator required")
    with get_engine().connect() as conn:
        jobs = (
            conn.execute(
                text("SELECT status,count(*) AS count FROM jobs GROUP BY status ORDER BY status")
            )
            .mappings()
            .all()
        )
        oldest: Any = conn.execute(
            text("""
          SELECT COALESCE(max(EXTRACT(EPOCH FROM clock_timestamp()-next_run_at)),0)
          FROM jobs WHERE status='READY' AND next_run_at<clock_timestamp()
        """)
        ).scalar_one()
    return {
        "api": telemetry.snapshot(),
        "jobs": [dict(row) for row in jobs],
        "oldest_ready_seconds": float(oldest),
    }
