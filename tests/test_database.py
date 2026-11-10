from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def seed(conn):
    case, evaluation, document = uuid4(), uuid4(), uuid4()
    conn.execute(
        text("INSERT INTO cases(id,segment,currency,cutoff) VALUES(:id,'SME','USD','2026-01-31')"),
        {"id": case},
    )
    conn.execute(
        text(
            "INSERT INTO evaluations(id,case_id,prepared_by,input_hash,snapshot,versions,"
            "processing_state) VALUES(:id,:case,'analyst',:hash,'{}','{}','CREATED')"
        ),
        {"id": evaluation, "case": case, "hash": "a" * 64},
    )
    conn.execute(
        text(
            "INSERT INTO documents(id,case_id,sha256,media_type,byte_size,storage_key) "
            "VALUES(:id,:case,:hash,'text/csv',10,:key)"
        ),
        {"id": document, "case": case, "hash": "b" * 64, "key": str(document)},
    )
    conn.execute(
        text("INSERT INTO evaluation_documents VALUES(:eval,:doc)"),
        {"eval": evaluation, "doc": document},
    )
    conn.execute(
        text("UPDATE cases SET current_evaluation_id=:eval WHERE id=:case"),
        {"eval": evaluation, "case": case},
    )
    return case, evaluation, document


def policy(conn, key, start, end):
    conn.execute(
        text(
            "INSERT INTO policy_versions VALUES(:id,'SME','USD','individual',"
            ":start,:end,:hash,'{}',now())"
        ),
        {"id": key, "start": start, "end": end, "hash": "c" * 64},
    )


def test_policy_overlap_boundaries_and_immutability(database):
    with database.begin() as conn:
        policy(conn, "p1", "2026-01-01", "2027-01-01")
        policy(conn, "p2", "2027-01-01", None)
    with pytest.raises(DBAPIError), database.begin() as conn:
        policy(conn, "p3", "2026-06-01", "2026-12-31")
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(text("UPDATE policy_versions SET rules='{}' WHERE id='p1'"))


@pytest.mark.parametrize("table", ["audit_events", "documents", "reviews"])
def test_runtime_cannot_mutate_protected_tables(database, table):
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(text("SET LOCAL ROLE cds_runtime"))
        conn.execute(text(f"DELETE FROM {table}"))


def test_cross_case_links_and_snapshot_immutability(database):
    with database.begin() as conn:
        a, e, d = seed(conn)
        b, e2, d2 = seed(conn)
    for sql, params in [
        ("UPDATE cases SET current_evaluation_id=:eval WHERE id=:case", {"eval": e2, "case": a}),
        ("INSERT INTO evaluation_documents VALUES(:eval,:doc)", {"eval": e, "doc": d2}),
        ("UPDATE evaluations SET snapshot='[1]' WHERE id=:id", {"id": e}),
    ]:
        with pytest.raises(DBAPIError), database.begin() as conn:
            conn.execute(text(sql), params)
    with database.begin() as conn:
        conn.execute(
            text("UPDATE evaluations SET processing_state='DRAFT_READY' WHERE id=:id"), {"id": e}
        )
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(text("UPDATE evaluations SET recommendation='{}' WHERE id=:id"), {"id": e})


@pytest.mark.parametrize("kind", ["self", "stale", "not_ready", "no_membership"])
def test_review_guards(database, kind):
    with database.begin() as conn:
        case, evaluation, _ = seed(conn)
        conn.execute(
            text("INSERT INTO case_members VALUES(:case,'reviewer','reviewer')"), {"case": case}
        )
        if kind != "not_ready":
            conn.execute(
                text("UPDATE evaluations SET processing_state='DRAFT_READY' WHERE id=:id"),
                {"id": evaluation},
            )
        if kind == "stale":
            conn.execute(
                text("UPDATE cases SET current_evaluation_id=NULL WHERE id=:id"), {"id": case}
            )
    with pytest.raises(DBAPIError), database.begin() as conn:
        reviewer = (
            "analyst" if kind == "self" else "stranger" if kind == "no_membership" else "reviewer"
        )
        conn.execute(
            text("INSERT INTO reviews VALUES(:id,:eval,:actor,'APPROVED','checked',now())"),
            {"id": uuid4(), "eval": evaluation, "actor": reviewer},
        )


def test_valid_review_and_no_duplicate(database):
    with database.begin() as conn:
        case, evaluation, _ = seed(conn)
        conn.execute(
            text("INSERT INTO case_members VALUES(:id,'reviewer','reviewer')"), {"id": case}
        )
        conn.execute(
            text("UPDATE evaluations SET processing_state='DRAFT_READY' WHERE id=:id"),
            {"id": evaluation},
        )
        conn.execute(
            text("INSERT INTO reviews VALUES(:id,:eval,'reviewer','APPROVED','checked',now())"),
            {"id": uuid4(), "eval": evaluation},
        )
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text("INSERT INTO reviews VALUES(:id,:eval,'reviewer','APPROVED','again',now())"),
            {"id": uuid4(), "eval": evaluation},
        )


def test_fact_evidence_required_and_cross_evaluation_rejected(database):
    with database.begin() as conn:
        _, e, d = seed(conn)
        _, e2, d2 = seed(conn)
        ev = uuid4()
        conn.execute(
            text("INSERT INTO evidence VALUES(:id,:eval,:doc,CAST(:loc AS jsonb),'100','csv-1')"),
            {"id": ev, "eval": e2, "doc": d2, "loc": '{"row":2,"column":"value"}'},
        )
    fact = uuid4()
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO facts(id,evaluation_id,key,value,unit,period_start,period_end,"
                "status) VALUES(:id,:eval,'revenue',100,'USD','2025-01-01','2025-12-31',"
                "'extracted')"
            ),
            {"id": fact, "eval": e},
        )
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO facts(id,evaluation_id,key,value,unit,period_start,period_end,"
                "status) VALUES(:id,:eval,'revenue',100,'USD','2025-01-01','2025-12-31',"
                "'extracted')"
            ),
            {"id": fact, "eval": e},
        )
        conn.execute(text("INSERT INTO fact_evidence VALUES(:fact,:ev)"), {"fact": fact, "ev": ev})


@pytest.mark.parametrize(
    "locator", ["{}", '{"row":1,"column":"value"}', '{"row":null,"column":"value"}']
)
def test_invalid_csv_locator(database, locator):
    with database.begin() as conn:
        _, e, d = seed(conn)
    with pytest.raises(DBAPIError), database.begin() as conn:
        conn.execute(
            text("INSERT INTO evidence VALUES(:id,:eval,:doc,CAST(:loc AS jsonb),'100','csv')"),
            {"id": uuid4(), "eval": e, "doc": d, "loc": locator},
        )
