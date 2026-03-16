"""主要銘柄の1h足データを1年分取得 (MEXC先物)

使い方:
  python scripts/fetch_hourly_data.py
"""
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import ccxt
import pandas as pd
from src.data.database import HistoricalDB


def get_top_symbols(db: HistoricalDB, limit: int = 100) -> list:
    """出来高上位の銘柄を取得"""
    conn = db._get_conn()
    # 直近1ヶ月の出来高上位
    rows = conn.execute("""
        SELECT symbol, SUM(volume * close) as vol_usd
        FROM ohlcv WHERE timeframe='1d'
        AND timestamp >= ? GROUP BY symbol
        ORDER BY vol_usd DESC LIMIT ?
    """, (int(datetime(2026, 2, 1).timestamp() * 1000), limit)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def fetch_hourly(exchange, db: HistoricalDB, symbol: str,
                 target_start_ms: int, existing_oldest_ms: int = None) -> int:
    """1銘柄の1h足を取得"""
    added = 0
    since = target_start_ms

    for page in range(15):  # 15ページ = 15000本 ≈ 625日
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', since=since, limit=1000)
        except Exception as e:
            if 'not exist' in str(e).lower() or '30004' in str(e):
                break
            raise

        if not ohlcv:
            break

        # 既存データより古いものだけ (既存データがある場合)
        if existing_oldest_ms:
            ohlcv = [c for c in ohlcv if c[0] < existing_oldest_ms]

        if not ohlcv:
            break

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='first')]

        saved = db.upsert_ohlcv(symbol, '1h', df)
        added += saved

        # 次のページ
        last_ts = int(ohlcv[-1][0]) if ohlcv else since
        since = last_ts + 3600000  # 1時間後

        if since >= (existing_oldest_ms or float('inf')):
            break

        time.sleep(0.3)

    return added


def main():
    db = HistoricalDB()
    conn = db._get_conn()

    # 現在の1h最古タイムスタンプ確認
    r = conn.execute("SELECT MIN(timestamp) FROM ohlcv WHERE timeframe='1h'").fetchone()
    existing_oldest = r[0] if r[0] else None

    # 1h足のある銘柄数
    h_count = conn.execute("SELECT COUNT(DISTINCT symbol) FROM ohlcv WHERE timeframe='1h'").fetchone()[0]
    conn.close()

    print("=" * 70, flush=True)
    print("  1h足データ取得 (MEXC先物)", flush=True)
    print(f"  既存1h: {h_count}銘柄, 最古: {datetime.fromtimestamp(existing_oldest/1000) if existing_oldest else 'なし'}", flush=True)
    print("=" * 70, flush=True)

    # 上位100銘柄
    symbols = get_top_symbols(db, 100)
    print(f"  対象: 出来高上位{len(symbols)}銘柄", flush=True)

    # 目標: 2025-01-01 から取得 (約14ヶ月分)
    target_start = int(datetime(2025, 1, 1).timestamp() * 1000)

    exchange = ccxt.mexc({'options': {'defaultType': 'swap'}})
    total_added = 0
    extended = 0
    errors = []

    for i, sym in enumerate(symbols):
        try:
            # この銘柄の1h最古を確認
            conn = db._get_conn()
            r = conn.execute(
                "SELECT MIN(timestamp) FROM ohlcv WHERE symbol=? AND timeframe='1h'", (sym,)
            ).fetchone()
            sym_oldest = r[0] if r[0] else None
            conn.close()

            # 既に十分古ければスキップ
            if sym_oldest and sym_oldest <= target_start:
                continue

            added = fetch_hourly(exchange, db, sym, target_start, sym_oldest)
            if added > 0:
                total_added += added
                extended += 1

            if (i + 1) % 10 == 0 or (i + 1) == len(symbols):
                print(f"  [{i+1}/{len(symbols)}] 拡張: {extended}銘柄, +{total_added:,}レコード", flush=True)

        except Exception as e:
            errors.append(f"{sym}: {str(e)[:60]}")
            time.sleep(1)

        time.sleep(0.2)

    print(f"\n{'='*70}", flush=True)
    print(f"  1h足データ取得完了!", flush=True)
    print(f"  拡張銘柄: {extended}", flush=True)
    print(f"  追加レコード: {total_added:,}", flush=True)
    print(f"  エラー: {len(errors)}", flush=True)

    # 取得後の確認
    conn = db._get_conn()
    for tf in ['1h', '1d']:
        r = conn.execute(f"SELECT COUNT(DISTINCT symbol), MIN(timestamp), MAX(timestamp), COUNT(*) FROM ohlcv WHERE timeframe='{tf}'").fetchone()
        if r[1]:
            print(f"  {tf}: {r[0]}銘柄, {datetime.fromtimestamp(r[1]/1000).date()} ~ {datetime.fromtimestamp(r[2]/1000).date()}, {r[3]:,}レコード", flush=True)
    conn.close()

    if errors[:5]:
        print(f"  エラー例:", flush=True)
        for e in errors[:5]:
            print(f"    {e}", flush=True)


if __name__ == '__main__':
    main()
