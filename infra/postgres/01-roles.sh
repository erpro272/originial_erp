#!/bin/sh
# Runs once when the Postgres volume is first created.
# erp_owner (POSTGRES_USER) owns the schema and runs migrations.
# erp_app is what the API uses: NOT superuser, NOT owner, NO BYPASSRLS -> RLS applies.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE erp_app LOGIN PASSWORD '${ERP_APP_DB_PASSWORD:-erp_app}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO erp_app;
GRANT USAGE ON SCHEMA public TO erp_app;
CREATE DATABASE erp_test OWNER "$POSTGRES_USER";
GRANT CONNECT ON DATABASE erp_test TO erp_app;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname erp_test -c "GRANT USAGE ON SCHEMA public TO erp_app;"
