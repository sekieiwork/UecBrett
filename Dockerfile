# Python 3.13の公式イメージを使用
FROM python:3.13-slim

# ビルドに必要なOSの依存関係をインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
# pip installが失敗した場合でも、詳細なログを出力する
RUN pip install --no-cache-dir -r requirements.txt || true

# アプリケーションのコードをコンテナにコピー
COPY . .

# アプリケーションを起動
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]