"""セクター分類修正 - 5段階処理（キャッシュ統合）"""
import asyncio
import re
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.data.cache_manager import CacheManager
from config.sector_mapping import (
    classify_sector, classify_chain, COINGECKO_TO_MESSARI, CHAIN_KEYWORDS
)

# CoinGecko API
import aiohttp
from aiohttp.resolver import ThreadedResolver

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


async def fetch_coingecko_info(session: aiohttp.ClientSession, coin_id: str,
                               sector_cache: dict, cache: CacheManager) -> dict:
    """CoinGecko APIから情報取得（キャッシュ優先）"""
    # キャッシュチェック
    if coin_id in sector_cache:
        return sector_cache[coin_id]

    try:
        url = f"{COINGECKO_BASE}/coins/{coin_id}"
        params = {"localization": "false", "tickers": "false",
                  "market_data": "false", "community_data": "false",
                  "developer_data": "false"}
        async with session.get(url, params=params) as resp:
            if resp.status == 429:
                return {"rate_limited": True}
            if resp.status == 200:
                data = await resp.json()
                categories = [c for c in data.get("categories", []) if c]
                platforms = data.get("platforms", {})
                result = {"categories": categories, "platforms": platforms,
                          "market_cap_rank": data.get("market_cap_rank")}
                # キャッシュ保存
                sector_cache[coin_id] = result
                cache.file_set("coingecko_sectors", sector_cache)
                return result
    except Exception:
        pass
    return {}


