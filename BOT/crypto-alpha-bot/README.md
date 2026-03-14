# Crypto Alpha Bot

X（Twitter）の暗号通貨エッジ投稿を自動検出してTelegramに送るBOT

```
X監視（Cookie認証・無料）→ Claude AI判定 → Telegram送信
```

## セットアップ手順

### Step 1: パッケージインストール

```bash
cd crypto-alpha-bot
bash setup.sh
```

### Step 2: Telegram Botを作成

1. Telegramで **@BotFather** に `/newbot`
2. Bot名・ユーザー名を設定 → `TELEGRAM_BOT_TOKEN` を取得
3. **@userinfobot** に `/start` → `TELEGRAM_CHAT_ID` を取得

### Step 3: X（Twitter）Cookie取得

1. Chrome/EdgeでX.comにログイン
2. F12 → Application → Cookies → `twitter.com`
3. 以下3つをコピー:
   - `auth_token` → `TWITTER_AUTH_TOKEN`
   - `ct0` → `TWITTER_CT0`
   - `twid` → `TWITTER_TWID`

### Step 4: .env を設定

```bash
cp .env.example .env
nano .env  # 各値を入力
```

### Step 5: 動作確認

```bash
source venv/bin/activate
python bot.py        # 1回だけ実行してテスト
```

### Step 6: 定期実行（30分ごと）

```bash
# バックグラウンドで常時起動
nohup python bot.py --loop > bot.log 2>&1 &

# 停止するとき
pkill -f "python bot.py"
```

## 監視しているキーワード

| カテゴリ | 内容 |
|---------|------|
| 英語アルファ | gem, edge, underrated, alpha, 100x |
| 日本語アルファ | エッジ、仕込む、先行、秘密、ポジション |
| テーマ特化 | RWA, DePIN, AI agent crypto |
| 価格予測 | ビットコイン 次 動く、アルト 上昇 |

## AIスコア基準

| スコア | 意味 | Telegram送信 |
|--------|------|-------------|
| 9-10 | 明確なエッジ（具体的銘柄・戦略・数値） | ✅ 送信 |
| 7-8  | エッジの可能性（示唆が深い） | ✅ 送信 |
| 5-6  | 一般的な情報 | ❌ 送信しない |
| 1-4  | 煽り・宣伝・無価値 | ❌ 送信しない |

## Telegram通知のフォーマット例

```
₿ 暗号通貨エッジ検出 ₿

📊 スコア: 8/10 ⭐⭐⭐⭐⭐⭐⭐⭐
🏷 カテゴリ: ALT

💡 エッジ要約:
SOLのDePINセクターで3月中旬に大口の仕込みが確認。特定プロジェクトのTVLが急増。

📝 原文:
[ツイート本文]

👤 @username（フォロワー: 12,000人）
❤️ 234　🔁 89

🔗 元ツイートを見る
🕐 2026-03-12 10:00 UTC
```

## ファイル構成

```
crypto-alpha-bot/
├── bot.py              # メインBOT
├── requirements.txt    # 依存パッケージ
├── setup.sh            # セットアップスクリプト
├── .env.example        # 設定テンプレート
├── .env                # 実際の設定（git管理外）
├── seen_tweets.json    # 送信済みツイートID（重複防止）
└── bot.log             # 実行ログ
```

## コスト試算

| 項目 | コスト |
|------|--------|
| X Cookie認証 | 無料 |
| Claude Haiku（AI判定） | 約$0.01/100ツイート |
| Telegram Bot API | 無料 |
| **合計（月間）** | **$1〜5/月** |
