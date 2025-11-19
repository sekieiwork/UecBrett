import os
import psycopg2

# 環境変数からDATABASE_URLを取得
DB_URL = os.environ.get('DATABASE_URL')

if DB_URL:
    try:
        # DBに接続
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        # user_subscription テーブルの最新の5件を取得
        cursor.execute("SELECT id, user_id, LENGTH(subscription_json) FROM user_subscription ORDER BY id DESC LIMIT 5;")
        results = cursor.fetchall()
        
        print("\n--- PUSH SUBSCRIPTION CHECK ---")
        if results:
            print(f"Total active subscriptions found: {len(results)}")
            for row in results:
                # ユーザーIDとJSONのサイズを出力する
                print(f"ID: {row[0]}, User ID: {row[1]}, JSON Size: {row[2]} bytes")
        else:
            print("No active subscriptions found in the database.")
        print("-------------------------------\n")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"DATABASE CHECK ERROR: Failed to query user_subscription: {e}")
        # DBのチェックに失敗しても、アプリの起動は試みる