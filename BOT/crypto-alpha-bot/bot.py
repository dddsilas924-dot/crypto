"""
Crypto Alpha Bot v3
「実績公開型アカウント」を世界中から監視 → エッジをTelegramに日本語で送信
・APIキー不要・完全無料
・自分のトレード結果・P&L・ボット稼働状況を公開してる人が対象
・そういう人から自然とエッジが漏れる

使い方:
  python bot.py          # 1回実行
  python bot.py --loop   # 30分ごと定期実行
"""

import os
import re
import json
import time
import logging
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

import urllib.parse
import requests
from twikit import Client as TwikitClient

# ============================================================
# Google翻訳（無料・APIキー不要）
# ============================================================
def translate_to_ja(text: str) -> str:
    """英語テキストを日本語に自動翻訳。失敗時は原文を返す"""
    try:
        # 日本語が多い場合はそのまま返す
        ja_chars = len(re.findall(r'[\u3040-\u9FFF]', text))
        if ja_chars / max(len(text), 1) > 0.2:
            return text
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx", "sl": "auto", "tl": "ja",
            "dt": "t", "q": text[:1000]
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.ok:
            result = resp.json()
            translated = "".join(part[0] for part in result[0] if part[0])
            return translated
    except Exception:
        pass
    return text

# ============================================================
# 設定
# ============================================================
load_dotenv()

TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "").strip("'\"")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID", "").strip("'\"")
TWITTER_AUTH_TOKEN    = os.getenv("TWITTER_AUTH_TOKEN", "").strip("'\"")
TWITTER_CT0           = os.getenv("TWITTER_CT0", "").strip("'\"")
TWITTER_TWID          = os.getenv("TWITTER_TWID", "").strip("'\"")
MONITOR_INTERVAL      = int(os.getenv("MONITOR_INTERVAL", "1800"))
ALPHA_SCORE_THRESHOLD = float(os.getenv("ALPHA_SCORE_THRESHOLD", "5"))
MAX_TWEETS_PER_RUN    = int(os.getenv("MAX_TWEETS_PER_RUN", "10"))

