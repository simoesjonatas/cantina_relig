# # Dockerfile
# FROM python:3.11-slim

# ENV PYTHONDONTWRITEBYTECODE 1
# ENV PYTHONUNBUFFERED 1

# WORKDIR /app

# COPY requirements.txt /app/
# RUN pip install --upgrade pip && pip install -r requirements.txt

# COPY . /app/

# CMD ["gunicorn", "cantina.wsgi:application", "--bind", "0.0.0.0:8000"]

# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install gunicorn

COPY . /app/

# roda migrações e collectstatic antes de subir o servidor
CMD bash -lc "python manage.py migrate && (python manage.py collectstatic --noinput || true) && gunicorn cantina.wsgi:application --bind 0.0.0.0:8000"
