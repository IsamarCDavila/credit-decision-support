from pathlib import Path

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    directory = Path(__file__).resolve().parent.parent
    op.get_bind().exec_driver_sql((directory / "0001_schema.sql").read_text(encoding="utf-8"))
    op.get_bind().exec_driver_sql((directory / "0001_controls.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    tables = (
        "idempotency_records",
        "audit_events",
        "jobs",
        "reviews",
        "calculations",
        "fact_evidence",
        "facts",
        "evidence",
        "evaluation_documents",
        "evaluations",
        "documents",
        "policy_versions",
        "case_members",
        "cases",
    )
    for table in tables:
        op.execute(f"DROP TABLE {table} CASCADE")
    functions = (
        "deny_mutation",
        "guard_policy",
        "guard_evaluation",
        "guard_case_evaluation",
        "guard_document_binding",
        "guard_evidence",
        "guard_finalized_child",
        "guard_fact_evidence",
        "require_fact_evidence",
        "guard_calculation",
        "guard_review",
    )
    for function in functions:
        op.execute(f"DROP FUNCTION {function}()")
