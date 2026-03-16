"""ヒストリカルデータの期間確認スクリプト"""
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data.database import HistoricalDB


def main():
    db = HistoricalDB()
    conn = db._get_conn()

    # 全銘柄の最古・最新日付
    rows = conn.execute(
        "SELECT symbol, MIN(timestamp), MAX(timestamp), COUNT(*) "
        "FROM ohlcv WHERE timeframe='1d' GROUP BY symbol ORDER BY MIN(timestamp)"
    ).fetchall()

    print(f"📊 ヒストリカルデータ期間確認")
    print(f"  日足データを持つ銘柄数: {len(rows)}")

    now = datetime(2026, 3, 1)
    buckets = defaultdict(int)
    earliest_symbols = []

    for symbol, min_ts, max_ts, count in rows:
        min_dt = datetime.fromtimestamp(min_ts / 1000)
        max_dt = datetime.fromtimestamp(max_ts / 1000)
        years = (now - min_dt).days / 365.25

        if years >= 6:
            buckets['6年以上'] += 1
        elif years >= 5:
            buckets['5年以上'] += 1
        elif years >= 4:
            buckets['4年以上'] += 1
        elif years >= 3:
            buckets['3年以上'] += 1
        elif years >= 2:
            buckets['2年以上'] += 1
        elif years >= 1:
            buckets['1年以上'] += 1
        else:
            buckets['1年未満'] += 1

        if len(earliest_symbols) < 15:
            earliest_symbols.append((symbol, min_dt.strftime('%Y-%m-%d'), max_dt.strftime('%Y-%m-%d'), count))

    print(f"\n  {'データ期間':<16s} {'銘柄数':>8s}")
    print(f"  {'-'*26}")
    for label in ['6年以上', '5年以上', '4年以上', '3年以上', '2年以上', '1年以上', '1年未満']:
        print(f"  {label:<16s} {buckets.get(label, 0):>8d}")

    print(f"\n  最古データ銘柄TOP15:")
    for sym, start, end, cnt in earliest_symbols:
        print(f"    {sym:<25s} {start} 〜 {end} ({cnt}本)")

    # Fear&Greed履歴
    fg_rows = conn.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM fear_greed_history"
    ).fetchone()
    if fg_rows and fg_rows[0]:
        print(f"\n  Fear&Greed履歴: {fg_rows[0]} 〜 {fg_rows[1]} ({fg_rows[2]}日分)")
    else:
        print(f"\n  Fear&Greed履歴: なし")

    conn.close()


if __name__ == '__main__':
    main()
