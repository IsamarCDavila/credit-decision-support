"""Publish and verify a constrained synthetic policy catalog; no rule expressions are executed."""

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from credit_support.audit import canonical
from credit_support.db import get_engine
from credit_support.policy_models import PolicyCitation, PolicySpec, PolicyView


class PolicyError(ValueError):
    pass


def render(spec: PolicySpec) -> list[dict[str, str]]:
    threshold = spec.rules[0].threshold
    texts = [
        (
            "scope",
            "SIMULATION. Synthetic SME policy for USD standalone full-calendar-year statements.",
            "SIMULACIÓN. Política PyME sintética para estados individuales en USD "
            "de año calendario completo.",
        ),
        (
            "dscr-definition",
            "DSCR = annual cash available for debt service / annual debt service. "
            "EBITDA is not a substitute. Missing or unverified inputs require review. "
            "Zero debt service "
            "is not applicable; negative debt service is invalid. Negative cash flow is retained.",
            "DSCR = flujo anual disponible para servicio de deuda / servicio de deuda anual. "
            "EBITDA no sustituye el flujo. Las entradas ausentes o no verificadas "
            "requieren revisión. El servicio de deuda cero no aplica; el negativo es inválido. "
            "Se conserva el flujo negativo.",
        ),
        (
            "DSCR_MINIMUM",
            f"DSCR must be at least {threshold}. Compare before display rounding. "
            "This synthetic rule does not authorize credit.",
            f"El DSCR debe ser al menos {threshold}. "
            "Se compara antes del redondeo de presentación. "
            "Esta regla sintética no autoriza créditos.",
        ),
    ]
    fragments = []
    for identifier, en, es in texts:
        fragment = {
            "policy_version": spec.id,
            "fragment_id": identifier,
            "text_en": en,
            "text_es": es,
        }
        fragment["sha256"] = hashlib.sha256(canonical(fragment).encode()).hexdigest()
        fragments.append(fragment)
    return fragments


def content_hash(spec: PolicySpec) -> str:
    return hashlib.sha256(
        canonical(
            {"specification": spec.model_dump(mode="json"), "fragments": render(spec)}
        ).encode()
    ).hexdigest()


def publish(conn: Connection, spec: PolicySpec) -> str:
    scope = [spec.segment, spec.currency, spec.accounting_basis]
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
        {"scope": canonical(scope)},
    )
    digest = content_hash(spec)
    existing = conn.execute(
        text("SELECT content_sha256 FROM policy_versions WHERE id=:id"), {"id": spec.id}
    ).scalar_one_or_none()
    if existing is not None:
        if existing != digest:
            raise PolicyError("A policy identifier cannot be reused with changed content")
        load_policy(conn, spec.id)
        return spec.id
    conn.execute(
        text("""
      INSERT INTO policy_versions
      (id,segment,currency,accounting_basis,valid_from,valid_to,content_sha256,rules,published_at)
      VALUES(:id,:segment,:currency,:basis,:start,:end,:hash,CAST(:rules AS jsonb),NULL)
    """),
        {
            "id": spec.id,
            "segment": spec.segment,
            "currency": spec.currency,
            "basis": spec.accounting_basis,
            "start": spec.valid_from,
            "end": spec.valid_to,
            "hash": digest,
            "rules": canonical([r.model_dump() for r in spec.rules]),
        },
    )
    conn.execute(
        text("INSERT INTO policy_contents(policy_id,payload) VALUES(:id,CAST(:body AS jsonb))"),
        {"id": spec.id, "body": spec.model_dump_json()},
    )
    for ordinal, fragment in enumerate(render(spec), 1):
        conn.execute(
            text("""
          INSERT INTO policy_fragments(policy_id,id,ordinal,text_en,text_es,sha256)
          VALUES(:policy_version,:fragment_id,:ordinal,:text_en,:text_es,:sha256)
        """),
            {**fragment, "ordinal": ordinal},
        )
    conn.execute(
        text("UPDATE policy_versions SET published_at=now() WHERE id=:id"), {"id": spec.id}
    )
    return spec.id


def load_policy(conn: Connection, policy_id: str) -> PolicyView:
    row = (
        conn.execute(
            text("""
      SELECT p.*,c.payload FROM policy_versions p JOIN policy_contents c ON c.policy_id=p.id
      WHERE p.id=:id AND p.published_at IS NOT NULL
    """),
            {"id": policy_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise PolicyError("Published policy content is unavailable")
    try:
        spec = PolicySpec.model_validate(row["payload"])
    except ValueError as exc:
        raise PolicyError("Stored policy specification is invalid") from exc
    stored = [
        dict(r)
        for r in conn.execute(
            text("""
      SELECT policy_id AS policy_version,id AS fragment_id,text_en,text_es,sha256
      FROM policy_fragments WHERE policy_id=:id ORDER BY ordinal
    """),
            {"id": policy_id},
        ).mappings()
    ]
    if (
        spec.id != policy_id
        or content_hash(spec) != row["content_sha256"]
        or stored != render(spec)
        or row["rules"] != [r.model_dump() for r in spec.rules]
        or (
            row["segment"],
            row["currency"],
            row["accounting_basis"],
            row["valid_from"],
            row["valid_to"],
        )
        != (spec.segment, spec.currency, spec.accounting_basis, spec.valid_from, spec.valid_to)
    ):
        raise PolicyError("Stored policy text, rules, or scope fail integrity verification")
    return PolicyView(
        specification=spec,
        content_sha256=row["content_sha256"],
        fragments=[PolicyCitation.model_validate(f) for f in stored],
    )


def select_policy(conn: Connection, case: Any) -> PolicyView:
    versions: Sequence[str] = (
        conn.execute(
            text("""
      SELECT id FROM policy_versions WHERE segment=:segment AND currency=:currency
      AND accounting_basis='individual' AND published_at IS NOT NULL
      AND valid_from<=:cutoff AND (valid_to IS NULL OR :cutoff<valid_to) ORDER BY id
    """),
            {"segment": case["segment"], "currency": case["currency"], "cutoff": case["cutoff"]},
        )
        .scalars()
        .all()
    )
    if len(versions) != 1:
        raise PolicyError("Exactly one published policy must match the case scope and cutoff")
    return load_policy(conn, versions[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish validated synthetic policy bundles")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.paths or sorted(Path("data/policies").glob("*.json"))
    if not paths:
        raise SystemExit("No policy bundles found")
    with get_engine().begin() as conn:
        for path in paths:
            spec = PolicySpec.model_validate_json(path.read_text(encoding="utf-8"))
            publish(conn, spec)
            print("Published synthetic policy:", spec.id)


if __name__ == "__main__":
    main()
