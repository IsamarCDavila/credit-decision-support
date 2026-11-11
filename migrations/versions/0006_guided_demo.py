from alembic import op

revision = "0006_guided_demo"
down_revision = "0005_human_review"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE demo_sessions (
 id uuid PRIMARY KEY, case_id uuid UNIQUE NOT NULL REFERENCES cases(id),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 revoked_at timestamptz, CHECK(expires_at>created_at)
);
CREATE INDEX demo_session_expiry ON demo_sessions(expires_at) WHERE revoked_at IS NULL;
CREATE TABLE demo_role_tokens (
 token_hash char(64) PRIMARY KEY, session_id uuid NOT NULL REFERENCES demo_sessions(id),
 actor_id text UNIQUE NOT NULL,
 role text NOT NULL CHECK(role IN ('analyst','reviewer','auditor')),
 UNIQUE(session_id,role)
);
CREATE TRIGGER demo_token_immutable BEFORE UPDATE OR DELETE ON demo_role_tokens
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
CREATE FUNCTION guard_demo_session() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR
 (NEW.id,NEW.case_id,NEW.created_at,NEW.expires_at) IS DISTINCT FROM
 (OLD.id,OLD.case_id,OLD.created_at,OLD.expires_at) THEN
  RAISE EXCEPTION 'demo session may only be revoked' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER demo_session_immutable BEFORE UPDATE OR DELETE ON demo_sessions
 FOR EACH ROW EXECUTE FUNCTION guard_demo_session();
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN
  GRANT SELECT,INSERT ON demo_sessions,demo_role_tokens TO cds_runtime;
  GRANT UPDATE(revoked_at) ON demo_sessions TO cds_runtime;
 END IF;
END $$;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE demo_role_tokens,demo_sessions")
    op.execute("DROP FUNCTION guard_demo_session()")
