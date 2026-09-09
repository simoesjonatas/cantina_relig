# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/
RUN chmod +x /app/entrypoint.sh

# O entrypoint roda migrate + collectstatic e só então entrega para o CMD.
# Fica no ENTRYPOINT (e não no CMD) porque o "command:" do docker-compose
# substitui o CMD — era por isso que o collectstatic não rodava em produção.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "cantina.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
