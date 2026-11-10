from alembic import op

revision = "0003_policy_engine"
down_revision = "0002_ingestion"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE policy_contents (
 policy_id text PRIMARY KEY REFERENCES policy_versions(id), payload jsonb NOT NULL,
 published_by text NOT NULL DEFAULT current_user
);
CREATE TABLE policy_fragments (
 policy_id text NOT NULL REFERENCES policy_versions(id), id text NOT NULL,
 ordinal int NOT NULL CHECK(ordinal>0), text_en text NOT NULL, text_es text NOT NULL,
 sha256 char(64) NOT NULL,
 search_en tsvector GENERATED ALWAYS AS (to_tsvector('english',text_en)) STORED,
 search_es tsvector GENERATED ALWAYS AS (to_tsvector('spanish',text_es)) STORED,
 PRIMARY KEY(policy_id,id), UNIQUE(policy_id,ordinal)
);
CREATE INDEX policy_search_en ON policy_fragments USING gin(search_en);
CREATE INDEX policy_search_es ON policy_fragments USING gin(search_es);

CREATE FUNCTION guard_published_policy_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target text; published timestamptz;
BEGIN
 IF TG_OP='DELETE' THEN target:=OLD.policy_id; ELSE target:=NEW.policy_id; END IF;
 IF TG_OP='UPDATE' AND NEW.policy_id IS DISTINCT FROM OLD.policy_id THEN
  RAISE EXCEPTION 'policy binding is immutable' USING ERRCODE='23514';
 END IF;
 SELECT published_at INTO published FROM policy_versions WHERE id=target FOR UPDATE;
 IF published IS NOT NULL THEN
  RAISE EXCEPTION 'published policy content is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER published_content BEFORE INSERT OR UPDATE OR DELETE ON policy_contents
 FOR EACH ROW EXECUTE FUNCTION guard_published_policy_child();
CREATE TRIGGER published_fragment BEFORE INSERT OR UPDATE OR DELETE ON policy_fragments
 FOR EACH ROW EXECUTE FUNCTION guard_published_policy_child();

ALTER TABLE evaluations ADD CONSTRAINT evaluation_policy_pair UNIQUE(id,policy_id);
CREATE TABLE policy_checks (
 evaluation_id uuid PRIMARY KEY, policy_id text NOT NULL, result jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT now(), UNIQUE(evaluation_id,policy_id),
 FOREIGN KEY(evaluation_id,policy_id) REFERENCES evaluations(id,policy_id)
);
CREATE TABLE policy_check_citations (
 evaluation_id uuid NOT NULL, policy_id text NOT NULL, fragment_id text NOT NULL,
 PRIMARY KEY(evaluation_id,fragment_id),
 FOREIGN KEY(evaluation_id,policy_id) REFERENCES policy_checks(evaluation_id,policy_id),
 FOREIGN KEY(policy_id,fragment_id) REFERENCES policy_fragments(policy_id,id)
);
CREATE TRIGGER policy_check_immutable BEFORE UPDATE OR DELETE ON policy_checks
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER policy_citation_immutable BEFORE UPDATE OR DELETE ON policy_check_citations
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();

ALTER TABLE calculations ADD COLUMN details jsonb NOT NULL DEFAULT '{}';
ALTER TABLE calculations ADD CONSTRAINT metric_status CHECK
 (status IN ('CALCULATED','MISSING_INPUT','INVALID_INPUT','NOT_APPLICABLE'));
ALTER TABLE calculations ADD CONSTRAINT metric_value CHECK
 ((status='CALCULATED' AND result IS NOT NULL) OR (status<>'CALCULATED' AND result IS NULL));
ALTER TABLE calculations ADD CONSTRAINT one_metric_per_evaluation
 UNIQUE(evaluation_id,formula_id,formula_version);
