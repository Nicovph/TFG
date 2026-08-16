# Makefile defines local Django development and verification commands.

# Default Python executable used by the Makefile targets.
# This can be overridden by setting the PYTHON environment variable.
PYTHON ?= python3

# Keep tests isolated from real provider credentials and network configuration.
TEST_ENV = DJANGO_DB_PROFILE=test LLM_PROVIDER_REQUIRED=false \
	GROQ_API_KEY= GROQ_API_KEY_FILE= \
	INTERPRETATION_HMAC_KEY= INTERPRETATION_HMAC_KEY_FILE=

# Declare non-file targets so Make does not treat them as real files.
.PHONY: run migrate makemigrations check test test1 test2 test3 test4

run:
	DJANGO_DB_PROFILE=app $(PYTHON) manage.py runserver
	
migrate:
	DJANGO_DB_PROFILE=migrate $(PYTHON) manage.py migrate

makemigrations:
	DJANGO_DB_PROFILE=app $(PYTHON) manage.py makemigrations accounts audit preferences

# Validate the Django project configuration and identify common issues.
check:
	DJANGO_DB_PROFILE=app $(PYTHON) manage.py check

test:
	$(TEST_ENV) $(PYTHON) manage.py test

test1:
	$(TEST_ENV) $(PYTHON) manage.py test backend/accounts

test2:
	$(TEST_ENV) $(PYTHON) manage.py test backend/audit

test3:
	$(TEST_ENV) $(PYTHON) manage.py test backend/preferences

test4:
	$(TEST_ENV) $(PYTHON) manage.py test backend/interpretation
