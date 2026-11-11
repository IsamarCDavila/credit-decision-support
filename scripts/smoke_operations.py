"""Verify packaged HTTP admission without creating cases or exposing credentials."""

import argparse
import json
from uuid import UUID

import httpx


def run(base_url):
    with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
        ready = client.get("/readyz")
        ready.raise_for_status()
        UUID(ready.headers["X-Request-ID"])
        assert client.get("/v1/operations").status_code == 401
        rejected = None
        # Missing the required demo marker prevents writes on admitted requests.
        for n in range(61):
            response = client.post(
                "/v1/demo/sessions",
                json={"role": "analyst"},
                headers={"X-Forwarded-For": f"198.51.100.{n + 1}"},
            )
            UUID(response.headers["X-Request-ID"])
            assert response.status_code in (422, 429)
            if response.status_code == 429:
                rejected = response
                break
        assert rejected is not None
        assert 1 <= int(rejected.headers["Retry-After"]) <= 61
        spoof = client.post("/v1/demo/sessions", headers={"X-Forwarded-For": "203.0.113.90"})
        assert spoof.status_code == 429
        assert spoof.headers["X-Request-ID"] != rejected.headers["X-Request-ID"]
        assert client.get("/healthz").status_code == 200
    print(
        json.dumps(
            {
                "request_ids_verified": True,
                "demo_rate_rejection_verified": True,
                "forwarded_peer_bypass_blocked": True,
                "cases_created": 0,
                "paid_model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    run(parser.parse_args().base_url)
