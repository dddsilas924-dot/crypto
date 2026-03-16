"""CoinGecko API → Messari 11セクター分類 + チェーンタグ（キャッシュ統合）"""
import asyncio
import aiohttp
import aiohttp.resolver
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.data.cache_manager import CacheManager
from config.sector_mapping import classify_sector, classify_chain

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def _create_session():
    connector = aiohttp.TCPConnector(resolver=aiohttp.resolver.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector)


async def fetch_coingecko_list(session) -> dict:
    """CoinGecko全コインリスト→シンボル→IDマッピング"""
    url = f"{COINGECKO_BASE}/coins/list"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                coins = await resp.json()
                mapping = {}
                for coin in coins:
                    sym = coin['symbol'].upper()
                    if sym not in mapping:
                        mapping[sym] = coin['id']
                return mapping
    except Exception as e:
        print(f"[CoinGecko Error] list: {e}")
    return {}


async def fetch_coin_detail(session, coin_id: str) -> dict:
    """CoinGecko コイン詳細取得（categories + platforms）"""
    url = f"{COINGECKO_BASE}/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false"
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    wait = 30 * (attempt + 1)
                    print(f"  [Rate Limited] {wait}秒待機...")
                    await asyncio.sleep(wait)
                    continue
        except Exception:
            pass
    return {}


async def send_telegram_summary(sector_df, chain_df, unknown_count: int, total_count: int, elapsed_min: float):
    """完了時にTelegramへサマリー送信"""
    import html as html_mod
    from src.execution.alert import TelegramAlert
    alert = TelegramAlert()

    sector_lines = '\n'.join([
        f"  {html_mod.escape(str(row['primary_sector']))}: {row['count']}銘柄"
        for _, row in sector_df.iterrows()
    ])
    chain_lines = '\n'.join([
        f"  {html_mod.escape(str(row['chain']))}: {row['count']}銘柄"
        for _, row in chain_df.iterrows()
    ]) or '  なし'

    text = (
        f"🏷️ <b>セクター分類完了</b>\n\n"
        f"■ Messari 11セクター別\n{sector_lines}\n\n"
        f"■ チェーン別 Top10\n{chain_lines}\n\n"
        f"■ Unknown残: {unknown_count}/{total_count}銘柄\n"
        f"■ 処理時間: {elapsed_min:.1f}分\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await alert.send_message(text)


async def main():
    start_time = datetime.now()
    db = HistoricalDB()
    cache = CacheManager()

    # sector テーブルにchain, subsectorカラムを追加（既存DBマイグレーション）
    conn = db._get_conn()
    try:
        conn.execute("ALTER TABLE sector ADD COLUMN chain TEXT DEFAULT 'Other'")
        print("[Migration] chain カラム追加")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sector ADD COLUMN subsector TEXT DEFAULT ''")
        print("[Migration] subsector カラム追加")
    except Exception:
        pass
    conn.close()

    print("=" * 60)
    print("🏷️ Messari 11セクター分類")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # MEXC先物シンボル取得（キャッシュ対応）
    from src.fetchers.ohlcv import MEXCFetcher
    fetcher = MEXCFetcher(cache=cache)
    symbols = await fetcher.fetch_futures_symbols()
    await fetcher.close()
    print(f"📈 MEXC先物銘柄数: {len(symbols)}")

    # 既存分類をチェック
    conn = db._get_conn()
    existing = {r[0] for r in conn.execute("SELECT symbol FROM sector WHERE primary_sector != 'Unknown'").fetchall()}
    conn.close()
    print(f"📊 既存分類済み: {len(existing)}銘柄")

    async with _create_session() as session:
        # CoinGecko IDマッピング（キャッシュ: 30日有効）
        cg_mapping = cache.file_get("coingecko_id_map")
        if cg_mapping:
            print(f"🔍 CoinGecko IDマップ: キャッシュから{len(cg_mapping)}件読み込み")
        else:
            print("🔍 CoinGeckoコインリスト取得中...")
            cg_mapping = await fetch_coingecko_list(session)
            print(f"  → {len(cg_mapping)}コインのマッピング取得")
            if cg_mapping:
                cache.file_set("coingecko_id_map", cg_mapping)

        classified = 0
        skipped = 0
        not_found = []

        # セクター詳細キャッシュ（ループ外で1回読込）
        sector_cache = cache.file_get("coingecko_sectors") or {}
        print(f"📦 セクター詳細キャッシュ: {len(sector_cache)}件")

        for i, symbol in enumerate(symbols):
            base = symbol.split('/')[0]

            # 既存分類済みはスキップ（強制再分類しない）
            if symbol in existing:
                skipped += 1
                continue

            coin_id = cg_mapping.get(base)
            if not coin_id:
                not_found.append(base)
                db.set_sector(symbol, '', '[]', 'Unknown', 0, 'Other', '')
                continue

            if coin_id in sector_cache:
                detail = sector_cache[coin_id]
            else:
                detail = await fetch_coin_detail(session, coin_id)
                if detail:
                    sector_cache[coin_id] = {
                        'categories': detail.get('categories', []) or [],
                        'platforms': detail.get('platforms', {}) or {},
                        'market_cap_rank': detail.get('market_cap_rank'),
                    }
                # CoinGecko無料API: 10-30 req/min
                await asyncio.sleep(2.5)

            if detail:
                categories = detail.get('categories', []) or []
                platforms = detail.get('platforms', {}) or {}
                rank = detail.get('market_cap_rank') or 9999

                primary = classify_sector(categories)
                chain = classify_chain(categories, platforms)

                # subsector: 最も具体的なカテゴリを使用
                subsector = categories[0] if categories else ''

                db.set_sector(symbol, coin_id, json.dumps(categories), primary, rank, chain, subsector)
                classified += 1

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(symbols)}] 新規分類: {classified}, スキップ: {skipped}")
                cache.file_set("coingecko_sectors", sector_cache)

        # 最終キャッシュ保存
        cache.file_set("coingecko_sectors", sector_cache)

    print(f"\n✅ 完了!")
    print(f"  新規分類: {classified}")
    print(f"  既存スキップ: {skipped}")
    print(f"  CoinGecko未発見: {len(not_found)}")

    # セクター分布表示
    conn = db._get_conn()
    import pandas as pd
    df = pd.read_sql_query("SELECT primary_sector, COUNT(*) as count FROM sector GROUP BY primary_sector ORDER BY count DESC", conn)
    conn.close()
    print("\n📊 Messariセクター分布:")
    for _, row in df.iterrows():
        print(f"  {row['primary_sector']}: {row['count']}銘柄")

    # チェーン分布
    conn = db._get_conn()
    df2 = pd.read_sql_query("SELECT chain, COUNT(*) as count FROM sector WHERE chain != 'Other' GROUP BY chain ORDER BY count DESC LIMIT 10", conn)
    conn.close()
    if len(df2) > 0:
        print("\n🔗 チェーン分布 Top10:")
        for _, row in df2.iterrows():
            print(f"  {row['chain']}: {row['count']}銘柄")

    # Unknown数
    unknown_count = int(df[df['primary_sector'] == 'Unknown']['count'].sum()) if 'Unknown' in df['primary_sector'].values else 0
    total_count = int(df['count'].sum())

    # Telegram送信
    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    try:
        await send_telegram_summary(df, df2, unknown_count, total_count, elapsed_min)
        print("\n📱 Telegramサマリー送信完了")
    except Exception as e:
        print(f"\n⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
