from alembic import op

revision = "0005_human_review"
down_revision = "0004_ai_workflow"
branch_labels = None
depends_on = None

SQL = """
CREATE INDEX case_member_workspace ON case_members(actor_id,role,case_id);
CREATE INDEX case_created_order ON cases(created_at DESC,id DESC);
CREATE INDEX evaluation_case_history ON evaluations(case_id,created_at DESC,id DESC);
ALTER TABLE reviews ADD CONSTRAINT review_reason_length CHECK(length(reason)<=4000);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE reviews DROP CONSTRAINT review_reason_length")
    op.execute("DROP INDEX evaluation_case_history,case_created_order,case_member_workspace")
