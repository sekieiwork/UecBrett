#!/bin/sh

echo "Running critical database history fix script..."
python fix_db_history.py

# データベースのマイグレーション（テーブル作成）を実行する
# (履歴が修正されたので、これは何もせず成功するはずです)
echo "Running standard Flask upgrade/check..."
flask db upgrade

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000