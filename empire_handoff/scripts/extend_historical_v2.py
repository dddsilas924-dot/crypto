"""ヒストリカルデータ拡張 v2 - マルチソース対応 (同期版)

取得優先順:
  1. MEXC先物 (主データソース、先物価格一致)
  2. Binance現物 (補完用、最も古い)
  3. Bybit先物 (追加補完)

使い方:
  python scripts/extend_historical_v2.py
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

# 目標: 2020-01-01まで遡る
TARGET_OLDEST_MS = int(datetime(2020, 1, 1).timestamp() * 1000)
MAX_PAGES = 5


def get_symbols_needing_extension(db: HistoricalDB) -> list:
    """拡張が必要な銘柄一覧"""
    conn = db._get_conn()
    rows = conn.execute(
        "SELECT symbol, MIN(timestamp) as oldest, MAX(timestamp) as newest, COUNT(*) as cnt "
        "FROM ohlcv WHERE timeframe='1d' GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    conn.close()

    need = [(sym, oldest, newest, cnt) for sym, oldest, newest, cnt in rows if oldest > TARGET_OLDEST_MS]
    ok = len(rows) - len(need)
    return rows, need, ok


def fetch_pages(exchange, symbol: str, target_since: int, current_oldest: int,
                max_pages: int = MAX_PAGES, sleep_sec: float = 0.5) -> list:
    """ページネーションで古いデータを取得"""
    all_ohlcv = []
    since = target_since

    for page in range(max_pages):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '1d', since=since, limit=1000)
        except Exception:
            break

        if not ohlcv:
            break

        old_data = [c for c in ohlcv if c[0] < current_oldest]
        all_ohlcv.extend(old_data)

        last_ts = ohlcv[-1][0]
        if last_ts >= current_oldest:
            break
        since = last_ts + 86400000
        time.sleep(sleep_sec)

    return all_ohlcv


def save_ohlcv(db: HistoricalDB, symbol: str, ohlcv_list: list) -> int:
    """OHLCVリストをDBに保存"""
    if not ohlcv_list:
        return 0
    df = pd.DataFrame(ohlcv_list, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')]
    return db.upsert_ohlcv(symbol, '1d', df)


def mexc_to_binance(sym: str) -> str:
    return sym.replace(':USDT', '')


def run_phase(exchange, symbols, db, phase_name, symbol_transform=None, sleep_sec=0.5):
    """1フェーズ実行"""
    added = 0
    extended = 0
    errors = []
    remaining = []

    for i, (sym, oldest, newest, cnt) in enumerate(symbols):
        fetch_sym = symbol_transform(sym) if symbol_transform else sym
        try:
            ohlcv = fetch_pages(exchange, fetch_sym, TARGET_OLDEST_MS, oldest, sleep_sec=sleep_sec)
            if ohlcv:
                saved = save_ohlcv(db, sym, ohlcv)  # DBにはMEXCシンボル名で保存
                added += saved
                extended += 1
                new_oldest = min(c[0] for c in ohlcv)
                if new_oldest > TARGET_OLDEST_MS + 86400000 * 30:
                    remaining.append((sym, new_oldest, newest, cnt + saved))
            else:
                remaining.append((sym, oldest, newest, cnt))
        except Exception as e:
            err = str(e)[:80]
            skip_msgs = ['not exist', '30004', 'not found', 'invalid symbol', 'does not have']
            if not any(m in err.lower() for m in skip_msgs):
                errors.append(f"{sym}: {err}")
            remaining.append((sym, oldest, newest, cnt))

        if (i + 1) % 50 == 0 or (i + 1) == len(symbols):
            print(f"  [{i+1}/{len(symbols)}] {phase_name}: {extended}銘柄拡張, +{added:,}レコード", flush=True)

        time.sleep(0.1)

    return added, extended, errors, remaining


def main():
    db = HistoricalDB()
    all_symbols, need_extend, already_ok = get_symbols_needing_extension(db)

    print("=" * 70, flush=True)
    print("  ヒストリカルデータ拡張 v2 (マルチソース・同期版)", flush=True)
    print(f"  対象銘柄: {len(all_symbols)} (拡張必要: {len(need_extend)}, 済: {already_ok})", flush=True)
    print(f"  目標最古日: {datetime.utcfromtimestamp(TARGET_OLDEST_MS/1000).date()}", flush=True)
    print("=" * 70, flush=True)
    start_time = time.time()

    # === Phase 1: MEXC先物 ===
    print(f"\n--- Phase 1: MEXC先物 ({len(need_extend)}銘柄) ---", flush=True)
    mexc = ccxt.mexc({'options': {'defaultType': 'swap'}})
    mexc_added, mexc_ext, mexc_err, remaining = run_phase(
        mexc, need_extend, db, "MEXC", sleep_sec=0.3)
    print(f"  MEXC完了: +{mexc_added:,}レコード ({mexc_ext}銘柄), エラー{len(mexc_err)}", flush=True)

    # === Phase 2: Binance現物 ===
    print(f"\n--- Phase 2: Binance現物 ({len(remaining)}銘柄) ---", flush=True)
    binance = ccxt.binance()
    binance_added, binance_ext, binance_err, still_remaining = run_phase(
        binance, remaining, db, "Binance", symbol_transform=mexc_to_binance, sleep_sec=0.5)
    print(f"  Binance完了: +{binance_added:,}レコード ({binance_ext}銘柄), エラー{len(binance_err)}", flush=True)

    # === Phase 3: Bybit先物 ===
    print(f"\n--- Phase 3: Bybit先物 ({len(still_remaining)}銘柄) ---", flush=True)
    bybit = ccxt.bybit()
    bybit_added, bybit_ext, bybit_err, final_remaining = run_phase(
        bybit, still_remaining, db, "Bybit", sleep_sec=0.5)
    print(f"  Bybit完了: +{bybit_added:,}レコード ({bybit_ext}銘柄), エラー{len(bybit_err)}", flush=True)

    # === 結果サマリ ===
    total_added = mexc_added + binance_added + bybit_added
    elapsed = time.time() - start_time

    print(f"\n{'='*70}", flush=True)
    print(f"  データ拡張完了! ({elapsed:.0f}秒)", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"  MEXC先物:    +{mexc_added:>7,} レコード ({mexc_ext}銘柄)", flush=True)
    print(f"  Binance現物: +{binance_added:>7,} レコード ({binance_ext}銘柄)", flush=True)
    print(f"  Bybit先物:   +{bybit_added:>7,} レコード ({bybit_ext}銘柄)", flush=True)
    print(f"  合計:        +{total_added:>7,} レコード", flush=True)

    # 拡張後カバレッジ
    print(f"\n  --- 拡張後のデータカバレッジ ---", flush=True)
    conn = db._get_conn()
    for year in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
        start_ts = int(datetime(year, 1, 1).timestamp() * 1000)
        end_ts = int(datetime(year, 12, 31).timestamp() * 1000)
        n = conn.execute(
            'SELECT COUNT(DISTINCT symbol) FROM ohlcv WHERE timeframe="1d" AND timestamp >= ? AND timestamp <= ?',
            (start_ts, end_ts)
        ).fetchone()[0]
        print(f"  {year}: {n} symbols", flush=True)
    conn.close()

    # エラー例
    all_errors = mexc_err[:3] + binance_err[:3] + bybit_err[:3]
    if all_errors:
        print(f"\n  エラー例:", flush=True)
        for e in all_errors[:5]:
            print(f"    {e}", flush=True)

    return total_added


if __name__ == '__main__':
    main()
