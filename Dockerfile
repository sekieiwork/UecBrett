# Python 3.13の公式イメージを使用
FROM python:3.13-slim

# ビルドに必要なOSの依存関係をインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコンテナにコピー
COPY . .

# start.shの改行コードをLFに変換
RUN dos2unix ./start.sh

# 新しく作ったstart.shに実行権限を与える
RUN chmod +x ./start.sh

# Gunicornの代わりにstart.shを起動する
CMD ["./start.sh"]