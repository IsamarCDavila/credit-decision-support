CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE policy_versions ADD CONSTRAINT no_published_policy_overlap
 EXCLUDE USING gist (segment WITH =, currency WITH =, accounting_basis WITH =,
 daterange(valid_from,valid_to,'[)') WITH &&) WHERE (published_at IS NOT NULL);
ALTER TABLE jobs ADD COLUMN lease_token uuid;
ALTER TABLE jobs ADD COLUMN next_run_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE jobs ADD CONSTRAINT valid_job_status
 CHECK(status IN ('READY','RUNNING','SUCCEEDED','FAILED_TERMINAL'));
ALTER TABLE jobs ADD CONSTRAINT running_job_has_lease CHECK
 (status <> 'RUNNING' OR (lease_until IS NOT NULL AND lease_token IS NOT NULL));
CREATE INDEX jobs_available ON jobs(status,next_run_at,lease_until);
CREATE INDEX evaluations_case ON evaluations(case_id);
CREATE INDEX documents_case ON documents(case_id);
CREATE INDEX evidence_evaluation ON evidence(evaluation_id);
CREATE INDEX facts_evaluation ON facts(evaluation_id);

CREATE FUNCTION deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable record' USING ERRCODE='23514'; END $$;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER documents_immutable BEFORE UPDATE OR DELETE ON documents
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER reviews_immutable BEFORE UPDATE OR DELETE ON reviews
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();

CREATE FUNCTION guard_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.published_at IS NOT NULL THEN
  RAISE EXCEPTION 'published policy is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER policy_immutable BEFORE UPDATE OR DELETE ON policy_versions
 FOR EACH ROW EXECUTE FUNCTION guard_policy();

CREATE FUNCTION guard_evaluation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR OLD.processing_state='DRAFT_READY'
 OR (NEW.case_id,NEW.input_hash,NEW.snapshot,NEW.versions,NEW.prepared_by)
 IS DISTINCT FROM (OLD.case_id,OLD.input_hash,OLD.snapshot,OLD.versions,OLD.prepared_by) THEN
  RAISE EXCEPTION 'evaluation snapshot is immutable' USING ERRCODE='23514';
 END IF;
 IF OLD.policy_id IS NOT NULL AND NEW.policy_id IS DISTINCT FROM OLD.policy_id THEN
  RAISE EXCEPTION 'policy version is pinned' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER evaluation_immutable BEFORE UPDATE OR DELETE ON evaluations
 FOR EACH ROW EXECUTE FUNCTION guard_evaluation();

CREATE FUNCTION guard_case_evaluation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.current_evaluation_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM evaluations WHERE id=NEW.current_evaluation_id AND case_id=NEW.id) THEN
  RAISE EXCEPTION 'evaluation belongs to another case' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER case_current_evaluation BEFORE INSERT OR UPDATE ON cases
 FOR EACH ROW EXECUTE FUNCTION guard_case_evaluation();

CREATE FUNCTION guard_document_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM evaluations e JOIN documents d ON d.case_id=e.case_id
 WHERE e.id=NEW.evaluation_id AND d.id=NEW.document_id) THEN
  RAISE EXCEPTION 'document belongs to another case' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER document_binding BEFORE INSERT OR UPDATE ON evaluation_documents
 FOR EACH ROW EXECUTE FUNCTION guard_document_binding();

CREATE FUNCTION guard_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE media text;
BEGIN
 SELECT d.media_type INTO media FROM evaluation_documents ed JOIN documents d
 ON d.id=ed.document_id WHERE ed.evaluation_id=NEW.evaluation_id AND ed.document_id=NEW.document_id;
 IF media IS NULL THEN
  RAISE EXCEPTION 'document not in snapshot' USING ERRCODE='23514';
 END IF;
 IF media='application/pdf' THEN
  IF NOT (NEW.locator ?& ARRAY['page','start','end']) OR
    jsonb_typeof(NEW.locator->'page') IS DISTINCT FROM 'number' OR
    jsonb_typeof(NEW.locator->'start') IS DISTINCT FROM 'number' OR
    jsonb_typeof(NEW.locator->'end') IS DISTINCT FROM 'number' OR
    (NEW.locator->>'page')::int < 1 OR (NEW.locator->>'start')::int < 0 OR
    (NEW.locator->>'end')::int <= (NEW.locator->>'start')::int THEN
   RAISE EXCEPTION 'invalid PDF locator' USING ERRCODE='23514';
  END IF;
 ELSIF media='text/csv' THEN
  IF NOT (NEW.locator ?& ARRAY['row','column']) OR
   jsonb_typeof(NEW.locator->'row') IS DISTINCT FROM 'number' OR
   jsonb_typeof(NEW.locator->'column') IS DISTINCT FROM 'string' OR
   (NEW.locator->>'row')::int < 2 OR length(trim(NEW.locator->>'column'))=0 THEN
   RAISE EXCEPTION 'invalid CSV locator' USING ERRCODE='23514';
  END IF;
 ELSE RAISE EXCEPTION 'unsupported media' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER evidence_locator BEFORE INSERT OR UPDATE ON evidence
 FOR EACH ROW EXECUTE FUNCTION guard_evidence();

