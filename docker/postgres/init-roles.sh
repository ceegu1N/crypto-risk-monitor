#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$APP_DB_PASSWORD" <<-'SQL'
SELECT format('CREATE ROLE crypto_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_app') \gexec

GRANT CONNECT ON DATABASE :DBNAME TO crypto_app;
GRANT USAGE, CREATE ON SCHEMA public TO crypto_app;
SQL
