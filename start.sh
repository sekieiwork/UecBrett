#!/bin/sh

echo "!!! RESETTING DATABASE FOR CLEAN DEPLOY !!!"

# 1. 既存のテーブルを全て削除して、真っ白にする
python -c "from app import app, db; app.app_context().push(); db.drop_all(); db.session.commit()"

# 2. 履歴テーブルの残骸も念のため消す
python -c "
from app import app, db
from sqlalchemy import text
with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
        conn.commit()
"

# 3. マイグレーション適用（全テーブルを新規作成）
echo "Running database migrations..."
flask db upgrade

# 4. サーバー起動
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000