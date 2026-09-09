#!/bin/sh
# Roda sempre, mesmo quando o docker-compose sobrescreve o "command:".
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
