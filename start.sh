#!/bin/sh

# データベースのマイグレーション（テーブル作成）を実行する
echo "Running database migrations..."
flask db upgrade

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000