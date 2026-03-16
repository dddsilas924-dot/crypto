"""過去FR履歴の一括取得（MEXC API, ページネーション対応）

実行:
  python scripts/fetch_fr_history.py
  python scripts/fetch_fr_history.py --symbols 50 --since 2024-06-01

推定時間: 100銘柄 × 8ページ × 2秒 ≒ 27分
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import ccxt
from src.data.database import HistoricalDB
from src.data.funding_rate import FundingRateCollector


def get_top_symbols(db: HistoricalDB, limit: int = 100) -> list:
    """DB内の出来高上位N銘柄を取得"""
    conn = db._get_conn()
    rows = conn.execute(
        """SELECT symbol, SUM(volume) as total_vol
        FROM ohlcv WHERE timeframe='1d'
        GROUP BY symbol
        ORDER BY total_vol DESC
        LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser(description='Fetch FR history from MEXC')
    parser.add_argument('--symbols', type=int, default=100, help='取得銘柄数')
    parser.add_argument('--since', type=str, default='2024-03-01', help='開始日')
    parser.add_argument('--until', type=str, default='2026-03-01', help='終了日')
    args = parser.parse_args()

    print(f"[FR History] MEXC FR履歴取得開始（ページネーション対応）")
    print(f"  期間: {args.since} -> {args.until}")
    print(f"  銘柄数: {args.symbols}")
    print(f"  期待値: ~730件/銘柄 (8h間隔, 2年分)")

    db = HistoricalDB()
    symbols = get_top_symbols(db, args.symbols)
    print(f"  対象銘柄: {len(symbols)}件（DB出来高上位）")

    if not symbols:
        print("[ERROR] DB内に銘柄データがありません。先にOHLCVデータを取得してください。")
        return

    # MEXC sync接続
    exchange = ccxt.mexc({
        'options': {'defaultType': 'swap'},
    })

    collector = FundingRateCollector(exchange, db=db)

    start_time = time.time()
    total_count = 0
    success = 0
    failed = 0
    counts_per_symbol = []

    for i, symbol in enumerate(symbols):
        try:
            count = collector.fetch_history(symbol, args.since, args.until)
            total_count += count
            counts_per_symbol.append(count)
            if count > 0:
                success += 1
            status = "OK" if count >= 500 else ("LOW" if count > 0 else "EMPTY")
            print(f"  [{i+1}/{len(symbols)}] {symbol}: {count}件 (期待: ~730) [{status}]")
        except Exception as e:
            failed += 1
            counts_per_symbol.append(0)
            print(f"  [{i+1}/{len(symbols)}] {symbol}: ERROR: {e}")
        time.sleep(2.0)

    elapsed = time.time() - start_time
    minutes = elapsed / 60

    # DB確認
    conn = db._get_conn()
    total_in_db = conn.execute("SELECT COUNT(*) FROM funding_rate_history").fetchone()[0]
    symbols_with_data = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM funding_rate_history"
    ).fetchone()[0]
    conn.close()

    avg_per_symbol = total_in_db / symbols_with_data if symbols_with_data > 0 else 0
    coverage_pct = avg_per_symbol / 730 * 100 if avg_per_symbol > 0 else 0

    print(f"\n{'='*60}")
    print(f"  FR履歴取得完了")
    print(f"{'='*60}")
    print(f"  今回取得: {total_count}件")
    print(f"  成功: {success}銘柄 / 失敗: {failed}銘柄")
    print(f"  所要時間: {minutes:.1f}分")
    print(f"")
    print(f"  [DB合計]")
    print(f"  総レコード: {total_in_db}件")
    print(f"  銘柄数: {symbols_with_data}")
    print(f"  平均件数/銘柄: {avg_per_symbol:.0f} (期待値: ~730)")
    print(f"  カバー率: {coverage_pct:.1f}%")

    if avg_per_symbol < 365:
        print(f"\n  WARNING: カバー率が低い ({coverage_pct:.1f}%)。")
        print(f"  MEXCがこの銘柄のFR履歴を制限している可能性あり。")

    # Telegram通知
    try:
        import asyncio
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        text = (
            f"<b>FR履歴取得完了</b>\n"
            f"  銘柄: {success}/{len(symbols)}\n"
            f"  レコード: {total_count}件 (DB合計: {total_in_db})\n"
            f"  平均: {avg_per_symbol:.0f}件/銘柄\n"
            f"  カバー率: {coverage_pct:.1f}%\n"
            f"  所要時間: {minutes:.1f}分"
        )
        asyncio.run(alert.send_message(text))
    except Exception:
        pass


if __name__ == "__main__":
    main()
