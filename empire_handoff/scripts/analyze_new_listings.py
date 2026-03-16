"""新規上場銘柄分析 + バイアス検証スクリプト

Phase 2: データ分析（分布・年齢・PnL）
Phase 3: バイアス検証バックテスト（上場日数別フィルター）
"""
import sys
import sqlite3
import csv
import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data.database import HistoricalDB


def get_listing_dates(conn) -> dict:
    """各銘柄の推定上場日（最古の日足データ日）を取得"""
    rows = conn.execute(
        "SELECT symbol, MIN(timestamp) FROM ohlcv WHERE timeframe='1d' GROUP BY symbol"
    ).fetchall()
    result = {}
    for symbol, ts in rows:
        if ts:
            result[symbol] = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
    return result


def get_new_listing_flags(conn) -> set:
    """is_new_listing=1 の銘柄セット"""
    rows = conn.execute(
        "SELECT symbol FROM sanctuary WHERE is_new_listing=1"
    ).fetchall()
    return {r[0] for r in rows}


def symbol_age_at_date(listing_date_str: str, trade_date_str: str) -> int:
    """銘柄の上場からの日数を計算"""
    ld = datetime.strptime(listing_date_str, '%Y-%m-%d')
    td = datetime.strptime(trade_date_str, '%Y-%m-%d')
    return (td - ld).days


def phase2_distribution(conn, listing_dates: dict, nl_flags: set):
    """Phase 2-1: 新規銘柄の分布"""
    print("\n" + "=" * 60)
    print("  Phase 2-1: 新規銘柄の分布")
    print("=" * 60)

    # 全銘柄数
    all_symbols = set(listing_dates.keys())
    total = len(all_symbols)

    # バックテスト終了日基準で各期間内の銘柄数を算出
    ref_date = datetime(2026, 3, 1)
    buckets = {'30日以内': 0, '31-60日': 0, '61-90日': 0, '90日超': 0}

    for symbol, ld_str in listing_dates.items():
        ld = datetime.strptime(ld_str, '%Y-%m-%d')
        age = (ref_date - ld).days
        if age <= 30:
            buckets['30日以内'] += 1
        elif age <= 60:
            buckets['31-60日'] += 1
        elif age <= 90:
            buckets['61-90日'] += 1
        else:
            buckets['90日超'] += 1

    # is_new_listing flag の分布
    print(f"\n  全銘柄数: {total}")
    print(f"  is_new_listing=True: {len(nl_flags)}銘柄")
    print(f"\n  {'期間':<16s} {'銘柄数':>8s} {'全体比率':>10s}")
    print(f"  {'-'*36}")
    for label, count in buckets.items():
        pct = count / total * 100 if total > 0 else 0
        print(f"  {label:<16s} {count:>8d} {pct:>9.1f}%")

    # 上場日の年月別分布
    print(f"\n  上場年月別分布（上位10）:")
    monthly = defaultdict(int)
    for ld_str in listing_dates.values():
        monthly[ld_str[:7]] += 1
    for month, count in sorted(monthly.items(), key=lambda x: -x[1])[:10]:
        print(f"    {month}: {count}銘柄")

    return buckets