CREATE FUNCTION guard_finalized_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE eval_id uuid; state text;
BEGIN
 IF TG_OP='DELETE' THEN eval_id:=OLD.evaluation_id; ELSE eval_id:=NEW.evaluation_id; END IF;
 IF TG_OP='UPDATE' AND NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id THEN
  RAISE EXCEPTION 'evaluation binding is immutable' USING ERRCODE='23514';
 END IF;
 SELECT processing_state INTO state FROM evaluations WHERE id=eval_id FOR UPDATE;
 IF state='DRAFT_READY' THEN
  RAISE EXCEPTION 'finalized evaluation is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER evidence_finalized BEFORE INSERT OR UPDATE OR DELETE ON evidence
 FOR EACH ROW EXECUTE FUNCTION guard_finalized_child();
CREATE TRIGGER facts_finalized BEFORE INSERT OR UPDATE OR DELETE ON facts
 FOR EACH ROW EXECUTE FUNCTION guard_finalized_child();
CREATE TRIGGER calculations_finalized BEFORE INSERT OR UPDATE OR DELETE ON calculations
 FOR EACH ROW EXECUTE FUNCTION guard_finalized_child();
CREATE TRIGGER bindings_finalized BEFORE INSERT OR UPDATE OR DELETE ON evaluation_documents
 FOR EACH ROW EXECUTE FUNCTION guard_finalized_child();

CREATE FUNCTION guard_fact_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE eval_id uuid; state text;
BEGIN
 SELECT evaluation_id INTO eval_id FROM facts
 WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.fact_id ELSE NEW.fact_id END;
 SELECT processing_state INTO state FROM evaluations WHERE id=eval_id FOR UPDATE;
 IF state='DRAFT_READY' THEN
  RAISE EXCEPTION 'finalized evidence links are immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.fact_id,NEW.evidence_id) IS DISTINCT FROM
 (OLD.fact_id,OLD.evidence_id) THEN
  RAISE EXCEPTION 'replace evidence link explicitly' USING ERRCODE='23514';
 END IF;
 IF TG_OP <> 'DELETE' AND NOT EXISTS
 (SELECT 1 FROM evidence WHERE id=NEW.evidence_id AND evaluation_id=eval_id) THEN
  RAISE EXCEPTION 'cross-evaluation evidence' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fact_evidence_binding BEFORE INSERT OR UPDATE OR DELETE ON fact_evidence
 FOR EACH ROW EXECUTE FUNCTION guard_fact_evidence();

CREATE FUNCTION require_fact_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fact_key uuid;
BEGIN
 IF TG_TABLE_NAME='facts' THEN fact_key:=NEW.id;
 ELSIF TG_OP='DELETE' THEN fact_key:=OLD.fact_id; ELSE fact_key:=NEW.fact_id; END IF;
 IF EXISTS(SELECT 1 FROM facts WHERE id=fact_key AND status='extracted') AND NOT EXISTS
 (SELECT 1 FROM fact_evidence WHERE fact_id=fact_key) THEN
  RAISE EXCEPTION 'extracted fact requires evidence' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER fact_requires_evidence AFTER INSERT OR UPDATE ON facts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_fact_evidence();
CREATE CONSTRAINT TRIGGER link_requires_evidence AFTER DELETE OR UPDATE ON fact_evidence
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_fact_evidence();

CREATE FUNCTION guard_calculation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF cardinality(NEW.input_fact_ids)=0 OR EXISTS
 (SELECT 1 FROM unnest(NEW.input_fact_ids) k WHERE NOT EXISTS
 (SELECT 1 FROM facts WHERE id=k AND evaluation_id=NEW.evaluation_id AND status='extracted')) THEN
  RAISE EXCEPTION 'invalid calculation inputs' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calculation_inputs BEFORE INSERT OR UPDATE ON calculations
 FOR EACH ROW EXECUTE FUNCTION guard_calculation();

CREATE FUNCTION guard_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target evaluations; current_id uuid;
BEGIN
 SELECT * INTO target FROM evaluations WHERE id=NEW.evaluation_id;
 SELECT current_evaluation_id INTO current_id FROM cases WHERE id=target.case_id FOR UPDATE;
 IF target.processing_state <> 'DRAFT_READY' OR current_id IS DISTINCT FROM target.id
 OR target.prepared_by=NEW.reviewer_id OR NOT EXISTS
 (SELECT 1 FROM case_members WHERE case_id=target.case_id AND actor_id=NEW.reviewer_id
 AND role='reviewer') THEN
  RAISE EXCEPTION 'review requires current ready evaluation and independent reviewer'
  USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER review_guard BEFORE INSERT ON reviews
 FOR EACH ROW EXECUTE FUNCTION guard_review();

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN
  GRANT USAGE ON SCHEMA public TO cds_runtime;
  GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO cds_runtime;
  REVOKE UPDATE,DELETE,TRUNCATE ON audit_events,documents,reviews FROM cds_runtime;
  REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM cds_runtime;
  REVOKE ALL ON alembic_version FROM cds_runtime;
  GRANT SELECT ON alembic_version TO cds_runtime;
  REVOKE INSERT,UPDATE,DELETE ON policy_versions FROM cds_runtime;
 END IF;
END $$;
