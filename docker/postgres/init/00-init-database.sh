#!/usr/bin/env bash
# Use /usr/bin/env to locate bash for greater portability across systems.

set -Eeuo pipefail
# Strict mode for safer scripts:
# -E: It propagates errors in functions and traps.
# -e: Exit on first error.
# -u: Treat unset variables as errors.
# -o pipefail: Fail a pipeline if any command fails.

read_env_value() {
    local file_path="$1"
    local variable_name="$2"
    local line
    local value

    if [[ ! -r "$file_path" ]]; then # Check if the file exists and if the user has read permissions.
        echo "Error: no se puede leer el secreto $file_path." >&2
        exit 1
    fi

    # Read the first line that starts with VAR_NAME= (safe grep)
    line="$(grep -m1 "^${variable_name}=" "$file_path" || true)"
    # Using `|| true` prevents the script from exiting if grep finds nothing.

    if [[ -z "$line" ]]; then # If the variable is not found, it throws an error.
        echo "Error: falta ${variable_name} en $file_path." >&2
        exit 1
    fi

    # Remove the leading 'VAR=' and any Windows CR at end of line
    value="${line#*=}"
    value="${value%$'\r'}"

    if [[ -z "$value" ]]; then
        echo "Error: ${variable_name} está vacío en $file_path." >&2
        exit 1
    fi

    # Print the cleaned value without extra newline
    printf '%s' "$value"
}


APP_CONFIG_FILE="/run/secrets/db_app_config"
MIGRATE_CONFIG_FILE="/run/secrets/db_migrate_config"
TEST_CONFIG_FILE="/run/secrets/db_test_config"
# Define las rutas donde Docker monta los secrets (archivos de solo lectura).

APP_USER="$(read_env_value "$APP_CONFIG_FILE" "POSTGRES_USER")"
APP_PASSWORD="$(read_env_value "$APP_CONFIG_FILE" "POSTGRES_PASSWORD")"
# Extrae el usuario y contraseña del archivo de la aplicación.

MIGRATOR_USER="$(
    read_env_value "$MIGRATE_CONFIG_FILE" "POSTGRES_USER"
)"
MIGRATOR_PASSWORD="$(
    read_env_value "$MIGRATE_CONFIG_FILE" "POSTGRES_PASSWORD"
)"
TEST_USER="$(
    read_env_value "$TEST_CONFIG_FILE" "POSTGRES_USER"
)"
TEST_PASSWORD="$(
    read_env_value "$TEST_CONFIG_FILE" "POSTGRES_PASSWORD"
)"


# Fail fast if secrets point to unexpected roles (safety check)
if [[ "$APP_USER" != "traductor_tea_app" ]]; then
    echo "Error: el usuario de aplicación debe ser traductor_tea_app." >&2
    exit 1
fi

if [[ "$MIGRATOR_USER" != "traductor_tea_migrator" ]]; then
    echo "Error: el usuario de migraciones debe ser traductor_tea_migrator." >&2
    exit 1
fi

if [[ "$TEST_USER" != "traductor_tea_test" ]]; then
    echo "Error: el usuario de tests debe ser traductor_tea_test." >&2
    exit 1
fi

# Execute the SQL initialization file using psql.
# --set=ON_ERROR_STOP=1 will cause psql to exit on the first SQL error.
psql \
    --set=ON_ERROR_STOP=1 \
    --set=app_password="$APP_PASSWORD" \
    --set=migrator_password="$MIGRATOR_PASSWORD" \
    --set=test_password="$TEST_PASSWORD" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --file=/opt/traductor-tea/sql/01-init-database.sql

# Security: unset sensitive variables as soon as they are no longer needed
# to reduce the window where secrets may reside in process memory.
unset APP_PASSWORD
unset MIGRATOR_PASSWORD
unset TEST_PASSWORD