"""
Crypto Alpha Bot - 自動セットアップウィザード

実行するとブラウザが開いてX.comのCookieを自動取得し .env に保存します。
Telegram Bot Tokenは対話式で入力します。
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, set_key
from playwright.async_api import async_playwright

ENV_FILE = Path(".env")

# ============================================================
# カラー出力
# ============================================================
def ok(msg):  print(f"\033[92m✅ {msg}\033[0m")
def info(msg): print(f"\033[94mℹ️  {msg}\033[0m")
def warn(msg): print(f"\033[93m⚠️  {msg}\033[0m")
def err(msg):  print(f"\033[91m❌ {msg}\033[0m")
def step(n, msg): print(f"\n\033[1m{'='*50}\033[0m\n\033[1m STEP {n}: {msg}\033[0m\n{'='*50}")

# ============================================================
# STEP 1: X Cookie自動取得
# ============================================================
async def get_x_cookies() -> dict:
    step(1, "X（Twitter）Cookie を自動取得")
    info("ブラウザを開きます。X.com にログインしてください。")
    info("すでにログイン済みの場合は自動で取得します（最大60秒待機）。")

    cookies = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(viewport=None)
        page = await ctx.new_page()

        await page.goto("https://x.com/home", wait_until="domcontentloaded")

        print("\n  👉 X.com が開きました。")
        print("  👉 ログインしていない場合はログインしてください。")
        print("  👉 ホーム画面が表示されたら自動で Cookie を取得します...\n")

        # ホーム画面（ログイン完了）まで最大90秒待つ
        for i in range(90):
            current_url = page.url
            if "home" in current_url or "following" in current_url:
                # Cookie取得
                all_cookies = await ctx.cookies()
                for c in all_cookies:
                    if c["name"] == "auth_token":
                        cookies["auth_token"] = c["value"]
                    elif c["name"] == "ct0":
                        cookies["ct0"] = c["value"]
                    elif c["name"] == "twid":
                        cookies["twid"] = c["value"]

                if len(cookies) == 3:
                    break
            await asyncio.sleep(1)
            if i % 10 == 9:
                info(f"待機中... ({i+1}/90秒)")

        await browser.close()

    if len(cookies) == 3:
        ok(f"Cookie取得成功！")
        ok(f"  auth_token: {cookies['auth_token'][:10]}...")
        ok(f"  ct0:        {cookies['ct0'][:10]}...")
        ok(f"  twid:       {cookies['twid'][:15]}...")
    else:
        err(f"Cookie取得失敗（取得できた: {list(cookies.keys())}）")
        err("ログイン後にもう一度実行してください。")

    return cookies

# ============================================================
# STEP 2: Telegram セットアップ（対話式）
# ============================================================
async def setup_telegram() -> dict:
    step(2, "Telegram Bot セットアップ")

    print("""
  📱 スマホの Telegram アプリで以下の手順を行ってください:

  【Bot Token の取得】
  1. Telegram の検索バーで「BotFather」を検索（青チェックマーク付き）
  2. BotFather を開いて「/newbot」と送信
  3. Bot 名を入力（例: Crypto Alpha Bot）
  4. ユーザー名を入力（末尾に "bot" 必須、例: my_cryptoalpha_bot）
  5. 成功すると以下のようなトークンが表示されます:
     7123456789:AAF_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

  【Chat ID の取得】
  1. Telegram で「userinfobot」を検索
  2. 開いて「/start」と送信
  3. 「Id: 123456789」のように数字が返ってくる
""")

    token = input("  🔑 Bot Token を貼り付けてください: ").strip()
    chat_id = input("  💬 Chat ID を入力してください: ").strip()

    # 検証
    import urllib.request
    import json
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        res = urllib.request.urlopen(url, timeout=10)
        data = json.loads(res.read())
        bot_name = data["result"]["username"]
        ok(f"Bot 接続確認: @{bot_name}")

        # テストメッセージ送信
        msg_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": "🎉 Crypto Alpha Bot のセットアップが完了しました！\n\n暗号通貨のエッジ投稿を検出してここに届けます。"
        }).encode()
        req = urllib.request.Request(msg_url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        ok("Telegram にテストメッセージを送信しました！")

    except Exception as e:
        warn(f"検証エラー: {e}")
        warn("Token または Chat ID が間違っている可能性があります。後で確認してください。")

    return {"token": token, "chat_id": chat_id}

# ============================================================
# STEP 3: Anthropic API Key
# ============================================================
def setup_anthropic() -> str:
    step(3, "Anthropic API Key（Claude AI 判定用）")
    print("""
  Anthropic API Key が必要です。
  取得先: https://console.anthropic.com/

  ※ Claude Haiku を使用するため低コスト（月1〜5ドル程度）です。
""")
    existing = os.getenv("ANTHROPIC_API_KEY", "")
    if existing and existing != "sk-ant-api03-xxxxxxxxxxxx":
        ok(f"既存のキーを使用: {existing[:20]}...")
        use = input("  このキーを使いますか？ [Y/n]: ").strip().lower()
        if use != "n":
            return existing

    key = input("  🔑 API Key を貼り付けてください (sk-ant-...): ").strip()
    return key

# ============================================================
# STEP 4: .env に保存
# ============================================================
def save_env(x_cookies: dict, tg: dict, anthropic_key: str):
    step(4, ".env ファイルに保存")

    if not ENV_FILE.exists():
        import shutil
        shutil.copy(".env.example", ".env")

    mapping = {
        "TELEGRAM_BOT_TOKEN":  tg.get("token", ""),
        "TELEGRAM_CHAT_ID":    tg.get("chat_id", ""),
        "TWITTER_AUTH_TOKEN":  x_cookies.get("auth_token", ""),
        "TWITTER_CT0":         x_cookies.get("ct0", ""),
        "TWITTER_TWID":        x_cookies.get("twid", ""),
        "ANTHROPIC_API_KEY":   anthropic_key,
        "MONITOR_INTERVAL":    "1800",
        "ALPHA_SCORE_THRESHOLD": "7",
        "MAX_TWEETS_PER_RUN":  "5",
    }

    for key, val in mapping.items():
        if val:
            set_key(str(ENV_FILE), key, val)

    ok(".env に保存しました")
    print(f"\n  保存先: {ENV_FILE.resolve()}")

# ============================================================
# 完了メッセージ
# ============================================================
def show_complete():
    print(f"""
\033[92m
{'='*50}
  🎉 セットアップ完了！
{'='*50}

  次のコマンドで Bot を起動してください:

  【テスト実行（1回のみ）】
  source venv/bin/activate
  python bot.py

  【定期実行（30分ごと・バックグラウンド）】
  source venv/bin/activate
  nohup python bot.py --loop > bot.log 2>&1 &

  【停止するとき】
  pkill -f "python bot.py"

  【ログ確認】
  tail -f bot.log

{'='*50}
\033[0m""")

# ============================================================
# メイン
# ============================================================
async def main():
    print("""
\033[1m
╔══════════════════════════════════════════╗
║   Crypto Alpha Bot - 自動セットアップ   ║
╚══════════════════════════════════════════╝
\033[0m
  X（Twitter）のCookie取得とTelegram設定を
  自動で行います。約3〜5分で完了します。
""")
    load_dotenv()

    # STEP 1: X Cookie
    x_cookies = await get_x_cookies()

    # STEP 2: Telegram
    tg = await setup_telegram()

    # STEP 3: Anthropic
    anthropic_key = setup_anthropic()

    # STEP 4: 保存
    save_env(x_cookies, tg, anthropic_key)

    # 完了
    show_complete()

if __name__ == "__main__":
    asyncio.run(main())
