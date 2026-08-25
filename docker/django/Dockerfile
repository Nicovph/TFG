# Build the non-root Django image used by runtime, migration, and test services.
FROM python:3.13.15-slim-bookworm

# Avoid Python to write .pyc (Python cache) files in the container, for cleaning and reproducibility
ENV PYTHONDONTWRITEBYTECODE=1
# It prevents Python output from being buffered, useful because it allows to see the logs immediately.
ENV PYTHONUNBUFFERED=1

# Creates a group and a system user called appuser, avoiding to execut Django with root inside the container.
RUN addgroup --system appuser \
    && adduser --system --ingroup appuser --no-create-home appuser
# appuser has not home directory, because the app is in /app

# This causes commands to be executed from that moment on as if they were in /app
WORKDIR /app 

COPY requirements.txt /app/requirements.txt
# Use the pip bundled with the pinned Python image instead of downloading the
# latest installer on every build. This removes an uncontrolled version change,
# while --no-cache-dir prevents package downloads from remaining in the image.
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser manage.py /app/manage.py
COPY --chown=appuser:appuser Traductor_TEA /app/Traductor_TEA
COPY --chown=appuser:appuser backend /app/backend
RUN mkdir /app/staticfiles && chown appuser:appuser /app/staticfiles

USER appuser

# Documents that the container listen in the 8000 port, however the actual publication is done in compose.yaml.
EXPOSE 8000

# Collect Admin assets before booting Django so Caddy can serve them with DEBUG disabled
# and is used 0.0.0.0 so that the container is accessible from the outside.
CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec python manage.py runserver 0.0.0.0:8000"]
