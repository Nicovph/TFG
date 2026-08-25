#!/usr/bin/env bash
# Build and exercise an isolated Compose stack without touching developer data.

set -Eeuo pipefail
# Read/write/execute permission for the owner.
umask 077

# $$ is the PID of the current process.
clean_project_name="traductor-tea-clean-$$"
clean_temp_dir="$(mktemp -d /tmp/traductor-tea-clean.XXXXXX)"
clean_http_port="${CLEAN_HTTP_PORT:-18080}"
clean_https_port="${CLEAN_HTTPS_PORT:-18443}"
clean_env_file="$clean_temp_dir/compose.env"
clean_secret_dir="$clean_temp_dir/secrets"
mkdir "$clean_secret_dir"

if [[ "$clean_temp_dir" != /tmp/traductor-tea-clean.* ]]; then
    echo "El directorio temporal no es seguro." >&2
    exit 1
fi

# Defines the handler for when execution finishes or is interrupted.
# Remove only resources owned by this unique project and its temporary files.
cleanup() {
    # Store the exact exit code with which the routine was invoked.
    local exit_code=$?
    # Remove the trap to prevent infinite loops during dismantling.
    trap - EXIT INT TERM
    # If the script fails, print all accumulated Docker logs to stderr before destroying the stack.
    if (( exit_code != 0 )); then
        "${clean_compose[@]}" logs --no-color >&2 || true
    fi
    # Aggressively cleans up containers, created volumes, orphaned containers, and generated local images.
    "${clean_compose[@]}" down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
    # Destroys the temporary directory and its secrets on the host disk.
    rm -rf -- "$clean_temp_dir"
    exit "$exit_code"
}

# Create one role-specific PostgreSQL dotenv secret with a random password.
write_database_secret() {
    local role_name="$1"
    local output_path="$2"
    # Redirects the keys using the username passed as an argument.
    printf 'POSTGRES_USER=%s\nPOSTGRES_PASSWORD=' "$role_name" > "$output_path"
    #Generates a cryptographically secure pseudorandom key of 48 hexadecimal characters and concatenates it.
    openssl rand -hex 24 >> "$output_path"
}

write_database_secret traductor_tea_app "$clean_secret_dir/db-app.env"
write_database_secret traductor_tea_migrator "$clean_secret_dir/db-migrate.env"
write_database_secret traductor_tea_test "$clean_secret_dir/db-test.env"
openssl rand -hex 24 > "$clean_secret_dir/db-admin-password.txt"
openssl rand -hex 32 > "$clean_secret_dir/django-secret-key.txt"
openssl rand -hex 24 > "$clean_secret_dir/google-oidc-client-secret.txt"
openssl rand -hex 24 > "$clean_secret_dir/groq-api-key.txt"
openssl rand -hex 32 > "$clean_secret_dir/interpretation-hmac-key.txt"
# Keep the host directory private while allowing each non-root container user
# to read only the secret files explicitly mounted into that container.
chmod 0444 "$clean_secret_dir"/*

printf '%s\n' \
    "COMPOSE_HTTP_PORT=$clean_http_port" \
    "COMPOSE_HTTPS_PORT=$clean_https_port" \
    "FRONTEND_AUTH_RETURN_URL=https://localhost:$clean_https_port/" \
    "GOOGLE_OIDC_CLIENT_ID=clean-e2e.apps.googleusercontent.com" \
    "GOOGLE_OIDC_REDIRECT_URI=https://localhost:$clean_https_port/api/auth/google/callback/" \
    "POSTGRES_ADMIN_PASSWORD_SOURCE_FILE=$clean_secret_dir/db-admin-password.txt" \
    "DB_APP_CONFIG_SOURCE_FILE=$clean_secret_dir/db-app.env" \
    "DB_MIGRATE_CONFIG_SOURCE_FILE=$clean_secret_dir/db-migrate.env" \
    "DB_TEST_CONFIG_SOURCE_FILE=$clean_secret_dir/db-test.env" \
    "DJANGO_SECRET_KEY_SOURCE_FILE=$clean_secret_dir/django-secret-key.txt" \
    "GOOGLE_OIDC_CLIENT_SECRET_SOURCE_FILE=$clean_secret_dir/google-oidc-client-secret.txt" \
    "GROQ_API_KEY_SOURCE_FILE=$clean_secret_dir/groq-api-key.txt" \
    "INTERPRETATION_HMAC_KEY_SOURCE_FILE=$clean_secret_dir/interpretation-hmac-key.txt" \
    > "$clean_env_file"

# Create a Bash array as a wrapper for the Compose CLI, ensuring that all subcommands point to the isolated project and its variables.
clean_compose=(docker compose --project-name "$clean_project_name" --env-file "$clean_env_file")
# Registers the cleanup function to run automatically on any clean exit (EXIT) or abrupt interruption (SIGINT, SIGTERM).
trap cleanup EXIT INT TERM

"${clean_compose[@]}" config --quiet
"${clean_compose[@]}" --profile migrate build --no-cache backend backend-migrate frontend
"${clean_compose[@]}" --profile migrate run --rm backend-migrate
# Start the background services and wait up to 3 minutes for all health checks to transition to a healthy state.
"${clean_compose[@]}" up --detach --wait --wait-timeout 180
# Verify via the CLI that the frontend app is up and correctly indexing the DOM root node.
curl --fail --silent --show-error --insecure --retry 10 --retry-all-errors --retry-delay 1 \
    "https://localhost:$clean_https_port/" | grep -q '<div id="root"></div>'
# Verify that the API returns the expected payload in JSON format with a 200 OK status.
curl --fail --silent --show-error --insecure --retry 10 --retry-all-errors --retry-delay 1 \
    "https://localhost:$clean_https_port/api/health/" |
    jq -e '. == {"status":"ok","service":"django"}' >/dev/null

# Print only the session_key of the generated cookie to the screen, capturing it using `tail -n 1`.
e2e_session_cookie="$(
    "${clean_compose[@]}" exec -T backend python manage.py shell -c '
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from backend.accounts.models import CustomUser
from backend.preferences.models import UserPreferences
user = CustomUser.objects.create_user(google_subject="clean-e2e-subject")
UserPreferences.objects.create(user=user)
session = SessionStore()
session[SESSION_KEY] = str(user.pk)
session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
session[HASH_SESSION_KEY] = user.get_session_auth_hash()
session.save()
print(session.session_key)
' | tail -n 1
)"

# Injects values ​​via the E2E_BASE_URL and E2E_SESSION_COOKIE environment variables (to avoid having to log in manually via the UI).
E2E_BASE_URL="https://localhost:$clean_https_port" \
E2E_SESSION_COOKIE="$e2e_session_cookie" \
TMPDIR=/tmp \
npm --prefix frontend run test:e2e
