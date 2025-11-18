#!/bin/sh

# データベースの履歴を強制的に最新版(abf...)にスタンプする
echo "Stamping database to revision abf7081a2a16..."
flask db stamp abf7081a2a16

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000