async def main():
    start_time = datetime.now()
    db = HistoricalDB()
    cache = CacheManager()

    print("=" * 60)
    print("🔧 セクター分類修正 (5段階処理)")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = db._get_conn()

    # 現状確認
    all_sectors = conn.execute(
        "SELECT symbol, primary_sector, chain, categories, coingecko_id, subsector FROM sector"
    ).fetchall()
    print(f"\n📊 修正前: {len(all_sectors)}件")

    sector_counts_before = {}
    for row in all_sectors:
        s = row[1]
        sector_counts_before[s] = sector_counts_before.get(s, 0) + 1
    for s, c in sorted(sector_counts_before.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    stats = {
        'step1_scale': 0,
        'step2_stock': 0,
        'step3_remap': 0,
        'step4_rejudge': 0,
    }

    # セクターキャッシュ読み込み
    sector_cache = cache.file_get("coingecko_sectors") or {}
    print(f"\n📦 セクターキャッシュ: {len(sector_cache)}件")

    # CoinGecko IDマップキャッシュ
    cg_id_map = cache.file_get("coingecko_id_map") or {}
    print(f"📦 IDマップキャッシュ: {len(cg_id_map)}件")

    # ========================================
    # 処理1: Scale token正規化
    # ========================================
    print("\n" + "=" * 40)
    print("処理1: Scale token正規化")
    print("=" * 40)

    scale_pattern = re.compile(r'^(\d+M?)([A-Z]+)')
    scale_symbols = conn.execute(
        "SELECT symbol, coingecko_id, categories, primary_sector FROM sector WHERE symbol LIKE '%/%'"
    ).fetchall()

    scale_targets = []
    for row in scale_symbols:
        symbol = row[0]
        base = symbol.split('/')[0]
        m = scale_pattern.match(base)
        if m:
            prefix = m.group(1)
            real_name = m.group(2)
            scale_targets.append((symbol, real_name, row[1], row[2], row[3]))

    print(f"  スケールトークン検出: {len(scale_targets)}件")

    if scale_targets:
        # CoinGecko IDマップ取得（キャッシュ優先）
        if not cg_id_map:
            connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
            async with aiohttp.ClientSession(connector=connector) as session:
                try:
                    async with session.get(f"{COINGECKO_BASE}/coins/list") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for coin in data:
                                cg_id_map[coin['symbol'].upper()] = coin['id']
                            cache.file_set("coingecko_id_map", cg_id_map)
                            print(f"  CoinGeckoコインリスト: {len(cg_id_map)}件")
                except Exception as e:
                    print(f"  ⚠️ コインリスト取得失敗: {e}")
        else:
            print(f"  CoinGecko IDマップ: キャッシュから{len(cg_id_map)}件")

        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            for symbol, real_name, old_cg_id, old_cats, old_sector in scale_targets:
                cg_id = cg_id_map.get(real_name)
                if cg_id and cg_id != old_cg_id:
                    info = await fetch_coingecko_info(session, cg_id, sector_cache, cache)
                    if info.get("rate_limited"):
                        print("  [Rate Limited] 30秒待機...")
                        await asyncio.sleep(30)
                        info = await fetch_coingecko_info(session, cg_id, sector_cache, cache)

                    if info.get("categories"):
                        cats = info["categories"]
                        platforms = info.get("platforms", {})
                        new_sector = classify_sector(cats)
                        new_chain = classify_chain(cats, platforms)
                        cats_json = json.dumps(cats)

                        conn.execute(
                            "UPDATE sector SET coingecko_id=?, categories=?, primary_sector=?, chain=?, updated_at=? WHERE symbol=?",
                            (cg_id, cats_json, new_sector, new_chain, datetime.now().isoformat(), symbol)
                        )
                        stats['step1_scale'] += 1
                        print(f"  ✅ {symbol}: {real_name} → {new_sector} [{new_chain}]")
                    if cg_id not in sector_cache:
                        await asyncio.sleep(1.5)

    conn.commit()
    print(f"  処理1完了: {stats['step1_scale']}件更新")

    # ========================================
    # 処理2: STOCKトークン → CeFi
    # ========================================
    print("\n" + "=" * 40)
    print("処理2: STOCKトークン → CeFi")
    print("=" * 40)

    stock_symbols = conn.execute(
        "SELECT symbol FROM sector WHERE symbol LIKE '%STOCK%'"
    ).fetchall()

    for row in stock_symbols:
        symbol = row[0]
        conn.execute(
            "UPDATE sector SET primary_sector='CeFi', subsector='Tokenized Stock', updated_at=? WHERE symbol=?",
            (datetime.now().isoformat(), symbol)
        )
        stats['step2_stock'] += 1
        print(f"  ✅ {symbol} → CeFi (Tokenized Stock)")

    conn.commit()
    print(f"  処理2完了: {stats['step2_stock']}件更新")

    # ========================================
    # 処理3: セクター名リマッピング
    # ========================================
    print("\n" + "=" * 40)
    print("処理3: セクター名リマッピング")
    print("=" * 40)

    CHAIN_SECTORS = ['BNB', 'Solana', 'Ethereum']
    SECTOR_REMAP = {
        'L1': 'Networks',
        'L2': 'Networks',
        'GameFi': 'Gaming',
        'RWA': 'DeFi',
        'NFT': 'NFTs',
    }

    # 3a: chain系セクター → chainに移動 + categoriesから再判定
    for chain_sector in CHAIN_SECTORS:
        rows = conn.execute(
            "SELECT symbol, categories, chain FROM sector WHERE primary_sector=?",
            (chain_sector,)
        ).fetchall()
        print(f"\n  [{chain_sector}セクター] {len(rows)}件 → chain={chain_sector}に移動")

        for symbol, cats_json, old_chain in rows:
            new_chain = chain_sector
            new_sector = "Unknown"
            if cats_json:
                try:
                    cats = json.loads(cats_json)
                    new_sector = classify_sector(cats)
                    if new_sector in CHAIN_SECTORS:
                        new_sector = "Unknown"
                except (json.JSONDecodeError, TypeError):
                    pass

            conn.execute(
                "UPDATE sector SET primary_sector=?, chain=?, updated_at=? WHERE symbol=?",
                (new_sector, new_chain, datetime.now().isoformat(), symbol)
            )
            stats['step3_remap'] += 1

    # 3b: セクター名変換
    for old_name, new_name in SECTOR_REMAP.items():
        rows = conn.execute(
            "SELECT symbol FROM sector WHERE primary_sector=?", (old_name,)
        ).fetchall()
        if rows:
            print(f"\n  [{old_name}→{new_name}] {len(rows)}件")
            conn.execute(
                "UPDATE sector SET primary_sector=?, updated_at=? WHERE primary_sector=?",
                (new_name, datetime.now().isoformat(), old_name)
            )
            stats['step3_remap'] += len(rows)

    # 3c: "Other" セクターを再判定
    other_rows = conn.execute(
        "SELECT symbol, categories FROM sector WHERE primary_sector='Other'"
    ).fetchall()
    print(f"\n  [Other再判定] {len(other_rows)}件")
    other_reclassified = 0
    for symbol, cats_json in other_rows:
        if cats_json:
            try:
                cats = json.loads(cats_json)
                new_sector = classify_sector(cats)
                if new_sector != "Unknown":
                    conn.execute(
                        "UPDATE sector SET primary_sector=?, updated_at=? WHERE symbol=?",
                        (new_sector, datetime.now().isoformat(), symbol)
                    )
                    other_reclassified += 1
                    stats['step3_remap'] += 1
            except (json.JSONDecodeError, TypeError):
                pass
    print(f"  Other再判定成功: {other_reclassified}件")

    conn.commit()
    print(f"  処理3完了: {stats['step3_remap']}件更新")

    # ========================================
    # 処理4: Unknown再判定（CoinGecko API）
    # ========================================
    print("\n" + "=" * 40)
    print("処理4: Unknown再判定")
    print("=" * 40)

    unknown_rows = conn.execute(
        "SELECT symbol, coingecko_id, categories FROM sector WHERE primary_sector='Unknown'"
    ).fetchall()
    print(f"  Unknown: {len(unknown_rows)}件")

    # 4a: 既存categories から再判定
    reclaimed_from_cats = 0
    for symbol, cg_id, cats_json in unknown_rows:
        if cats_json:
            try:
                cats = json.loads(cats_json)
                if cats:
                    new_sector = classify_sector(cats)
                    if new_sector != "Unknown":
                        new_chain = classify_chain(cats)
                        conn.execute(
                            "UPDATE sector SET primary_sector=?, chain=?, updated_at=? WHERE symbol=?",
                            (new_sector, new_chain, datetime.now().isoformat(), symbol)
                        )
                        reclaimed_from_cats += 1
                        stats['step4_rejudge'] += 1
            except (json.JSONDecodeError, TypeError):
                pass
    conn.commit()
    print(f"  既存categories再判定: {reclaimed_from_cats}件")

    # 4b: coingecko_idがあるのにcategoriesが空 → API再取得（キャッシュ優先）
    still_unknown = conn.execute(
        "SELECT symbol, coingecko_id FROM sector WHERE primary_sector='Unknown' AND coingecko_id IS NOT NULL AND coingecko_id != ''"
    ).fetchall()
    print(f"  CoinGecko ID有りUnknown: {len(still_unknown)}件 → API/キャッシュ再取得")

    if still_unknown:
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            api_success = 0
            for i, (symbol, cg_id) in enumerate(still_unknown):
                info = await fetch_coingecko_info(session, cg_id, sector_cache, cache)
                if info.get("rate_limited"):
                    print(f"  [Rate Limited] 30秒待機...")
                    await asyncio.sleep(30)
                    info = await fetch_coingecko_info(session, cg_id, sector_cache, cache)
                    if info.get("rate_limited"):
                        print(f"  [Rate Limited] 60秒待機...")
                        await asyncio.sleep(60)
                        info = await fetch_coingecko_info(session, cg_id, sector_cache, cache)

                if info.get("categories"):
                    cats = info["categories"]
                    platforms = info.get("platforms", {})
                    new_sector = classify_sector(cats)
                    new_chain = classify_chain(cats, platforms)
                    cats_json = json.dumps(cats)
                    conn.execute(
                        "UPDATE sector SET categories=?, primary_sector=?, chain=?, updated_at=? WHERE symbol=?",
                        (cats_json, new_sector, new_chain, datetime.now().isoformat(), symbol)
                    )
                    if new_sector != "Unknown":
                        api_success += 1
                        stats['step4_rejudge'] += 1

                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(still_unknown)}] 再取得成功: {api_success}")
                    conn.commit()

                # キャッシュヒットならスリープ不要
                if cg_id not in sector_cache:
                    await asyncio.sleep(1.5)

            conn.commit()
            print(f"  API再取得成功: {api_success}件")

    print(f"  処理4完了: {stats['step4_rejudge']}件更新")

    # ========================================
    # 処理5: 最終集計 + Telegram送信
    # ========================================
    print("\n" + "=" * 40)
    print("処理5: 最終集計")
    print("=" * 40)

    final_unknown = conn.execute(
        "SELECT symbol FROM sector WHERE primary_sector='Unknown'"
    ).fetchall()
    final_unknown_symbols = [r[0] for r in final_unknown]

    final_sectors = conn.execute(
        "SELECT primary_sector, COUNT(*) FROM sector GROUP BY primary_sector ORDER BY COUNT(*) DESC"
    ).fetchall()

    final_chains = conn.execute(
        "SELECT chain, COUNT(*) FROM sector WHERE chain != 'Other' GROUP BY chain ORDER BY COUNT(*) DESC"
    ).fetchall()

    conn.close()

    elapsed = (datetime.now() - start_time).total_seconds()
    cache_stats = cache.stats()

    print(f"\n✅ 完了! ({elapsed:.0f}秒)")
    print(f"\n📊 最終セクター分布:")
    for sector, count in final_sectors:
        print(f"  {sector}: {count}銘柄")

    print(f"\n🔗 チェーン分布:")
    for chain, count in final_chains[:10]:
        print(f"  {chain}: {count}銘柄")

    print(f"\n❓ Unknown残: {len(final_unknown_symbols)}銘柄")
    if final_unknown_symbols:
        for s in final_unknown_symbols[:20]:
            print(f"  {s}")
        if len(final_unknown_symbols) > 20:
            print(f"  ...他{len(final_unknown_symbols)-20}件")

    print(f"\n📈 処理統計:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\n📦 キャッシュ: hits={cache_stats['hits']}, misses={cache_stats['misses']}, rate={cache_stats['hit_rate_pct']}%")

    # Telegram送信
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()

        sector_lines = '\n'.join([f"  {s}: {c}銘柄" for s, c in final_sectors])
        chain_lines = '\n'.join([f"  {ch}: {c}銘柄" for ch, c in final_chains[:10]])
        unknown_list = ', '.join([s.split('/')[0] for s in final_unknown_symbols[:30]])

        text = (
            f"🔧 <b>セクター分類修正完了</b>\n\n"
            f"■ 処理結果\n"
            f"  Scale正規化: {stats['step1_scale']}\n"
            f"  STOCK→CeFi: {stats['step2_stock']}\n"
            f"  セクターremap: {stats['step3_remap']}\n"
            f"  Unknown再判定: {stats['step4_rejudge']}\n"
            f"  処理時間: {elapsed:.0f}秒\n\n"
            f"■ 最終セクター分布\n{sector_lines}\n\n"
            f"■ チェーン分布\n{chain_lines}\n\n"
            f"■ Unknown残: {len(final_unknown_symbols)}銘柄\n"
            f"  {unknown_list}\n\n"
            f"■ キャッシュ効率\n"
            f"  hits: {cache_stats['hits']}, misses: {cache_stats['misses']}, rate: {cache_stats['hit_rate_pct']}%\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        await alert.send_message(text)
        print("\n📱 Telegram送信完了")
    except Exception as e:
        print(f"\n⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
