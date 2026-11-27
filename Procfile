web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-2} --threads 4 --timeout 60 --log-file -