SEEN_FILE     = Path("seen_tweets.json")
ACCOUNTS_FILE = Path("watch_accounts.json")
USER_ID_CACHE = Path("user_id_cache.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ============================================================
# 監視アカウント
# 「自分のトレード結果・P&L・ボット稼働状況を公開してる人」
# こういう人から自然とエッジが漏れる
# ============================================================
INITIAL_ACCOUNTS = [
    # ── 日本語圏 SS/S級 botter（実績公開）──────────────────────
    "richmanbtc2",     # SS級 機械学習×BTC自動売買 年収10億円規模 著書あり
    "tomui_bitcoin",   # S級 200万→6億円 HL/Bybit ボット手法・成績公開
    "blog_uki",        # S級 株・暗号資産システムトレード ドテン君開発者
    "hht",             # S級 暗号資産botter 草コイン投機 note実績公開
    "QASH_NFT",        # アービトラージ専門 月次損益報告 2023年+6400万
    # ── 日本語圏 中堅botter（手法・結果公開）──────────────────
    "yodakaart",       # bot開発記録を週次公開 #80以上継続
    "autotradebtc",    # BTC自動売買ボット運用 結果公開
    "kkngo",           # 月次報告をnoteで公開
    "mtkn1",           # botterのためのデプロイ入門著者 Zennで手法公開
    "Harry_C_Botter",  # 初級botter 学習過程をXで公開
    "aiba_algo",       # アルゴ取引公開 初心者向けbot記事執筆
    "ros_1224",        # 仮想通貨BOTの開発論を執筆
    "ryota_trade",     # 文系向けBitcoin bot自動売買ブログ運営
    "chonan",          # botter 目標設定・FIRE論公開
    "kksbot",          # 2024 Advent Calendarまとめ執筆
    "daitote",         # 収益達成botter
    "3tomcha",         # TradingViewでbotter戦略解説
    "yodakaart",       # 週次bot開発記録
    # ── 日本語圏 情報発信系（エッジ多め）──────────────────────
    "coinkeiba",       # ツァビ FX→仮想通貨 ポジション公開
    "CryptoTimes_jp",  # 日本語速報
    "WuBlockchain",    # 業界ニュース速報
    "ikehaya",         # Web3投資家 情報発信
    # ── 英語圏 実績公開型トレーダー ──────────────────────────
    "HsakaTrades",     # デリバティブ市場 ポジション公開
    "cobie",           # UpOnlyポッドキャスト 実績・市場コメント公開
    "CryptoCobain",    # 長期運用実績をXで公開
    "CryptoCapo_",     # 価格予測・ポジションを定期公開
    "inversebrah",     # 逆張り戦略と実績をXで発信
    "MacnBTC",         # BTC先物 自動売買実績を定期公開
    "AltcoinPsycho",   # アルトコインbotトレード 実績ポスト
    "GiganticRebirth", # クジラウォレット追跡 大口アルゴ取引分析
    # ── 英語圏 OSSボット・アルゴ系 ───────────────────────────
    "freqtradeorg",    # Freqtrade公式 OSSアルゴ取引ボット実績共有
    "hummingbot",      # マーケットメイキングボット 収益構造公開
    "superalgos",      # OSSアルゴ取引基盤 シグナル競争で実績公開
    "jesse_ai_",       # Pythonクリプト取引フレームワーク開発者
    # ── オンチェーン分析（大口動向リアルタイム）────────────────
    "lookonchain",     # ウォレット追跡 大口トレード実績を即時公開
    "spotonchain",     # スマートマネー追跡
    "OnChainWizard",   # オンチェーン分析
    "EmberCN",         # オンチェーン分析（英語ツイートあり）
    "whale_alert",     # 大口送金リアルタイム
    # ── マクロ×クリプト（実績・見解公開）───────────────────────
    "woonomic",        # Willy Woo オンチェーン指標開発者
    "CryptoRand",      # クオンツ系戦略の実績を定期ポスト
    "rektcapital",     # チャートパターン分析 実績公開
    "BenjaminCowen",   # 定量・確率モデル分析
    "TechDev_52",      # BTC上級テクニカル
    "PlanB",           # S2Fモデル考案者 BTC価格予測と実績公開
    # ── Solana/DeFi 開発者（早期情報）──────────────────────────
    "aeyakovenko",     # Solana共同創設者
    "0xMert_",         # Helius Solana開発者情報
    "blknoiz06",       # Ansem Solana/AIエージェント早期発掘
    "Pentosh1",        # オンチェーン分析・トレード透明公開
    "hasufl",          # Flashbots研究者・MEV定量分析
]

# ============================================================
# ユーザーIDキャッシュ（レートリミット対策）
# ============================================================
def load_id_cache() -> dict:
    if USER_ID_CACHE.exists():
        return json.loads(USER_ID_CACHE.read_text())
    return {}

def save_id_cache(cache: dict):
    USER_ID_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

NOT_FOUND_MARKER = "__NOT_FOUND__"

def get_user_id(twitter: TwikitClient, username: str, cache: dict) -> str:
    key = username.lower()
    if key in cache:
        if cache[key] == NOT_FOUND_MARKER:
            raise ValueError(f"@{username} は存在しないアカウント（キャッシュ済み）")
        return cache[key]
    try:
        user = twitter.get_user_by_screen_name(username)
        cache[key] = user.id
        save_id_cache(cache)
        time.sleep(3.0)  # 新規取得時はゆっくり待つ
        return user.id
    except Exception as e:
        err_str = str(e)
        if "does not exist" in err_str or "User not found" in err_str or "The user" in err_str:
            cache[key] = NOT_FOUND_MARKER
            save_id_cache(cache)
        elif "429" in err_str or "Rate limit" in err_str:
            log.info("レートリミット到達 → 60秒待機")
            time.sleep(60)  # 429は1分待ってから続行
        raise

# ============================================================
# アカウント管理（動的追加）
# ============================================================
def load_accounts() -> list:
    if ACCOUNTS_FILE.exists():
        data = json.loads(ACCOUNTS_FILE.read_text())
        return data.get("accounts", INITIAL_ACCOUNTS)
    return list(INITIAL_ACCOUNTS)

def save_accounts(accounts: list):
    ACCOUNTS_FILE.write_text(json.dumps(
        {"accounts": list(dict.fromkeys(accounts)), "updated": datetime.now().isoformat()},
        ensure_ascii=False, indent=2
    ))

def add_account(username: str, reason: str = "自動発掘"):
    accounts = load_accounts()
    if username.lower() not in [a.lower() for a in accounts]:
        accounts.append(username)
        save_accounts(accounts)
        log.info(f"新アカウント追加: @{username}（{reason}）")
        send_telegram_text(
            f"👁 新しい監視アカウントを自動追加しました\n\n"
            f"アカウント: @{username}\n"
            f"理由: {reason}"
        )
        return True
    return False

# ============================================================
# 自動アカウント発掘
# ============================================================
def discover_accounts(twitter: TwikitClient, tweets: list, current_accounts: list):
    discovered = {}
    for tweet in tweets:
        mentions = re.findall(r'@(\w+)', tweet.text)
        for m in mentions:
            if m.lower() not in [a.lower() for a in current_accounts]:
                discovered[m] = discovered.get(m, 0) + 1
        if hasattr(tweet, 'quoted_tweet') and tweet.quoted_tweet:
            qt_user = tweet.quoted_tweet.user.screen_name
            if qt_user.lower() not in [a.lower() for a in current_accounts]:
                discovered[qt_user] = discovered.get(qt_user, 0) + 2

    candidates = [(u, c) for u, c in discovered.items() if c >= 2]
    candidates.sort(key=lambda x: x[1], reverse=True)

    id_cache = load_id_cache()
    added = 0
    for username, count in candidates[:5]:
        try:
            user = twitter.get_user_by_screen_name(username)
            if user.followers_count >= 1000:
                id_cache[username.lower()] = user.id
                save_id_cache(id_cache)
                reason = f"高スコア投稿で{count}回言及・フォロワー{user.followers_count:,}人"
                if add_account(username, reason):
                    added += 1
            time.sleep(1.5)
        except Exception:
            pass

    if added:
        log.info(f"自動発掘: {added}件のアカウントを追加")

# ============================================================
# スコアリング
# 「実績公開型」の投稿パターンを重視
# ============================================================

# ─────────────────────────────────────────────────────────────
# キーワード設計：「ポロっとエッジを落とす瞬間」を捕捉する
# ─────────────────────────────────────────────────────────────

# 【最高優先】実際に買ってる・売ってる動作（+1.0/個 最大+5）
ACTION_KEYWORDS = [
    # 日本語：買い動作
    "仕込み始めた", "仕込んだ", "仕込んでる", "仕込み中",
    "買い増した", "買い増してる", "少しずつ買", "ちょっと拾",
    "積み始めた", "拾い始めた", "拾ってる",
    "ポジション取った", "ロング建てた", "エントリーした",
    "利確した", "損切した", "決済した", "全決済",
    # 日本語：先行発見
    "誰も見てない", "気づいてない", "知られてない",
    "密かに", "こっそり", "ひっそり", "先に買",
    "これ来る", "これやばい", "注目してる", "マーク",
    "先週から", "先月から", "最近仕込",
    # 英語：買い動作
    "been buying", "been accumulating", "quietly buying",
    "added to my position", "added more", "loading up",
    "been dca", "dca-ing", "stacking sats", "been stacking",
    "took a position", "entered long", "entered short",
    "went long", "went short", "took profits", "cut my",
    # 英語：先行発見
    "nobody talking about", "nobody is watching",
    "been watching this", "been tracking this", "marking this",
    "under the radar", "sleeping giant",
    "before everyone", "early on this",
]

# 【高優先】ボット・自動売買の実況（+0.8/個 最大+4）
BOT_KEYWORDS = [
    "bot動いた", "bot稼いだ", "ボット走った", "シグナル出た",
    "条件満たした", "トリガー発動", "自動で入った", "自動売買結果",
    "今日のbot", "今週のbot", "月次bot", "bot成績",
    "my bot", "bot triggered", "signal fired", "algo fired",
    "bot pnl", "bot profit", "strategy triggered",
    "entry condition", "exit condition", "hit my target",
    "hit my stop",
]

# 【高優先】実績公開（+0.6/個 最大+3）
RESULT_KEYWORDS = [
    "万円", "今月の結果", "今週の結果", "今日の結果",
    "月次報告", "週次報告", "成績公開", "運用結果",
    "pnl", "p&l", "profit:", "total pnl",
    "win rate", "勝率", "sharpe",
    "確定益", "確定損", "含み益", "含み損",
    "利確", "損切り",
]

# 【中優先】エッジ・先行情報（+0.4/個 最大+2）
EDGE_KEYWORDS = [
    "alpha", "edge", "gem", "early", "100x", "10x",
    "smart money", "whale", "on-chain", "onchain",
    "narrative", "rotation", "next big",
    "エッジ", "仕込み", "先行", "大口", "クジラ",
    "オンチェーン", "ナラティブ", "ローテーション", "狙い目",
]

# ネガティブキーワード
NEGATIVE_KEYWORDS = [
    "guaranteed", "100% profit", "no risk", "free money",
    "絶対上がる", "確実に", "必ず上がる",
    "アフィリエイト", "紹介コード", "referral code",
    "giveaway", "フォローお願い", "rt希望", "rug", "scam",
]

CATEGORY_KEYWORDS = {
    "BTC":    ["bitcoin", "btc", "ビットコイン", "halving", "半減期", "sats"],
    "アルト":  ["altcoin", "アルトコイン", "solana", "sol", "ethereum", "eth",
               "イーサリアム", "gem", "100x", "銘柄", "アルト"],
    "DeFi":   ["defi", "yield", "stake", "ステーキング", "lending", "dex",
               "hyperliquid", "aave", "uniswap", "tvl"],
    "ボット":  ["bot", "ボット", "自動売買", "algo", "アルゴ", "backtest", "バックテスト"],
    "RWA":    ["rwa", "real world asset", "tokenize", "トークン化"],
    "DePIN":  ["depin", "helium", "render", "filecoin"],
    "AI":     ["ai agent", "aiエージェント", "bittensor", "virtuals", "autonomous"],
    "オンチェーン": ["onchain", "on-chain", "whale", "クジラ", "wallet", "ウォレット"],
}

def classify_category(text: str) -> str:
    t = text.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return "その他"

def score_tweet(tweet, watch_accounts: list) -> dict:
    text = tweet.text
    tl   = text.lower()
    score = 3.0  # ベース

    # 監視アカウントは+2
    is_watch = tweet.user.screen_name.lower() in [a.lower() for a in watch_accounts]
    if is_watch:
        score += 2.0

    # 【最高優先】実際の売買動作（+1.0/個 最大+5）
    action_hits = [kw for kw in ACTION_KEYWORDS if kw in tl]
    score += min(len(action_hits) * 1.0, 5.0)

    # 【高優先】ボット実況（+0.8/個 最大+4）
    bot_hits = [kw for kw in BOT_KEYWORDS if kw in tl]
    score += min(len(bot_hits) * 0.8, 4.0)

    # 【高優先】実績公開（+0.6/個 最大+3）
    result_hits = [kw for kw in RESULT_KEYWORDS if kw in tl]
    score += min(len(result_hits) * 0.6, 3.0)

    # 【中優先】エッジ語（+0.4/個 最大+2）
    edge_hits = [kw for kw in EDGE_KEYWORDS if kw in tl]
    score += min(len(edge_hits) * 0.4, 2.0)

    # エンゲージメント
    likes = tweet.favorite_count or 0
    rts   = tweet.retweet_count or 0
    flrs  = tweet.user.followers_count or 1

    if likes >= 500:   score += 1.5
    elif likes >= 100: score += 1.0
    elif likes >= 30:  score += 0.5
    elif likes >= 10:  score += 0.2

    if rts >= 100:    score += 1.0
    elif rts >= 30:   score += 0.5
    elif rts >= 10:   score += 0.2

    if flrs >= 100000: score += 1.0
    elif flrs >= 10000: score += 0.5
    elif flrs >= 1000:  score += 0.2

    # 具体的な数字（金額・パーセント・倍率）
    if re.search(r'\d+[%x倍]|\$\d+|[+\-]\d+万|[+\-]\d+%|\d+\s*btc', tl):
        score += 0.5

    # ネガティブ減点
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in tl)
    score -= neg * 1.5

    # 絵文字過多（スパム系）
    if len(re.findall(r'[🚀💎🔥🌙💰🤑]', text)) >= 5:
        score -= 1.5

    score = max(1.0, min(10.0, round(score, 1)))
    category = classify_category(text)

    # 検出キーワードまとめ
    top_hits = action_hits[:2] + bot_hits[:2] + result_hits[:2] + edge_hits[:1]
    summary = f"検出: {', '.join(top_hits)}" if top_hits else text[:80]

    return {
        "score": score,
        "category": category,
        "summary": summary,
        "action_hits": action_hits[:4],
        "bot_hits": bot_hits[:3],
        "result_hits": result_hits[:3],
        "edge_hits": edge_hits[:3],
        "reason": (
            f"売買動作{len(action_hits)}個・"
            f"ボット{len(bot_hits)}個・"
            f"実績{len(result_hits)}個・"
            f"エッジ{len(edge_hits)}個 / "
            f"いいね{likes} / RT{rts}"
        ),
    }

