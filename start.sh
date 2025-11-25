#!/bin/sh
echo "Running database migrations..."
flask db upgrade
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000