CREATE OR REPLACE FUNCTION guard_calculation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF cardinality(NEW.input_fact_ids)=0 OR EXISTS
 (SELECT 1 FROM unnest(NEW.input_fact_ids) k WHERE NOT EXISTS
 (SELECT 1 FROM facts WHERE id=k AND evaluation_id=NEW.evaluation_id
 AND (NEW.status<>'CALCULATED' OR status='extracted'))) THEN
  RAISE EXCEPTION 'invalid calculation inputs' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION seal_policy_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE eval_id uuid; fact_key uuid;
BEGIN
 IF TG_TABLE_NAME='fact_evidence' THEN
  IF TG_OP='DELETE' THEN fact_key:=OLD.fact_id; ELSE fact_key:=NEW.fact_id; END IF;
  SELECT evaluation_id INTO eval_id FROM facts WHERE id=fact_key;
 ELSE
  IF TG_OP='DELETE' THEN eval_id:=OLD.evaluation_id; ELSE eval_id:=NEW.evaluation_id; END IF;
 END IF;
 PERFORM id FROM evaluations WHERE id=eval_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM policy_checks WHERE evaluation_id=eval_id) THEN
  RAISE EXCEPTION 'completed policy inputs are immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER sealed_facts BEFORE INSERT OR UPDATE OR DELETE ON facts
 FOR EACH ROW EXECUTE FUNCTION seal_policy_inputs();
CREATE TRIGGER sealed_evidence BEFORE INSERT OR UPDATE OR DELETE ON evidence
 FOR EACH ROW EXECUTE FUNCTION seal_policy_inputs();
CREATE TRIGGER sealed_links BEFORE INSERT OR UPDATE OR DELETE ON fact_evidence
 FOR EACH ROW EXECUTE FUNCTION seal_policy_inputs();
CREATE TRIGGER sealed_calculations BEFORE INSERT OR UPDATE OR DELETE ON calculations
 FOR EACH ROW EXECUTE FUNCTION seal_policy_inputs();
CREATE TRIGGER sealed_documents BEFORE INSERT OR UPDATE OR DELETE ON evaluation_documents
 FOR EACH ROW EXECUTE FUNCTION seal_policy_inputs();

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN
  GRANT SELECT ON policy_contents,policy_fragments TO cds_runtime;
  GRANT SELECT,INSERT ON policy_checks,policy_check_citations TO cds_runtime;
  REVOKE UPDATE,DELETE ON calculations FROM cds_runtime;
 END IF;
END $$;
"""

RESTORE_CALCULATION = """
CREATE OR REPLACE FUNCTION guard_calculation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF cardinality(NEW.input_fact_ids)=0 OR EXISTS
 (SELECT 1 FROM unnest(NEW.input_fact_ids) k WHERE NOT EXISTS
 (SELECT 1 FROM facts WHERE id=k AND evaluation_id=NEW.evaluation_id AND status='extracted')) THEN
  RAISE EXCEPTION 'invalid calculation inputs' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    for trigger, table in (
        ("sealed_facts", "facts"),
        ("sealed_evidence", "evidence"),
        ("sealed_links", "fact_evidence"),
        ("sealed_calculations", "calculations"),
        ("sealed_documents", "evaluation_documents"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION seal_policy_inputs()")
    op.execute("DROP TABLE policy_check_citations,policy_checks")
    op.execute("ALTER TABLE evaluations DROP CONSTRAINT evaluation_policy_pair")
    op.execute("DROP TABLE policy_fragments,policy_contents")
    op.execute("DROP FUNCTION guard_published_policy_child()")
    op.execute("ALTER TABLE calculations DROP CONSTRAINT one_metric_per_evaluation")
    op.execute("ALTER TABLE calculations DROP CONSTRAINT metric_value")
    op.execute("ALTER TABLE calculations DROP CONSTRAINT metric_status")
    op.execute("ALTER TABLE calculations DROP COLUMN details")
    op.get_bind().exec_driver_sql(RESTORE_CALCULATION)
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN "
        "GRANT UPDATE,DELETE ON calculations TO cds_runtime; END IF; END $$"
    )