def phase2_trade_age_analysis(listing_dates: dict):
    """Phase 2-2 & 2-3: MeanRevert/WeakShortのトレード銘柄年齢分布 + PnL分析"""
    print("\n" + "=" * 60)
    print("  Phase 2-2: MeanRevert/WeakShort 銘柄年齢分布")
    print("=" * 60)

    bots = {
        'meanrevert': 'vault/backtest_results/bt_meanrevert_20240101_20260301.csv',
        'weakshort': None,
    }

    # WeakShortのCSVを探す
    ws_path = Path('vault/backtest_results/bt_weakshort_20240101_20260301.csv')
    if ws_path.exists():
        bots['weakshort'] = str(ws_path)

    age_buckets = {
        '0-30日': (0, 30),
        '31-60日': (31, 60),
        '61-90日': (61, 90),
        '91-180日': (91, 180),
        '181-365日': (181, 365),
        '365日超': (366, 99999),
    }

    results = {}

    for bot_name, csv_path in bots.items():
        if csv_path is None or not Path(csv_path).exists():
            print(f"\n  ⚠️ {bot_name} CSV not found, skipping")
            continue

        df = pd.read_csv(csv_path)
        if len(df) == 0:
            continue

        # 銘柄名からシンボルを復元（CSVのsymbol列）
        ages = []
        for _, row in df.iterrows():
            symbol = row['symbol']
            entry_date = row['entry_date']
            if symbol in listing_dates:
                age = symbol_age_at_date(listing_dates[symbol], entry_date)
                ages.append(age)
            else:
                ages.append(9999)  # 不明な場合は既存扱い

        df['age'] = ages

        # 年齢分布
        print(f"\n  {bot_name.upper()} (全{len(df)}トレード):")
        print(f"  {'年齢帯':<14s} {'トレード数':>10s} {'比率':>8s}")
        print(f"  {'-'*34}")
        for label, (lo, hi) in age_buckets.items():
            count = len(df[(df['age'] >= lo) & (df['age'] <= hi)])
            pct = count / len(df) * 100
            print(f"  {label:<14s} {count:>10d} {pct:>7.1f}%")

        # Phase 2-3: 新規 vs 既存 PnL
        new_df = df[df['age'] <= 90]
        old_df = df[df['age'] > 90]

        def calc_stats(sub_df, label):
            n = len(sub_df)
            if n == 0:
                return {'label': label, 'trades': 0, 'wr': 0, 'pf': 0, 'avg_pnl': 0, 'total_return': 0}
            wins = sub_df[sub_df['pnl_leveraged_pct'] > 0]
            losses = sub_df[sub_df['pnl_leveraged_pct'] <= 0]
            wr = len(wins) / n * 100
            gp = wins['pnl_leveraged_pct'].sum() if len(wins) > 0 else 0
            gl = abs(losses['pnl_leveraged_pct'].sum()) if len(losses) > 0 else 0.001
            pf = gp / gl if gl > 0 else 999
            avg = sub_df['pnl_leveraged_pct'].mean()
            total = sub_df['pnl_leveraged_pct'].sum()
            return {'label': label, 'trades': n, 'wr': wr, 'pf': pf, 'avg_pnl': avg, 'total_return': total}

        all_stats = calc_stats(df, f'{bot_name}全体')
        new_stats = calc_stats(new_df, f'{bot_name}新規(≤90日)')
        old_stats = calc_stats(old_df, f'{bot_name}既存(>90日)')

        results[bot_name] = {
            'all': all_stats,
            'new': new_stats,
            'old': old_stats,
            'df': df,
        }

    # Phase 2-3 テーブル表示
    print("\n" + "=" * 60)
    print("  Phase 2-3: 新規 vs 既存 PnL比較")
    print("=" * 60)

    header = f"  {'':20s} "
    for bot_name in ['meanrevert', 'weakshort']:
        if bot_name in results:
            for suffix in ['全体', '新規', '既存']:
                header += f"{'':>10s}"
    print(f"\n  {'指標':<12s}", end='')
    for bot_name in ['meanrevert', 'weakshort']:
        if bot_name not in results:
            continue
        for label in ['全体', '新規(≤90d)', '既存(>90d)']:
            short = f"{bot_name[:2].upper()}_{label}"
            print(f" {short:>14s}", end='')
    print()
    print(f"  {'-'*70}")

    for metric_key, metric_label, fmt in [
        ('trades', 'トレード数', '{:>14d}'),
        ('wr', '勝率', '{:>13.1f}%'),
        ('pf', 'PF', '{:>14.2f}'),
        ('avg_pnl', '平均PnL', '{:>13.1f}%'),
        ('total_return', 'Return', '{:>13.1f}%'),
    ]:
        print(f"  {metric_label:<12s}", end='')
        for bot_name in ['meanrevert', 'weakshort']:
            if bot_name not in results:
                continue
            for seg in ['all', 'new', 'old']:
                v = results[bot_name][seg][metric_key]
                if metric_key == 'trades':
                    print(f" {v:>14d}", end='')
                elif metric_key == 'wr':
                    print(f" {v:>13.1f}%", end='')
                elif metric_key == 'pf':
                    print(f" {v:>14.2f}", end='')
                else:
                    print(f" {v:>13.1f}%", end='')
        print()

    return results


