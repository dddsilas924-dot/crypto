"""ヒストリカルデータ拡張 - 各銘柄の最古データ以前まで遡って取得

MEXC APIは1回のfetch_ohlcvで最大1000本。
既存データの最古タイムスタンプから遡って取得を繰り返す。
"""
import asyncio
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import ccxt.async_support as ccxt
import pandas as pd
from src.data.database import HistoricalDB


async def extend_data():
    exchange = ccxt.mexc({
        'options': {'defaultType': 'swap'},
    })

    db = HistoricalDB()
    conn = db._get_conn()

    # 全銘柄の現在の最古タイムスタンプ取得
    rows = conn.execute(
        "SELECT s.symbol, MIN(o.timestamp) as oldest "
        "FROM sector s LEFT JOIN ohlcv o ON s.symbol = o.symbol AND o.timeframe='1d' "
        "WHERE s.is_crypto=1 GROUP BY s.symbol ORDER BY s.symbol"
    ).fetchall()

    print(f"📊 ヒストリカルデータ拡張")
    print(f"  対象銘柄: {len(rows)}")
    print(f"  開始: {datetime.now().strftime('%H:%M:%S')}")

    total_added = 0
    extended_count = 0
    errors = []
    skipped = 0

    for i, (symbol, oldest_ts) in enumerate(rows):
        try:
            if oldest_ts is None:
                # OHLCVデータなし - 全期間取得
                since = int(datetime(2020, 1, 1).timestamp() * 1000)
            else:
                since = int(oldest_ts)

            # 2020-01-01より古いデータはほぼないので、そこまで遡る
            target_oldest = int(datetime(2020, 1, 1).timestamp() * 1000)

            if oldest_ts and oldest_ts <= target_oldest:
                skipped += 1
                continue  # 既に十分古い

            # 遡りループ（最大5回 = 5000本追加）
            batch_added = 0
            current_since = target_oldest

            for attempt in range(5):
                try:
                    data = await exchange.fetch_ohlcv(symbol, '1d', since=current_since, limit=1000)
                except Exception as e:
                    if 'not exist' in str(e).lower() or '30004' in str(e):
                        break  # この銘柄は先物に存在しない
                    raise

                if not data or len(data) == 0:
                    break

                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)

                # 既存データより古いものだけ挿入
                if oldest_ts:
                    old_dt = datetime.fromtimestamp(oldest_ts / 1000)
                    df = df[df.index < old_dt]

                if len(df) == 0:
                    break

                count = db.upsert_ohlcv(symbol, '1d', df)
                batch_added += count

                # 次のバッチのsinceを更新
                last_ts = int(data[-1][0])
                if last_ts >= (oldest_ts or float('inf')):
                    break
                current_since = last_ts + 86400000  # 1日後

                await asyncio.sleep(0.2)

            if batch_added > 0:
                total_added += batch_added
                extended_count += 1

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(rows)}] 拡張済: {extended_count}銘柄, 追加: {total_added}レコード, Skip: {skipped}")

            await asyncio.sleep(0.3)

        except Exception as e:
            err_msg = str(e)[:80]
            errors.append(f"{symbol}: {err_msg}")
            await asyncio.sleep(1)

    await exchange.close()
    conn.close()

    print(f"\n✅ データ拡張完了!")
    print(f"  拡張銘柄数: {extended_count}")
    print(f"  追加レコード: {total_added:,}")
    print(f"  スキップ: {skipped}")
    print(f"  エラー: {len(errors)}")
    if errors[:5]:
        print(f"  エラー例:")
        for e in errors[:5]:
            print(f"    {e}")

    return total_added


if __name__ == '__main__':
    added = asyncio.run(extend_data())
    # 拡張後のデータ期間確認
    print("\n--- 拡張後のデータ期間 ---")
    import subprocess
    subprocess.run([sys.executable, 'scripts/check_data_range.py'])
