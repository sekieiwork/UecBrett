#!/bin/sh

# ▼▼▼ 追加: DBの履歴不整合を直すためのリセット処理 ▼▼▼
echo "Resetting alembic history..."
python -c "
from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        # 履歴テーブル(alembic_version)だけを消して、無理やり適用できるようにする
        conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
        conn.commit()
"
# ▲▲▲ ここまで追加 ▲▲▲

# データベースのマイグレーション（テーブル作成）を実行する
echo "Running database migrations..."
flask db upgrade

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000