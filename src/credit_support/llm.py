"""Responses gateway with durable reservations and no automatic network retries."""

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import Engine, text

from credit_support.ai_prompts import PROMPT_VERSION
from credit_support.audit import canonical
from credit_support.settings import get_settings

# Standard token prices, USD per million; checked 2026-11-10.
INPUT_PRICE = Decimal("2")
OUTPUT_PRICE = Decimal("12")
BUDGET_ID = "phase4-openai"


class ModelError(ValueError):
    pass


def budget(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        limit: Decimal = conn.execute(
            text("SELECT limit_usd FROM llm_budgets WHERE id=:id"), {"id": BUDGET_ID}
        ).scalar_one()
        row = (
            conn.execute(
                text("""
          SELECT COALESCE(sum(COALESCE(charged_usd,reserved_usd)),0) AS spent,
          count(*) AS calls FROM model_calls WHERE provider='openai'
        """)
            )
            .mappings()
            .one()
        )
        return {
            "limit_usd": str(min(limit, get_settings().llm_budget_usd)),
            "committed_or_reserved_usd": str(row["spent"]),
            "openai_calls": row["calls"],
        }


def call_model(
    engine: Engine,
    evaluation_id: UUID,
    provider: str,
    stage: str,
    prompt: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    mock_output: dict[str, Any],
    max_output: int = 2048,
) -> dict[str, Any]:
    settings = get_settings()
    model = settings.llm_model if provider == "openai" else "deterministic-fixture-v1"
    request = {
        "model": model,
        "store": False,
        "reasoning": {"effort": "none"},
        "instructions": prompt,
        "input": canonical(payload),
        "max_output_tokens": max_output,
        "text": {
            "format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}
        },
    }
    encoded = canonical(request).encode("utf-8")
    if len(encoded) > 60000:
        raise ModelError("MODEL_INPUT_LIMIT")
    if provider not in ("mock", "openai"):
        raise ModelError("UNSUPPORTED_PROVIDER")
    if provider == "openai" and (not settings.llm_live_enabled or not settings.openai_api_key):
        raise ModelError("LIVE_PROVIDER_DISABLED_OR_KEY_MISSING")
    digest = hashlib.sha256(encoded).hexdigest()
    # Token upper bound: UTF-8 bytes plus framing allowance; reserve output at full cap.
    reserve = (
        (Decimal(len(encoded) + 4096) * INPUT_PRICE + Decimal(max_output) * OUTPUT_PRICE)
        / Decimal(1000000)
        if provider == "openai"
        else Decimal(0)
    )
    call_id = uuid4()
    with engine.begin() as conn:
        # Serialize ALL provider reservations and duplicate checks across workers.
        cap: Decimal = conn.execute(
            text("SELECT limit_usd FROM llm_budgets WHERE id=:id FOR UPDATE"), {"id": BUDGET_ID}
        ).scalar_one()
        old = (
            conn.execute(
                text("""
          SELECT * FROM model_calls WHERE evaluation_id=:eval AND provider=:provider
          AND model=:model AND stage=:stage AND request_hash=:hash
        """),
                {
                    "eval": evaluation_id,
                    "provider": provider,
                    "model": model,
                    "stage": stage,
                    "hash": digest,
                },
            )
            .mappings()
            .first()
        )
        if old:
            if old["status"] == "COMPLETED":
                return dict(old["output"])
            raise ModelError("MODEL_CALL_ALREADY_RESERVED_OR_FAILED")
        if provider == "openai":
            spent = conn.execute(
                text("""
              SELECT COALESCE(sum(COALESCE(charged_usd,reserved_usd)),0),count(*)
              FROM model_calls WHERE provider='openai'
            """)
            ).one()
            if spent[0] + reserve > min(cap, settings.llm_budget_usd):
                raise ModelError("MODEL_BUDGET_EXHAUSTED")
            if spent[1] >= settings.llm_max_calls:
                raise ModelError("MODEL_CALL_LIMIT")
        conn.execute(
            text("""
          INSERT INTO model_calls(id,evaluation_id,provider,model,stage,request_hash,
          prompt_version,status,reserved_usd,request)
          VALUES(:id,:eval,:provider,:model,:stage,:hash,:prompt,'RESERVED',:reserve,
                 CAST(:request AS jsonb))
        """),
            {
                "id": call_id,
                "eval": evaluation_id,
                "provider": provider,
                "model": model,
                "stage": stage,
                "hash": digest,
                "prompt": PROMPT_VERSION,
                "reserve": reserve,
                "request": encoded.decode(),
            },
        )
    response: dict[str, Any] = {}
    charge: Decimal | None = Decimal(0) if provider == "mock" else None
    input_tokens, output_tokens = None, None
    try:
        if provider == "mock":
            output = mock_output
        else:
            assert settings.openai_api_key is not None
            with httpx.Client(
                timeout=settings.llm_timeout_seconds, trust_env=False, follow_redirects=False
            ) as client:
                reply = client.post(
                    "https://api.openai.com/v1/responses",
                    json=request,
                    headers={
                        "Authorization": "Bearer " + settings.openai_api_key.get_secret_value()
                    },
                )
            if reply.status_code != 200:
                # Store a bounded diagnostic code, never raw provider errors or request headers.
                try:
                    error_code = reply.json().get("error", {}).get("code")
                except (ValueError, AttributeError):
                    error_code = None
                known = {
                    "insufficient_quota",
                    "rate_limit_exceeded",
                    "model_not_found",
                    "invalid_api_key",
                    "permission_denied",
                }
                suffix = "_" + error_code.upper() if error_code in known else ""
                raise ModelError(f"OPENAI_HTTP_{reply.status_code}{suffix}")
            response = reply.json()
            usage = response.get("usage", {})
            if (
                type(usage.get("input_tokens")) is not int
                or type(usage.get("output_tokens")) is not int
                or min(usage["input_tokens"], usage["output_tokens"]) < 0
            ):
                raise ModelError("MODEL_USAGE_MISSING")
            input_tokens, output_tokens = usage["input_tokens"], usage["output_tokens"]
            actual = (
                Decimal(input_tokens) * INPUT_PRICE + Decimal(output_tokens) * OUTPUT_PRICE
            ) / Decimal(1000000)
            if actual > reserve:
                # Keep the larger amount; the next reservation is blocked by the ledger.
                charge = actual
                raise ModelError("MODEL_TOKEN_BOUND_EXCEEDED")
            charge = actual
            if response.get("status") != "completed":
                raise ModelError("MODEL_INCOMPLETE")
            content = [c for item in response.get("output", []) for c in item.get("content", [])]
            if any(c.get("type") == "refusal" for c in content):
                raise ModelError("MODEL_REFUSAL")
            texts = [c["text"] for c in content if c.get("type") == "output_text"]
            if len(texts) != 1:
                raise ModelError("MODEL_OUTPUT_MISSING")
            output = json.loads(texts[0])
            if not isinstance(output, dict):
                raise ModelError("MODEL_OUTPUT_INVALID")
        with engine.begin() as conn:
            conn.execute(
                text("""
              UPDATE model_calls SET status='COMPLETED',charged_usd=:charge,
              input_tokens=:inputs,output_tokens=:outputs,response=CAST(:response AS jsonb),
              output=CAST(:output AS jsonb),response_id=:response_id WHERE id=:id
            """),
                {
                    "id": call_id,
                    "charge": charge,
                    "inputs": input_tokens,
                    "outputs": output_tokens,
                    "response": canonical(response),
                    "output": canonical(output),
                    "response_id": response.get("id"),
                },
            )
        return dict(output)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        code = str(exc) if isinstance(exc, ModelError) else "MODEL_TRANSPORT_OR_FORMAT_ERROR"
        with engine.begin() as conn:
            conn.execute(
                text("""
              UPDATE model_calls SET status='FAILED',charged_usd=:charge,error_code=:error,
              input_tokens=:inputs,output_tokens=:outputs WHERE id=:id
            """),
                {
                    "id": call_id,
                    "charge": charge,
                    "error": code,
                    "inputs": input_tokens,
                    "outputs": output_tokens,
                },
            )
        raise ModelError(code) from None
