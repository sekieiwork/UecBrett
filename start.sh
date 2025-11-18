#!/bin/sh

# データベースの履歴を「dark_modeのない」最初の状態(21d...)にスタンプする
echo "Stamping database to revision 21dbbc274d99..."
flask db stamp 21dbbc274d99

# Webサーバー（Gunicorn）を起動する
echo "Starting Gunicorn server..."
gunicorn app:app --bind 0.0.0.0:8000