# Python 3.13の公式イメージを使用
FROM python:3.13-slim

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコンテナにコピー
COPY . .

# アプリケーションを起動
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]