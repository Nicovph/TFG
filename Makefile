# Makefile defines containerized development and verification commands while
# retaining an explicit Django configuration check for the local virtual environment.

# Default Python executable used by the Makefile targets.
# This can be overridden by setting the PYTHON environment variable.
PYTHON ?= python3

# Default Compose command used to run containerized project tasks.
COMPOSE ?= docker compose

# Preserve the host developer's ownership on migration files generated through
# the writable backend bind mount instead of assigning them to a container UID.
HOST_UID ?= $(shell id -u)
HOST_GID ?= $(shell id -g)

# Run trusted schema-management tasks with the dedicated migrator credentials
# and internal database network defined by the backend-migrate service.
MIGRATION_TASK = $(COMPOSE) --profile migrate run --rm --build

# Build the current Django source and run tests in the dedicated one-off
# service. That service owns the isolated database credentials and network.
TEST_COMMAND = $(COMPOSE) --profile test run --rm --build \
	backend-test python manage.py test

# Declare non-file targets so Make does not treat them as real files.
.PHONY: run migrate makemigrations check check-local test test1 test2 test3 test4

# Build and run the complete development stack in the background.
run:
	$(COMPOSE) up --build -d

# Apply committed migrations from a disposable container that can reach the
# unexposed PostgreSQL service and receives only migrator credentials.
migrate:
	$(MIGRATION_TASK) backend-migrate

# Generate migrations inside the trusted migration container while persisting
# only the backend source tree to the host. Running with the host UID/GID keeps
# generated files editable without changing their ownership afterwards.
makemigrations:
	$(MIGRATION_TASK) \
		--user "$(HOST_UID):$(HOST_GID)" \
		--volume "$(CURDIR)/backend:/app/backend" \
		backend-migrate python manage.py makemigrations

# Validate the same Django application profile, secrets, and networking used by
# the containerized runtime rather than relying on host-only configuration.
check:
	$(COMPOSE) run --rm --build backend python manage.py check

# Retain an explicit local check for IDE and virtual-environment workflows. It
# validates local settings, but it does not replace the Compose runtime check.
check-local:
	DJANGO_DB_PROFILE=app $(PYTHON) manage.py check

test:
	$(TEST_COMMAND)

test1:
	$(TEST_COMMAND) backend/accounts

test2:
	$(TEST_COMMAND) backend/audit

test3:
	$(TEST_COMMAND) backend/preferences

test4:
	$(TEST_COMMAND) backend/interpretation
