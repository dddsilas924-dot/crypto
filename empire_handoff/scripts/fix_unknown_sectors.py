"""Unknown銘柄セクター修正 + 非クリプト除外 - 4段階処理（キャッシュ統合）"""
import asyncio
import sys
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.data.cache_manager import CacheManager
from config.sector_mapping import classify_sector, classify_chain

import aiohttp
from aiohttp.resolver import ThreadedResolver

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# ========================================
# 処理1: 非クリプト商品 → is_crypto=False
# ========================================
NON_CRYPTO_SYMBOLS = {
    # 為替
    "AUD", "BRL", "CAD", "CHF", "EUR", "GBP", "JPY", "TRY",
    # 株式指数
    "NAS100", "SPX500", "US30", "HK50",
    # コモディティ
    "USOIL", "UKOIL", "NGAS", "SILVER", "XPT",
    # 個別株（STOCKサフィックス無し版）
    "NVIDIA", "TESLA", "ROBINHOOD", "COINBASE",
}

# ========================================
# 処理2: 手動マッピング（CoinGecko ID既知）
# ========================================
MANUAL_COIN_IDS = {
    # 前回分（キャッシュ済みはスキップされる）
    "ADA": "cardano",
    "LTC": "litecoin",
    "JUP": "jupiter-exchange-solana",
    "CORE": "core-dao",
    "EDU": "open-campus",
    "BIO": "bio-protocol",
    "IOTX": "iotex",
    "ACH": "alchemy-pay",
    "BICO": "biconomy",
    "CVC": "civic",
    "MAV": "maverick-protocol",
    "ALT": "altlayer",
    "APEX": "apex-protocol",
    "ARPA": "arpa",
    "BB": "bouncebit",
    "GPS": "gps-protocol",
    "HYPER": "hyperlane",
    "ACT": "act-i-the-ai-prophecy",
    # 新規追加
    "BCH": "bitcoin-cash",
    "DOT": "polkadot",
    "XRP": "ripple",
    "XTZ": "tezos",
    "ZEC": "zcash",
    "NEAR": "near",
    "APE": "apecoin",
    "TONCOIN": "the-open-network",
    "RDNT": "radiant-capital",
    "SXP": "solar",
    "WOO": "woo-network",
    "SOLV": "solv-protocol",
    "AGLD": "adventure-gold",
    "BEAMX": "beam-2",
    "PENGU": "pudgy-penguins",
    "DOG": "dog-go-to-the-moon-runes",
    "SATS": "sats-ordinals",
    "SC": "siacoin",
    "FLUX1": "flux",
    "PUMPFUN": "pump-fun",
    "VELODROME": "velodrome-finance",
    "ONT": "ontology",
    "MOVE": "movement",
    "ERA": "era-swap",
    "EDEN": "eden",
    "RIF": "rif-token",
    "REQ": "request-network",
    "L3": "layer3",
    "LUNANEW": "terra-luna-2",
}

# ========================================
# 処理3: Meme推測分類（CoinGecko不要）
# ========================================
MEME_FORCE = {
    "TRUMPOFFICIAL", "JELLYJELLY", "BROCCOLIF3B", "VINE",
    "LONGXIA", "BIANRENSHENG", "DOG", "BIRB", "SPORTFUN",
}

GUESS_RULES = {
    # Meme系
    'PEPE': 'Meme', 'DOGE': 'Meme', 'SHIB': 'Meme', 'FLOKI': 'Meme',
    'BABYDOGE': 'Meme', 'RATS': 'Meme', 'CAT': 'Meme', 'NEIRO': 'Meme',
    'TURBO': 'Meme', 'BRETT': 'Meme', 'PEOPLE': 'Meme', 'BONK': 'Meme',
    'TRUMP': 'Meme', 'JELLY': 'Meme', 'VINE': 'Meme',
    # AI系
    'AI': 'AI', 'GPT': 'AI',
    # Gaming系
    'PIXEL': 'Gaming', 'PORTAL': 'Gaming',
    # DeFi系
    'SWAP': 'DeFi', 'LEND': 'DeFi',
}


async def fetch_coin_info(session: aiohttp.ClientSession, coin_id: str,
                          sector_cache: dict) -> dict:
    """CoinGecko APIからコイン情報取得（キャッシュ優先）"""
    if coin_id in sector_cache:
        return sector_cache[coin_id]

    try:
        url = f"{COINGECKO_BASE}/coins/{coin_id}"
        params = {"localization": "false", "tickers": "false",
                  "market_data": "false", "community_data": "false",
                  "developer_data": "false"}
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 429:
                return {"rate_limited": True}
            if resp.status == 200:
                data = await resp.json()
                categories = [c for c in data.get("categories", []) if c]
                platforms = data.get("platforms", {})
                result = {"categories": categories, "platforms": platforms,
                          "market_cap_rank": data.get("market_cap_rank")}
                sector_cache[coin_id] = result
                return result
    except Exception:
        pass
    return {}