def phase3_bias_backtest(listing_dates: dict):
    """Phase 3: バイアス検証バックテスト（上場日数フィルター別）"""
    from src.backtest.backtest_engine import BacktestEngine

    print("\n" + "=" * 60)
    print("  Phase 3: バイアス検証バックテスト")
    print("=" * 60)

    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()

    filters = [
        ('全銘柄', None, None),
        ('新規のみ(≤30日)', 0, 30),
        ('新規のみ(≤60日)', 0, 60),
        ('新規のみ(≤90日)', 0, 90),
        ('既存のみ(>90日)', 91, None),
    ]

    results_table = []

    for bot_type in ['meanrevert', 'weakshort']:
        bot_config = config.get(f'bot_{bot_type}', {}).copy()

        for filter_label, age_min, age_max in filters:
            # age filterをconfigに注入
            bc = bot_config.copy()
            if age_min is not None or age_max is not None:
                bc['_listing_dates'] = listing_dates
                bc['_age_min'] = age_min
                bc['_age_max'] = age_max

            engine = BacktestEngine(bot_type, bc, db)
            r = engine.run('2024-01-01', '2026-03-01')

            row = {
                'bot': bot_type,
                'filter': filter_label,
                'trades': r.get('total_trades', 0),
                'wr': r.get('win_rate', 0),
                'pf': r.get('profit_factor', 0),
                'return': r.get('total_return_pct', 0),
                'mdd': r.get('max_drawdown_pct', 0),
            }
            results_table.append(row)
            pf_str = f"{row['pf']:.2f}" if row['pf'] < 900 else "N/A"
            print(f"  {bot_type:15s} {filter_label:20s} T={row['trades']:>4d} WR={row['wr']:>5.1f}% PF={pf_str:>6s} Ret={row['return']:>+8.1f}% MDD={row['mdd']:>6.1f}%")

    # 最終テーブル
    print(f"\n  {'Bot':<15s} {'フィルター':<22s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>9s} {'MDD':>7s}")
    print(f"  {'-'*75}")
    for r in results_table:
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 900 else "N/A"
        print(f"  {r['bot']:<15s} {r['filter']:<22s} {r['trades']:>7d} {r['wr']:>5.1f}% {pf_str:>7s} {r['return']:>+8.1f}% {r['mdd']:>6.1f}%")

    return results_table


def main():
    db = HistoricalDB()
    conn = db._get_conn()

    listing_dates = get_listing_dates(conn)
    nl_flags = get_new_listing_flags(conn)

    print(f"📊 新規上場銘柄分析")
    print(f"  銘柄総数: {len(listing_dates)}")
    print(f"  is_new_listing=True: {len(nl_flags)}")

    # Phase 2-1
    buckets = phase2_distribution(conn, listing_dates, nl_flags)

    # Phase 2-2 & 2-3
    pnl_results = phase2_trade_age_analysis(listing_dates)

    conn.close()

    # Phase 3: engine-based age-filtered backtests
    phase3_results = phase3_bias_backtest(listing_dates)

    # Phase 3 supplement: CSV-based heatmap
    phase3_csv_analysis(listing_dates)

    return pnl_results, phase3_results


def phase3_csv_analysis(listing_dates: dict):
    """CSVベースの上場日数別分析（エンジン変更不要）"""
    print("\n" + "=" * 60)
    print("  Phase 3: CSV銘柄年齢別分析")
    print("=" * 60)

    bots = {
        'MeanRevert': 'vault/backtest_results/bt_meanrevert_20240101_20260301.csv',
        'WeakShort': 'vault/backtest_results/bt_weakshort_20240101_20260301.csv',
    }

    age_ranges = [
        ('0-30日', 0, 30),
        ('31-60日', 31, 60),
        ('61-90日', 61, 90),
        ('90日超', 91, 99999),
    ]

    for bot_name, csv_path in bots.items():
        if not Path(csv_path).exists():
            print(f"  ⚠️ {csv_path} not found")
            continue

        df = pd.read_csv(csv_path)
        ages = []
        for _, row in df.iterrows():
            symbol = row['symbol']
            entry_date = row['entry_date']
            if symbol in listing_dates:
                age = symbol_age_at_date(listing_dates[symbol], entry_date)
            else:
                age = 9999
            ages.append(age)
        df['age'] = ages

        print(f"\n  {bot_name} 上場日数別PnLヒートマップ:")
        print(f"  {'年齢帯':<12s} {'Trades':>8s} {'WR':>7s} {'PF':>7s} {'AvgPnL':>9s} {'Return':>10s}")
        print(f"  {'-'*55}")

        for label, lo, hi in age_ranges:
            sub = df[(df['age'] >= lo) & (df['age'] <= hi)]
            n = len(sub)
            if n == 0:
                print(f"  {label:<12s} {0:>8d}      -       -         -          -")
                continue
            wins = sub[sub['pnl_leveraged_pct'] > 0]
            losses = sub[sub['pnl_leveraged_pct'] <= 0]
            wr = len(wins) / n * 100
            gp = wins['pnl_leveraged_pct'].sum() if len(wins) > 0 else 0
            gl = abs(losses['pnl_leveraged_pct'].sum()) if len(losses) > 0 else 0.001
            pf = gp / gl
            avg = sub['pnl_leveraged_pct'].mean()
            total = sub['pnl_leveraged_pct'].sum()
            print(f"  {label:<12s} {n:>8d} {wr:>6.1f}% {pf:>7.2f} {avg:>+8.1f}% {total:>+9.1f}%")


if __name__ == '__main__':
    main()
