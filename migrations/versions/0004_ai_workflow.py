from alembic import op

revision = "0004_ai_workflow"
down_revision = "0003_policy_engine"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE llm_budgets (
 id text PRIMARY KEY, limit_usd numeric NOT NULL CHECK(limit_usd>0 AND limit_usd<=2),
 last_reserved_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO llm_budgets(id,limit_usd) VALUES('phase4-openai',2);
CREATE TABLE model_calls (
 id uuid PRIMARY KEY, evaluation_id uuid NOT NULL REFERENCES evaluations(id),
 provider text NOT NULL CHECK(provider IN ('mock','openai')), model text NOT NULL,
 stage text NOT NULL, request_hash char(64) NOT NULL, prompt_version text NOT NULL,
 status text NOT NULL CHECK(status IN ('RESERVED','COMPLETED','FAILED')),
 reserved_usd numeric NOT NULL CHECK(reserved_usd>=0), charged_usd numeric CHECK(charged_usd>=0),
 input_tokens integer CHECK(input_tokens>=0), output_tokens integer CHECK(output_tokens>=0),
 request jsonb NOT NULL, response jsonb, output jsonb, response_id text, error_code text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(evaluation_id,provider,model,stage,request_hash)
);
CREATE INDEX model_calls_evaluation ON model_calls(evaluation_id);
CREATE FUNCTION guard_model_call() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR OLD.status<>'RESERVED' OR NEW.status='RESERVED' OR
 (NEW.id,NEW.created_at,NEW.evaluation_id,NEW.provider,NEW.model,NEW.stage,NEW.request_hash,NEW.request,
 NEW.prompt_version,NEW.reserved_usd) IS DISTINCT FROM
 (OLD.id,OLD.created_at,OLD.evaluation_id,OLD.provider,OLD.model,OLD.stage,OLD.request_hash,OLD.request,
 OLD.prompt_version,OLD.reserved_usd) THEN
  RAISE EXCEPTION 'model-call record is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER model_call_immutable BEFORE UPDATE OR DELETE ON model_calls
 FOR EACH ROW EXECUTE FUNCTION guard_model_call();
CREATE TABLE ai_drafts (
 evaluation_id uuid PRIMARY KEY REFERENCES policy_checks(evaluation_id),
 draft jsonb NOT NULL, sha256 char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER draft_immutable BEFORE UPDATE OR DELETE ON ai_drafts
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN
  GRANT SELECT ON llm_budgets TO cds_runtime;
  GRANT UPDATE(last_reserved_at) ON llm_budgets TO cds_runtime;
  GRANT SELECT,INSERT,UPDATE ON model_calls TO cds_runtime;
  GRANT SELECT,INSERT ON ai_drafts TO cds_runtime;
 END IF;
END $$;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE ai_drafts,model_calls,llm_budgets")
    op.execute("DROP FUNCTION guard_model_call()")
