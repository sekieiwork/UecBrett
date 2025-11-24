#!/bin/sh

# ▼▼▼ 修正版: DB履歴のリセット処理 ▼▼▼
echo "Resetting alembic history..."
python -c "
from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
        conn.commit()
"
# ▲▲▲ ここまで修正 ▲▲▲

# データベースのマイグレーション（テーブル作成）を実行する
echo "Running database migrations..."
flask db upgrade

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000