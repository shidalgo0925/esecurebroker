#!/usr/bin/env bash
# Provision dedicated Corredores Postgres (never touches iius_nodeone).
# Usage:
#   CORREDORES_DB_PASSWORD='...' sudo -E bash scripts/provision_postgres.sh
set -euo pipefail

DB_NAME="${CORREDORES_DB_NAME:-corredores}"
DB_TEST_NAME="${CORREDORES_DB_TEST_NAME:-corredores_test}"
DB_USER="${CORREDORES_DB_USER:-corredores_app}"
DB_PASSWORD="${CORREDORES_DB_PASSWORD:?Set CORREDORES_DB_PASSWORD}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (or sudo) so peer auth to postgres works." >&2
  exit 1
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

SELECT 'CREATE DATABASE ${DB_TEST_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_TEST_NAME}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
GRANT ALL PRIVILEGES ON DATABASE ${DB_TEST_NAME} TO ${DB_USER};
SQL

sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c \
  "ALTER SCHEMA public OWNER TO ${DB_USER}; GRANT ALL ON SCHEMA public TO ${DB_USER};"
sudo -u postgres psql -d "${DB_TEST_NAME}" -v ON_ERROR_STOP=1 -c \
  "ALTER SCHEMA public OWNER TO ${DB_USER}; GRANT ALL ON SCHEMA public TO ${DB_USER};"

echo "OK databases: ${DB_NAME}, ${DB_TEST_NAME} owner=${DB_USER}"
echo "Set DATABASE_URL=postgresql+psycopg://${DB_USER}:***@127.0.0.1:5432/${DB_NAME}"
echo "Set CORREDORES_TEST_DATABASE_URL=.../${DB_TEST_NAME} for pytest"
