from alembic import op

revision = "0002_ingestion"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

SQL = """
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
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER case_document_limit ON documents")
    op.execute("DROP FUNCTION limit_case_documents()")
    op.execute("DROP TABLE document_contents")
    op.execute("ALTER TABLE documents DROP CONSTRAINT unique_case_document")
