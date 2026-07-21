#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${WRITER_DB_PASSWORD:?WRITER_DB_PASSWORD is required}"
: "${WEB_DB_PASSWORD:?WEB_DB_PASSWORD is required}"

host_args=""
if [ -n "${PGHOST:-}" ]; then
  export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required with PGHOST}"
  host_args="--host=$PGHOST --port=${PGPORT:-5432}"
fi

# shellcheck disable=SC2086
psql $host_args \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=admin_role="$POSTGRES_USER" \
  --set=writer_password="$WRITER_DB_PASSWORD" \
  --set=web_password="$WEB_DB_PASSWORD" <<-'SQL'
SELECT 'CREATE ROLE crypto_writer LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_writer') \gexec
SELECT 'CREATE ROLE crypto_web LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') \gexec

SELECT format(
    'ALTER ROLE crypto_writer WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'writer_password'
) \gexec
SELECT format(
    'ALTER ROLE crypto_web WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'web_password'
) \gexec

GRANT CONNECT ON DATABASE :"DBNAME" TO crypto_writer, crypto_web;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO crypto_writer, crypto_web;

ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crypto_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT SELECT ON TABLES TO crypto_web;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO crypto_writer, crypto_web;
SQL