# ============================================================
# 既読管理
# ============================================================
def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)[-5000:]))

def tid(tweet) -> str:
    return hashlib.md5(str(tweet.id).encode()).hexdigest()

# ============================================================
# Telegram 送信（全文日本語）
# ============================================================
def send_telegram_text(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram送信エラー: {e}")

def send_telegram(tweet, score_data: dict, watch_accounts: list):
    cat_emoji = {
        "BTC": "₿", "アルト": "🪙", "DeFi": "🔄", "ボット": "🤖",
        "RWA": "🏦", "DePIN": "📡", "AI": "🧠",
        "オンチェーン": "🔍", "その他": "📌"
    }
    emoji  = cat_emoji.get(score_data["category"], "📌")
    score  = score_data["score"]
    stars  = "⭐" * min(int(score), 10)
    url    = f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}"
    source = "👁 監視アカウント" if tweet.user.screen_name.lower() in [a.lower() for a in watch_accounts] else "🔍 自動発掘"

    # 検出キーワードを種類別に表示
    action_label = "、".join(score_data.get("action_hits", [])[:2]) or "-"
    bot_label    = "、".join(score_data.get("bot_hits", [])[:2]) or "-"
    result_label = "、".join(score_data.get("result_hits", [])[:2]) or "-"
    edge_label   = "、".join(score_data.get("edge_hits", [])[:2]) or "-"

    # 何が引っかかったか一言で
    if score_data.get("action_hits"):
        trigger = "売買動作を検出"
    elif score_data.get("bot_hits"):
        trigger = "ボット実況を検出"
    elif score_data.get("result_hits"):
        trigger = "実績公開を検出"
    else:
        trigger = "エッジ情報を検出"

    body = (
        f"{emoji} {trigger} {emoji}\n"
        f"{source}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📊 スコア: {score}/10 {stars}\n"
        f"🏷 カテゴリ: {score_data['category']}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"🎯 検出ポイント:\n"
        f"  売買動作: {action_label}\n"
        f"  ボット実況: {bot_label}\n"
        f"  実績公開: {result_label}\n"
        f"  エッジ語: {edge_label}\n\n"
        f"📝 投稿内容（日本語訳）:\n{translate_to_ja(tweet.text[:800])}\n\n"
        f"🔤 原文:\n{tweet.text[:300]}{'...' if len(tweet.text) > 300 else ''}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 @{tweet.user.screen_name}\n"
        f"   フォロワー: {tweet.user.followers_count:,}人\n"
        f"   ❤️ {tweet.favorite_count}  🔁 {tweet.retweet_count}\n\n"
        f"🔗 投稿を見る: {url}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": body},
        timeout=10,
    )
    if resp.ok:
        log.info(f"送信済み: @{tweet.user.screen_name} スコア={score}")
    else:
        log.warning(f"送信失敗: {resp.text[:200]}")

