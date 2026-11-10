-- PostgreSQL 16. Diseño inicial; Alembic lo materializa y prueba en fase 1.
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
-- Fase 1: índices, permisos y triggers/mecanismos transaccionales probados para:
-- no solapar políticas publicadas; impedir UPDATE/DELETE de auditoría al rol runtime;
-- impedir cambiar políticas publicadas, documentos y evaluaciones finalizadas;
-- verificar pertenencia al mismo caso/evaluación en referencias cruzadas;
-- autor de revisión distinto de prepared_by; evaluación actual y DRAFT_READY;
-- evidencia requerida para facts extracted y validación de locator según formato.
-- No afirmar estas invariantes implementadas con este DDL preliminar.
