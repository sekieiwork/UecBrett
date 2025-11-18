import os
import psycopg2

# 目標とするリビジョンID (dark_modeのない最初の状態)
TARGET_REVISION = '21dbbc274d99'

# 環境変数からDATABASE_URLを取得
DB_URL = os.environ.get('DATABASE_URL')

if DB_URL:
    try:
        # DBに接続
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # 1. alembic_version テーブルからすべての履歴を削除
        cursor.execute("DELETE FROM alembic_version;")
        
        # 2. 正しい開始リビジョンを挿入
        cursor.execute(f"INSERT INTO alembic_version (version_num) VALUES ('{TARGET_REVISION}');")
        print(f"Database history successfully stamped to {TARGET_REVISION}.")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"FATAL DB HISTORY FIX ERROR: {e}")
        # 接続またはSQL実行エラーが発生したら、デプロイを失敗させる
        exit(1)