# ============================================================
# メイン処理
# ============================================================
def run_once():
    log.info("=== Crypto Alpha Bot v3 起動 ===")

    twitter = TwikitClient("ja-JP")
    twitter.set_cookies({
        "auth_token": TWITTER_AUTH_TOKEN,
        "ct0": TWITTER_CT0,
        "twid": TWITTER_TWID
    })

    watch_accounts = load_accounts()
    seen     = load_seen()
    id_cache = load_id_cache()
    candidates = []

    # STEP A: 監視アカウントのツイート取得
    # ローテーション方式: 1runで最大20件チェック、runごとにシフトして全件を3runでカバー
    ACCOUNTS_PER_RUN = 10  # 控えめに10件ずつ（レートリミット対策）
    run_count_now = int(Path("run_count.txt").read_text()) if Path("run_count.txt").exists() else 0
    total = len(watch_accounts)
    start = (run_count_now * ACCOUNTS_PER_RUN) % total
    indices = [(start + i) % total for i in range(ACCOUNTS_PER_RUN)]
    this_run = [watch_accounts[i] for i in indices]
    log.info(f"監視アカウント: {len(watch_accounts)}件中 今回{len(this_run)}件チェック（{start+1}〜）")

    for username in this_run:
        try:
            user_id = get_user_id(twitter, username, id_cache)
            tweets  = list(twitter.get_user_tweets(user_id, tweet_type="Tweets", count=15))
            tweets  = [t for t in tweets if not t.text.startswith("RT @")]
            new_cnt = 0
            for t in tweets:
                h = tid(t)
                if h not in seen:
                    seen.add(h)
                    candidates.append(t)
                    new_cnt += 1
            if new_cnt:
                log.info(f"  @{username} → 新着{new_cnt}件")
        except Exception as e:
            log.warning(f"  @{username} スキップ: {e}")
        time.sleep(3.0)  # リクエスト間隔を3秒に（レートリミット対策）

    save_seen(seen)
    log.info(f"候補合計: {len(candidates)}件 → スコアリング中...")

    # STEP B: スコアリング
    scored = [(t, score_tweet(t, watch_accounts)) for t in candidates]
    scored = [(t, s) for t, s in scored if s["score"] >= ALPHA_SCORE_THRESHOLD]
    scored.sort(key=lambda x: x[1]["score"], reverse=True)

    # STEP C: Telegram送信
    sent = 0
    for tweet, score_data in scored[:MAX_TWEETS_PER_RUN]:
        send_telegram(tweet, score_data, watch_accounts)
        sent += 1
        time.sleep(1)

    if sent:
        log.info(f"Telegram送信: {sent}件")
    else:
        log.info("今回は検出なし")

    # STEP D: 自動アカウント発掘
    high_score_tweets = [t for t, s in scored if s["score"] >= 7.0]
    if high_score_tweets:
        log.info(f"自動発掘: {len(high_score_tweets)}件の高スコア投稿から探索中...")
        discover_accounts(twitter, high_score_tweets, watch_accounts)

    # STEP E: 定期サマリー（10回に1回）
    run_count_file = Path("run_count.txt")
    count = int(run_count_file.read_text()) if run_count_file.exists() else 0
    count += 1
    run_count_file.write_text(str(count))

    if count % 10 == 0:
        accounts = load_accounts()
        send_telegram_text(
            f"📊 定期レポート（{count}回目）\n\n"
            f"監視アカウント数: {len(accounts)}件\n"
            f"今回の新着投稿: {len(candidates)}件\n"
            f"エッジ検出・送信: {sent}件\n"
            f"次回実行: {MONITOR_INTERVAL // 60}分後"
        )

# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if not ACCOUNTS_FILE.exists():
        save_accounts(INITIAL_ACCOUNTS)
        log.info(f"初期アカウント{len(INITIAL_ACCOUNTS)}件を保存")

    if args.loop:
        while True:
            try:
                run_once()
            except Exception as e:
                log.error(f"エラー: {e}", exc_info=True)
            log.info(f"次回まで {MONITOR_INTERVAL}秒待機...")
            time.sleep(MONITOR_INTERVAL)
    else:
        run_once()
