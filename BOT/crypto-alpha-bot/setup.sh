#!/bin/bash
# Crypto Alpha Bot セットアップスクリプト

set -e

echo "======================================"
echo "  Crypto Alpha Bot セットアップ"
echo "======================================"

# 1. Python仮想環境
echo ""
echo "[1/4] Python仮想環境を作成中..."
python3 -m venv venv
source venv/bin/activate

# 2. 依存パッケージインストール
echo ""
echo "[2/4] パッケージをインストール中..."
pip install -q --upgrade pip
pip install -r requirements.txt

# 3. .env ファイル確認
echo ""
echo "[3/4] 環境変数ファイルを確認中..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  .env ファイルを作成しました。値を設定してください:"
    echo ""
    echo "  nano .env"
    echo ""
    echo "必須項目:"
    echo "  TELEGRAM_BOT_TOKEN  - @BotFatherで取得"
    echo "  TELEGRAM_CHAT_ID    - @userinfobot で /start して取得"
    echo "  TWITTER_AUTH_TOKEN  - ブラウザのCookieから取得"
    echo "  TWITTER_CT0         - ブラウザのCookieから取得"
    echo "  TWITTER_TWID        - ブラウザのCookieから取得"
    echo "  ANTHROPIC_API_KEY   - Anthropic Consoleで取得"
else
    echo "✅ .env ファイルが存在します"
fi

# 4. seen_tweets.json 初期化
echo ""
echo "[4/4] 初期化中..."
echo "[]" > seen_tweets.json
echo "✅ seen_tweets.json を初期化しました"

echo ""
echo "======================================"
echo "  セットアップ完了！"
echo "======================================"
echo ""
echo "次のステップ:"
echo "  1. .env ファイルに値を設定"
echo "  2. 動作確認:  source venv/bin/activate && python bot.py"
echo "  3. 定期実行:  source venv/bin/activate && python bot.py --loop"
echo "  4. バックグラウンド実行（推奨）:"
echo "     nohup python bot.py --loop > bot.log 2>&1 &"
echo ""
