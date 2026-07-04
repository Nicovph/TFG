# Builds the Django development runtime image for the application service.
FROM python:3.13.14-slim-bookworm

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
# --no-cache-dir: Avoids save cache to reduce space in the container.
# Uses the pip associated to the Python interpreter defined.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser manage.py /app/manage.py
COPY --chown=appuser:appuser Traductor_TEA /app/Traductor_TEA
COPY --chown=appuser:appuser backend /app/backend

USER appuser

# Documents that the container listen in the 8000 port, however the actual publication is done in compose.yaml.
EXPOSE 8000

# Boots Django with the development server and is used 0.0.0.0 so that the container is accessible from the outside.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
