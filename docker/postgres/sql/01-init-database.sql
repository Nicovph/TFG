-- =========================================================
-- 01-init-database.sql
-- Purpose: Initialize PostgreSQL roles, database, schema ownership,
-- and privileges for the Traductor_TEA application.
--
-- Usage: Executed by the container init script. Passwords are passed
-- via psql variables (see the accompanying init script) to avoid
-- embedding secrets in source control.
--
-- Security notes:
-- - `password_encryption` is set to SCRAM-SHA-256 for stronger auth.
-- - The migrator role is the owner of the DB so it can create objects;
--   the application role receives only the runtime privileges needed.
-- =========================================================
\set ON_ERROR_STOP on

-- Use SCRAM-SHA-256 for password storage
SET password_encryption = 'scram-sha-256';


-- =========================================================
-- 1. Roles
-- =========================================================

CREATE ROLE traductor_tea_migrator
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS -- Ensures the role cannot bypass Row Level Security (RLS)
                -- Keeps RLS filters enforced.
    PASSWORD :'migrator_password'; -- password injected via psql `--set`

CREATE ROLE traductor_tea_app
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    PASSWORD :'app_password';

CREATE ROLE traductor_tea_test
    LOGIN
    NOSUPERUSER
    CREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    PASSWORD :'test_password';

-- =========================================================
-- 2. Data Base
-- =========================================================

CREATE DATABASE traductor_tea_db
    WITH
    OWNER = traductor_tea_migrator
    ENCODING = 'UTF8'
    TEMPLATE = template0; -- Create a clean DB from template0 for reproducibility


-- =========================================================
-- 3. Access to the database
-- =========================================================

REVOKE ALL
ON DATABASE traductor_tea_db
FROM PUBLIC; -- Remove default public access to reduce exposure

-- Allow only the migrator and application roles to connect at runtime
GRANT CONNECT
ON DATABASE traductor_tea_db
TO traductor_tea_migrator, traductor_tea_app;

GRANT CONNECT
ON DATABASE postgres
TO traductor_tea_test; -- The user used for testing needs
                       -- access to the default database postgres
                       -- to create temporary test databases during test runs. 


-- =========================================================
-- 4. Connection parameters
-- =========================================================

ALTER ROLE traductor_tea_app
IN DATABASE traductor_tea_db
SET client_encoding TO 'UTF8';

ALTER ROLE traductor_tea_app
IN DATABASE traductor_tea_db
SET default_transaction_isolation TO 'read committed';

ALTER ROLE traductor_tea_app
IN DATABASE traductor_tea_db
SET timezone TO 'UTC';


ALTER ROLE traductor_tea_migrator
IN DATABASE traductor_tea_db
SET client_encoding TO 'UTF8';

ALTER ROLE traductor_tea_migrator
IN DATABASE traductor_tea_db
SET default_transaction_isolation TO 'read committed';

ALTER ROLE traductor_tea_migrator
IN DATABASE traductor_tea_db
SET timezone TO 'UTC';


ALTER ROLE traductor_tea_test
SET client_encoding TO 'UTF8';

ALTER ROLE traductor_tea_test
SET default_transaction_isolation TO 'read committed';

ALTER ROLE traductor_tea_test
SET timezone TO 'UTC';

-- =========================================================
-- 5. Privileges inside the database
-- =========================================================

\connect traductor_tea_db

ALTER SCHEMA public
OWNER TO traductor_tea_migrator;

REVOKE ALL
ON SCHEMA public
FROM PUBLIC;

GRANT USAGE
ON SCHEMA public
TO traductor_tea_app;


-- Objects that already exists.
GRANT SELECT, INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA public
TO traductor_tea_app;

GRANT USAGE, SELECT
ON ALL SEQUENCES IN SCHEMA public
TO traductor_tea_app;


-- Objects that will be created in the future by the migrator role.
-- Default privileges: objects created by the migrator will automatically
-- grant the application role the required runtime permissions.
ALTER DEFAULT PRIVILEGES
FOR ROLE traductor_tea_migrator
IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLES
TO traductor_tea_app;

ALTER DEFAULT PRIVILEGES
FOR ROLE traductor_tea_migrator
IN SCHEMA public
GRANT USAGE, SELECT
ON SEQUENCES
TO traductor_tea_app; -- Allow app to use and read sequence values (e.g. serial IDs)