-- Executed once by the Postgres container on first boot.
-- Table DDL is owned by the backend (SQLAlchemy metadata); only extensions live here.
CREATE EXTENSION IF NOT EXISTS vector;
activate