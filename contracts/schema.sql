-- Reference export through 0002_ingestion. Apply changes with Alembic.
-- PostgreSQL 16 foundation schema.
CREATE TABLE cases (
 id uuid PRIMARY KEY, segment text NOT NULL CHECK (segment = 'SME'),
 currency char(3) NOT NULL CHECK (currency = 'USD'), cutoff date NOT NULL,
 current_evaluation_id uuid, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE case_members (
 case_id uuid REFERENCES cases(id), actor_id text NOT NULL,
 role text NOT NULL CHECK (role IN ('analyst','reviewer','auditor','admin')),
 PRIMARY KEY(case_id, actor_id, role)
);
CREATE TABLE policy_versions (
 id text PRIMARY KEY, segment text NOT NULL, currency char(3) NOT NULL,
 accounting_basis text NOT NULL CHECK (accounting_basis = 'individual'),
 valid_from date NOT NULL, valid_to date,
 content_sha256 char(64) NOT NULL, rules jsonb NOT NULL, published_at timestamptz,
 CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE documents (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES cases(id),
 sha256 char(64) NOT NULL, media_type text NOT NULL,
 byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 10485760),
 storage_key text UNIQUE NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE evaluations (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES cases(id),
 prepared_by text NOT NULL, policy_id text REFERENCES policy_versions(id),
 input_hash char(64) NOT NULL, snapshot jsonb NOT NULL, versions jsonb NOT NULL,
 processing_state text NOT NULL CHECK (processing_state IN (
 'CREATED','DOCUMENTS_RECEIVED','EXTRACTING','VALIDATING','POLICY_CHECK',
 'DRAFT_READY','FAILED_RETRYABLE','FAILED_TERMINAL')),
 recommendation jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(case_id,input_hash)
);
ALTER TABLE cases ADD CONSTRAINT current_evaluation_fk
 FOREIGN KEY(current_evaluation_id) REFERENCES evaluations(id);
CREATE TABLE evaluation_documents (
 evaluation_id uuid REFERENCES evaluations(id), document_id uuid REFERENCES documents(id),
 PRIMARY KEY(evaluation_id, document_id)
);
CREATE TABLE evidence (
 id uuid PRIMARY KEY, evaluation_id uuid NOT NULL REFERENCES evaluations(id),
 document_id uuid NOT NULL REFERENCES documents(id),
 locator jsonb NOT NULL, excerpt text NOT NULL, parser_version text NOT NULL
);
CREATE TABLE facts (
 id uuid PRIMARY KEY, evaluation_id uuid NOT NULL REFERENCES evaluations(id),
 key text NOT NULL, value numeric, currency char(3), unit text NOT NULL,
 period_start date NOT NULL, period_end date NOT NULL,
 status text NOT NULL CHECK (status IN ('extracted','missing','ambiguous','invalid')),
 confidence numeric CHECK (confidence >= 0 AND confidence <= 1),
 CHECK (period_end >= period_start), CHECK (status <> 'extracted' OR value IS NOT NULL)
);
CREATE TABLE fact_evidence (
 fact_id uuid REFERENCES facts(id), evidence_id uuid REFERENCES evidence(id),
 PRIMARY KEY(fact_id,evidence_id)
);
CREATE TABLE calculations (
 id uuid PRIMARY KEY, evaluation_id uuid NOT NULL REFERENCES evaluations(id),
 formula_id text NOT NULL, formula_version text NOT NULL,
 input_fact_ids uuid[] NOT NULL, result numeric, status text NOT NULL
);
CREATE TABLE reviews (
 id uuid PRIMARY KEY, evaluation_id uuid UNIQUE NOT NULL REFERENCES evaluations(id),
 reviewer_id text NOT NULL, decision text NOT NULL CHECK (
 decision IN ('APPROVED','REJECTED','NEEDS_MORE_INFO')),
 reason text NOT NULL CHECK (length(trim(reason)) > 0),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, evaluation_id uuid NOT NULL REFERENCES evaluations(id),
 step text NOT NULL, input_hash char(64) NOT NULL, status text NOT NULL,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 lease_until timestamptz, worker_id text, result jsonb,
 UNIQUE(evaluation_id,step,input_hash)
);
CREATE TABLE audit_events (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES cases(id),
 sequence bigint NOT NULL, actor_id text NOT NULL, kind text NOT NULL,
 payload jsonb NOT NULL, previous_hash char(64), event_hash char(64) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(case_id,sequence)
);
CREATE TABLE idempotency_records (
 actor_id text NOT NULL, route text NOT NULL, key text NOT NULL,
 payload_hash char(64) NOT NULL, response jsonb NOT NULL,
 response_status integer NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(actor_id,route,key)
);

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


ALTER TABLE documents ADD CONSTRAINT unique_case_document UNIQUE(case_id,sha256);
CREATE TABLE document_contents (
 document_id uuid PRIMARY KEY REFERENCES documents(id),
 data bytea NOT NULL CHECK(octet_length(data) BETWEEN 1 AND 10485760),
 parsed jsonb NOT NULL CHECK(parsed->'metadata'->>'synthetic'='true'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER contents_immutable BEFORE UPDATE OR DELETE ON document_contents
 FOR EACH ROW EXECUTE FUNCTION deny_mutation();
CREATE FUNCTION limit_case_documents() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM id FROM cases WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM documents WHERE case_id=NEW.case_id)>=20 THEN
  RAISE EXCEPTION 'case document limit reached' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER case_document_limit BEFORE INSERT ON documents
 FOR EACH ROW EXECUTE FUNCTION limit_case_documents();
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='cds_runtime') THEN
  GRANT SELECT,INSERT ON document_contents TO cds_runtime;
 END IF;
END $$;