async def main():
    start_time = datetime.now()
    db = HistoricalDB()
    cache = CacheManager()

    print("=" * 60)
    print("🔧 Unknown銘柄修正 + 非クリプト除外 (4段階処理)")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = db._get_conn()

    # is_cryptoカラム確認（HistoricalDB.__init__でマイグレーション済み）
    unknown_before = conn.execute(
        "SELECT COUNT(*) FROM sector WHERE primary_sector='Unknown'"
    ).fetchone()[0]
    total_before = conn.execute("SELECT COUNT(*) FROM sector").fetchone()[0]
    print(f"\n📊 修正前: Unknown {unknown_before}/{total_before}銘柄")

    # キャッシュ読込
    sector_cache = cache.file_get("coingecko_sectors") or {}
    cg_id_map = cache.file_get("coingecko_id_map") or {}
    print(f"📦 セクターキャッシュ: {len(sector_cache)}件")
    print(f"📦 IDマップキャッシュ: {len(cg_id_map)}件")

    stats = {'step1_non_crypto': 0, 'step2_manual': 0, 'step3_meme_guess': 0, 'step4_auto': 0}

    # ========================================
    # 処理1: 非クリプト商品 → is_crypto=False
    # ========================================
    print("\n" + "=" * 40)
    print("処理1: 非クリプト商品除外")
    print("=" * 40)

    all_symbols = [r[0] for r in conn.execute("SELECT symbol FROM sector").fetchall()]
    for symbol in all_symbols:
        base = symbol.split('/')[0]
        # STOCKサフィックス付きは既にCeFiだが、is_crypto=Falseに
        is_non_crypto = (
            base in NON_CRYPTO_SYMBOLS
            or base.endswith("STOCK")
        )
        if is_non_crypto:
            conn.execute(
                "UPDATE sector SET is_crypto=0, updated_at=? WHERE symbol=?",
                (datetime.now().isoformat(), symbol)
            )
            stats['step1_non_crypto'] += 1
            print(f"  🚫 {base} → is_crypto=False")

    conn.commit()
    print(f"  処理1完了: {stats['step1_non_crypto']}件除外")

    # ========================================
    # 処理2: 手動マッピング（CoinGecko API）
    # ========================================
    print("\n" + "=" * 40)
    print("処理2: 手動マッピング")
    print("=" * 40)

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        for base_sym, coin_id in MANUAL_COIN_IDS.items():
            symbol = f"{base_sym}/USDT:USDT"
            row = conn.execute(
                "SELECT primary_sector FROM sector WHERE symbol=?", (symbol,)
            ).fetchone()
            if not row:
                continue
            if row[0] != 'Unknown':
                continue

            info = await fetch_coin_info(session, coin_id, sector_cache)
            if info.get("rate_limited"):
                print(f"  [Rate Limited] 30秒待機...")
                await asyncio.sleep(30)
                info = await fetch_coin_info(session, coin_id, sector_cache)

            if info.get("categories"):
                cats = info["categories"]
                platforms = info.get("platforms", {})
                new_sector = classify_sector(cats)
                new_chain = classify_chain(cats, platforms)
                rank = info.get("market_cap_rank") or 9999
                cats_json = json.dumps(cats)

                conn.execute(
                    "UPDATE sector SET coingecko_id=?, categories=?, primary_sector=?, chain=?, market_cap_rank=?, updated_at=? WHERE symbol=?",
                    (coin_id, cats_json, new_sector, new_chain, rank, datetime.now().isoformat(), symbol)
                )
                stats['step2_manual'] += 1
                print(f"  ✅ {base_sym} → {new_sector} [{new_chain}] (rank:{rank})")
            else:
                print(f"  ⚠️ {base_sym}: categories空")

            if coin_id not in sector_cache:
                await asyncio.sleep(1.5)

    conn.commit()
    cache.file_set("coingecko_sectors", sector_cache)
    print(f"  処理2完了: {stats['step2_manual']}件更新")

    # ========================================
    # 処理3: Meme強制分類 + シンボル名推測
    # ========================================
    print("\n" + "=" * 40)
    print("処理3: Meme/推測分類")
    print("=" * 40)

    remaining_unknown = conn.execute(
        "SELECT symbol FROM sector WHERE primary_sector='Unknown' AND is_crypto=1"
    ).fetchall()

    for (symbol,) in remaining_unknown:
        base = symbol.split('/')[0]
        clean = re.sub(r'^\d+M?', '', base)

        matched_sector = None

        # Meme強制リスト
        if clean in MEME_FORCE:
            matched_sector = 'Meme'
        else:
            # 推測ルール
            for keyword, sector in GUESS_RULES.items():
                if keyword in clean:
                    matched_sector = sector
                    break

        if matched_sector:
            conn.execute(
                "UPDATE sector SET primary_sector=?, updated_at=? WHERE symbol=?",
                (matched_sector, datetime.now().isoformat(), symbol)
            )
            stats['step3_meme_guess'] += 1
            print(f"  ✅ {base} → {matched_sector}")

    conn.commit()
    print(f"  処理3完了: {stats['step3_meme_guess']}件更新")

    # ========================================
    # 処理4: 残りUnknown → CoinGecko自動マッチ
    # ========================================
    print("\n" + "=" * 40)
    print("処理4: CoinGecko自動マッチ")
    print("=" * 40)

    if not cg_id_map:
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(f"{COINGECKO_BASE}/coins/list",
                                       params={"include_platform": "true"},
                                       timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        coins = await resp.json()
                        for coin in coins:
                            sym = coin['symbol'].upper()
                            if sym not in cg_id_map:
                                cg_id_map[sym] = coin['id']
                        cache.file_set("coingecko_id_map", cg_id_map)
                        print(f"  CoinGecko全コイン: {len(cg_id_map)}件取得")
            except Exception as e:
                print(f"  ⚠️ コインリスト取得失敗: {e}")
    else:
        print(f"  CoinGecko IDマップ: キャッシュから{len(cg_id_map)}件")

    remaining = conn.execute(
        "SELECT symbol, coingecko_id FROM sector WHERE primary_sector='Unknown' AND is_crypto=1"
    ).fetchall()
    print(f"  残りUnknown: {len(remaining)}件")

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        for i, (symbol, old_cg_id) in enumerate(remaining):
            base = symbol.split('/')[0]
            coin_id = old_cg_id if old_cg_id else cg_id_map.get(base)
            if not coin_id:
                continue

            info = await fetch_coin_info(session, coin_id, sector_cache)
            if info.get("rate_limited"):
                print(f"  [Rate Limited] 30秒待機...")
                await asyncio.sleep(30)
                info = await fetch_coin_info(session, coin_id, sector_cache)
                if info.get("rate_limited"):
                    await asyncio.sleep(60)
                    info = await fetch_coin_info(session, coin_id, sector_cache)

            if info.get("categories"):
                cats = info["categories"]
                platforms = info.get("platforms", {})
                new_sector = classify_sector(cats)
                new_chain = classify_chain(cats, platforms)
                rank = info.get("market_cap_rank") or 9999
                cats_json = json.dumps(cats)

                if new_sector != "Unknown":
                    conn.execute(
                        "UPDATE sector SET coingecko_id=?, categories=?, primary_sector=?, chain=?, market_cap_rank=?, updated_at=? WHERE symbol=?",
                        (coin_id, cats_json, new_sector, new_chain, rank, datetime.now().isoformat(), symbol)
                    )
                    stats['step4_auto'] += 1
                    print(f"  ✅ {base} → {new_sector} [{new_chain}]")

            if (i + 1) % 20 == 0:
                conn.commit()
                cache.file_set("coingecko_sectors", sector_cache)
                print(f"  [{i+1}/{len(remaining)}] 自動マッチ: {stats['step4_auto']}件")

            if coin_id not in sector_cache:
                await asyncio.sleep(1.5)

    conn.commit()
    cache.file_set("coingecko_sectors", sector_cache)
    print(f"  処理4完了: {stats['step4_auto']}件更新")

    # ========================================
    # 最終集計
    # ========================================
    print("\n" + "=" * 40)
    print("最終集計")
    print("=" * 40)

    unknown_after = conn.execute(
        "SELECT COUNT(*) FROM sector WHERE primary_sector='Unknown' AND is_crypto=1"
    ).fetchone()[0]
    crypto_count = conn.execute(
        "SELECT COUNT(*) FROM sector WHERE is_crypto=1"
    ).fetchone()[0]
    non_crypto_count = conn.execute(
        "SELECT COUNT(*) FROM sector WHERE is_crypto=0"
    ).fetchone()[0]

    final_sectors = conn.execute(
        "SELECT primary_sector, COUNT(*) FROM sector WHERE is_crypto=1 GROUP BY primary_sector ORDER BY COUNT(*) DESC"
    ).fetchall()

    final_chains = conn.execute(
        "SELECT chain, COUNT(*) FROM sector WHERE chain != 'Other' AND is_crypto=1 GROUP BY chain ORDER BY COUNT(*) DESC"
    ).fetchall()

    still_unknown = conn.execute(
        "SELECT symbol FROM sector WHERE primary_sector='Unknown' AND is_crypto=1"
    ).fetchall()
    still_unknown_list = [r[0] for r in still_unknown]

    conn.close()

    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n✅ 完了! ({elapsed:.0f}秒)")
    print(f"\n📊 監視対象: {crypto_count}銘柄 (非クリプト除外: {non_crypto_count}件)")
    print(f"📊 Unknown(クリプトのみ): {unknown_before} → {unknown_after} (▼{unknown_before - unknown_after})")
    print(f"\n📊 最終セクター分布 (クリプトのみ):")
    for sector, count in final_sectors:
        print(f"  {sector}: {count}銘柄")

    print(f"\n🔗 チェーン分布:")
    for chain, count in final_chains[:10]:
        print(f"  {chain}: {count}銘柄")

    if still_unknown_list:
        print(f"\n❓ 残Unknown {len(still_unknown_list)}銘柄:")
        for s in still_unknown_list:
            print(f"  {s}")

    print(f"\n📈 処理統計:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
