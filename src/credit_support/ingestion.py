import hashlib
import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, text

from credit_support.audit import append_event, canonical
from credit_support.idempotency import remember, replay
from credit_support.parsers import FIELDS, PARSER_VERSION, IngestionError, parse_document
from credit_support.security import authorize
from credit_support.settings import Identity


def require_case(conn: Connection, case_id: UUID, actor: Identity, *, lock: bool = False) -> Any:
    if actor.demo_session_id is not None:
        authorize(conn, case_id, actor)
    row = (
        conn.execute(
            text(
                """
      SELECT c.* FROM cases c JOIN case_members m ON m.case_id=c.id
      WHERE c.id=:id AND m.actor_id=:actor AND m.role=:role
    """
                + (" FOR UPDATE OF c" if lock else "")
            ),
            {"id": case_id, "actor": actor.actor_id, "role": actor.role},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Case not found")
    return row


def upload(
    engine: Engine, case_id: UUID, actor: Identity, key: str, data: bytes, media_type: str
) -> dict[str, Any]:
    if actor.demo_session_id is not None:
        raise HTTPException(403, "Guided demo uses the included synthetic documents")
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    with engine.connect() as conn:
        require_case(conn, case_id, actor)
    digest = hashlib.sha256(data).hexdigest()
    payload_hash = hashlib.sha256(canonical([digest, media_type, True]).encode()).hexdigest()
    parsed = parse_document(data, media_type)
    route = f"/v1/cases/{case_id}/documents"
    with engine.begin() as conn:
        # Case lock precedes the idempotency lock for every case-specific mutation.
        case = require_case(conn, case_id, actor, lock=True)
        cached = replay(conn, actor.actor_id, route, key, payload_hash)
        if cached:
            return cached
        period_end = date.fromisoformat(parsed["metadata"]["period_end"])
        if period_end > case["cutoff"]:
            raise HTTPException(422, "Statement period ends after the case cutoff")
        previous_period = conn.execute(
            text("""
          SELECT dc.parsed->'metadata'->>'period_start' FROM documents d
          JOIN document_contents dc ON dc.document_id=d.id WHERE d.case_id=:id LIMIT 1
        """),
            {"id": case_id},
        ).scalar_one_or_none()
        if previous_period and previous_period != parsed["metadata"]["period_start"]:
            raise HTTPException(422, "All case documents must share one annual period")
        existing = conn.execute(
            text("SELECT id FROM documents WHERE case_id=:id AND sha256=:sha"),
            {"id": case_id, "sha": digest},
        ).scalar_one_or_none()
        if existing:
            receipt = {
                "document_id": str(existing),
                "sha256": digest,
                "media_type": media_type,
                "byte_size": len(data),
                "synthetic": True,
            }
        else:
            count: int = conn.execute(
                text("SELECT count(*) FROM documents WHERE case_id=:id"), {"id": case_id}
            ).scalar_one()
            if count >= 20:
                raise HTTPException(413, "Case document limit reached")
            document_id = uuid4()
            conn.execute(
                text("""
              INSERT INTO documents(id,case_id,sha256,media_type,byte_size,storage_key)
              VALUES(:id,:case,:sha,:media,:size,:key)
            """),
                {
                    "id": document_id,
                    "case": case_id,
                    "sha": digest,
                    "media": media_type,
                    "size": len(data),
                    "key": "db://" + str(document_id),
                },
            )
            conn.execute(
                text("""
              INSERT INTO document_contents(document_id,data,parsed)
              VALUES(:id,:data,CAST(:parsed AS jsonb))
            """),
                {"id": document_id, "data": data, "parsed": canonical(parsed)},
            )
            conn.execute(
                text("UPDATE cases SET current_evaluation_id=NULL WHERE id=:id"), {"id": case_id}
            )
            receipt = {
                "document_id": str(document_id),
                "sha256": digest,
                "media_type": media_type,
                "byte_size": len(data),
                "synthetic": True,
            }
            append_event(conn, case_id, actor.actor_id, "DOCUMENT_RECEIVED", receipt)
        remember(conn, actor.actor_id, route, key, payload_hash, receipt, 202)
        return receipt


def queue_extraction(engine: Engine, case_id: UUID, actor: Identity, key: str) -> dict[str, Any]:
    if actor.role != "analyst":
        raise HTTPException(403, "Analyst role required")
    route = f"/v1/cases/{case_id}/extract"
    request_hash = hashlib.sha256(b"{}").hexdigest()
    with engine.begin() as conn:
        require_case(conn, case_id, actor, lock=True)
        cached = replay(conn, actor.actor_id, route, key, request_hash)
        if cached:
            return cached
        documents = (
            conn.execute(
                text("""
          SELECT d.id,d.sha256,dc.parsed->>'parser_version' AS parser_version FROM documents d
          JOIN document_contents dc ON dc.document_id=d.id WHERE d.case_id=:id ORDER BY d.id
        """),
                {"id": case_id},
            )
            .mappings()
            .all()
        )
        if not documents:
            raise HTTPException(409, "Upload a supported synthetic document first")
        snapshot = {
            "documents": [
                {
                    "document_id": str(d["id"]),
                    "sha256": d["sha256"],
                    "parser_version": d["parser_version"],
                }
                for d in documents
            ],
            "purpose": "EXTRACTION_ONLY",
        }
        input_hash = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        existing = (
            conn.execute(
                text("""
          SELECT e.id AS evaluation_id,j.id AS job_id FROM evaluations e JOIN jobs j
          ON j.evaluation_id=e.id AND j.step='extract_documents'
          WHERE e.case_id=:case AND e.input_hash=:hash
        """),
                {"case": case_id, "hash": input_hash},
            )
            .mappings()
            .first()
        )
        if existing:
            receipt = {k: str(v) for k, v in existing.items()}
        else:
            evaluation_id, job_id = uuid4(), uuid4()
            conn.execute(
                text("""
              INSERT INTO evaluations
              (id,case_id,prepared_by,input_hash,snapshot,versions,processing_state)
              VALUES(:id,:case,:actor,:hash,CAST(:snapshot AS jsonb),
                     CAST(:versions AS jsonb),'DOCUMENTS_RECEIVED')
            """),
                {
                    "id": evaluation_id,
                    "case": case_id,
                    "actor": actor.actor_id,
                    "hash": input_hash,
                    "snapshot": canonical(snapshot),
                    "versions": canonical({"extraction": PARSER_VERSION}),
                },
            )
            for d in documents:
                conn.execute(
                    text("INSERT INTO evaluation_documents VALUES(:eval,:doc)"),
                    {"eval": evaluation_id, "doc": d["id"]},
                )
            conn.execute(
                text("""
              INSERT INTO jobs(id,evaluation_id,step,input_hash,status)
              VALUES(:id,:eval,'extract_documents',:hash,'READY')
            """),
                {"id": job_id, "eval": evaluation_id, "hash": input_hash},
            )
            receipt = {"evaluation_id": str(evaluation_id), "job_id": str(job_id)}
            append_event(conn, case_id, actor.actor_id, "EXTRACTION_QUEUED", receipt)
        conn.execute(
            text("UPDATE cases SET current_evaluation_id=:eval WHERE id=:case"),
            {"eval": receipt["evaluation_id"], "case": case_id},
        )
        remember(conn, actor.actor_id, route, key, request_hash, receipt, 202)
        return receipt


def extract(conn: Connection, evaluation_id: UUID) -> dict[str, Any]:
    documents = (
        conn.execute(
            text("""
      SELECT d.*,dc.data,dc.parsed FROM evaluation_documents ed
      JOIN documents d ON d.id=ed.document_id JOIN document_contents dc ON dc.document_id=d.id
      WHERE ed.evaluation_id=:id ORDER BY d.id
    """),
            {"id": evaluation_id},
        )
        .mappings()
        .all()
    )
    if not documents:
        raise IngestionError("Snapshot contains no documents")
    expected: dict[str, Any] = conn.execute(
        text("SELECT snapshot FROM evaluations WHERE id=:id"), {"id": evaluation_id}
    ).scalar_one()
    actual = [
        {
            "document_id": str(d["id"]),
            "sha256": d["sha256"],
            "parser_version": d["parsed"]["parser_version"],
        }
        for d in documents
    ]
    if expected.get("documents") != actual:
        raise IngestionError("Document bindings do not match the pinned snapshot")
    all_candidates: dict[str, list[dict[str, Any]]] = {key: [] for key in FIELDS}
    meta = documents[0]["parsed"]["metadata"]
    for doc in documents:
        if hashlib.sha256(bytes(doc["data"])).hexdigest() != doc["sha256"]:
            raise IngestionError("Stored document checksum mismatch")
        parsed = doc["parsed"]
        if parsed["metadata"] != meta or parsed["parser_version"] != PARSER_VERSION:
            raise IngestionError("Snapshot scope or parser version mismatch")
        for candidate in parsed["candidates"]:
            raw, loc = candidate["raw"], candidate["locator"]
            if doc["media_type"] == "text/csv":
                original = parsed["rows"][loc["row"] - 2][loc["column"]]
            else:
                original = parsed["pages"][loc["page"] - 1][loc["start"] : loc["end"]]
            if original != raw:
                raise IngestionError("Source excerpt does not match its locator")
            if raw.strip():
                all_candidates[candidate["key"]].append({**candidate, "document_id": doc["id"]})
    exceptions = []
    for key, candidates in all_candidates.items():
        numbers = [
            Decimal(c["raw"])
            for c in candidates
            if re.fullmatch(r"-?(?:0|[1-9][0-9]{0,17})(?:\.\d{1,2})?", c["raw"])
        ]
        if not candidates:
            status, value = "missing", None
        elif len(numbers) != len(candidates):
            status, value = "invalid", None
        elif len(set(numbers)) > 1:
            status, value = "ambiguous", None
        else:
            status, value = "extracted", numbers[0].quantize(Decimal("0.01"))
        fact_id = uuid4()
        conn.execute(
            text("""
          INSERT INTO facts
          (id,evaluation_id,key,value,currency,unit,period_start,period_end,status)
          VALUES(:id,:eval,:key,:value,'USD','USD',:start,:end,:status)
        """),
            {
                "id": fact_id,
                "eval": evaluation_id,
                "key": key,
                "value": value,
                "start": meta["period_start"],
                "end": meta["period_end"],
                "status": status,
            },
        )
        for candidate in candidates:
            evidence_id = uuid4()
            conn.execute(
                text("""
              INSERT INTO evidence(id,evaluation_id,document_id,locator,excerpt,parser_version)
              VALUES(:id,:eval,:doc,CAST(:locator AS jsonb),:excerpt,:version)
            """),
                {
                    "id": evidence_id,
                    "eval": evaluation_id,
                    "doc": candidate["document_id"],
                    "locator": canonical(candidate["locator"]),
                    "excerpt": candidate["raw"],
                    "version": PARSER_VERSION,
                },
            )
            conn.execute(
                text("INSERT INTO fact_evidence VALUES(:fact,:evidence)"),
                {"fact": fact_id, "evidence": evidence_id},
            )
        if status != "extracted":
            exceptions.append({"key": key, "status": status})
    conn.execute(
        text("UPDATE evaluations SET processing_state='VALIDATING' WHERE id=:id"),
        {"id": evaluation_id},
    )
    return {
        "simulation": True,
        "facts": len(FIELDS),
        "exceptions": exceptions,
        "purpose": "EXTRACTION_ONLY",
    }
