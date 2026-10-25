-- This small directory lives beside the regular application tables.
-- Each entry points to a private, temporary set of fictional demo tables.
CREATE TABLE IF NOT EXISTS demo_workspaces (
  id UUID PRIMARY KEY,
  schema_name VARCHAR(64) UNIQUE NOT NULL,
  student_id INTEGER NOT NULL,
  faculty_id INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_demo_expiration ON demo_workspaces (expires_at);
