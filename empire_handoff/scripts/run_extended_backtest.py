"""最長期間バックテスト: 7 Bot × 5 レバ = 35回

使い方:
  python scripts/run_extended_backtest.py
"""
import asyncio
import sys
import yaml
import csv
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

BOTS = [
    'surge', 'meanrevert',
    'meanrevert_adaptive', 'meanrevert_tight', 'meanrevert_hybrid',
    'meanrevert_newlist', 'meanrevert_tuned',
]

BOT_LABELS = {
    'surge': 'Surge', 'meanrevert': 'MeanRevert',
    'meanrevert_adaptive': 'MR-Adaptive', 'meanrevert_tight': 'MR-Tight',
    'meanrevert_hybrid': 'MR-Hybrid', 'meanrevert_newlist': 'MR-NewList',
    'meanrevert_tuned': 'MR-Tuned',
}

LEVERAGES = [1, 2, 3, 5, 10]

# 期間
MAX_START = '2023-07-01'  # データ開始直後はMA20計算に不足するため少し後ろ
MAX_END = '2026-03-01'
SHORT_START = '2024-01-01'
SHORT_END = '2026-03-01'


def run_single(bot_type: str, leverage: int, start: str, end: str,
               config: dict, db: HistoricalDB) -> dict:
    """単一バックテスト実行"""
    bot_config = config.get(f'bot_{bot_type}', {}).copy()
    bot_config['leverage'] = leverage
    bot_config['max_position_pct'] = 50

    engine = BacktestEngine(bot_type, bot_config, db)
    results = engine.run(start, end)

    # 破産チェック（最小資本が初期の10%以下）
    min_cap = results.get('min_capital', 1_000_000)
    bankrupt = min_cap < 100_000  # 10万円以下

    return {
        'bot': bot_type,
        'label': BOT_LABELS.get(bot_type, bot_type),
        'leverage': leverage,
        'period': f"{start}~{end}",
        'trades': results.get('total_trades', 0),
        'wr': results.get('win_rate', 0),
        'pf': min(results.get('profit_factor', 0), 999),
        'return': results.get('total_return_pct', 0),
        'mdd': results.get('max_drawdown_pct', 0),
        'sharpe': results.get('sharpe_ratio', 0),
        'min_cap': min_cap,
        'bankrupt': bankrupt,
        'final_cap': results.get('final_capital', 1_000_000),
        'equity_curve': results.get('equity_curve', []),
        'trades_list': engine.trades,
    }


def yearly_breakdown(trades_list: list, fg_map: dict = None) -> dict:
    """年度別の成績を集計"""
    yearly = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0, 'loss': 0, 'trades': 0})
    for t in trades_list:
        year = t.get('entry_date', '')[:4]
        if not year:
            continue
        pnl = t.get('pnl_leveraged_pct', 0)
        yearly[year]['trades'] += 1
        if pnl > 0:
            yearly[year]['wins'] += 1
            yearly[year]['profit'] += pnl
        else:
            yearly[year]['losses'] += 1
            yearly[year]['loss'] += abs(pnl)
    return dict(yearly)


def fear_breakdown(trades_list: list, equity_curve: list) -> dict:
    """Fear帯別の成績を集計（equity_curveからfg取得）"""
    # equity_curveからdate->fg mapを作成
    fg_map = {}
    for ec in equity_curve:
        fg_map[ec.get('date', '')] = ec.get('fg', 50)

    bands = {'<25': (0, 24), '25-50': (25, 50), '50-75': (50, 75), '>75': (76, 100)}
    result = {}
    for label, (lo, hi) in bands.items():
        subset = [t for t in trades_list if lo <= fg_map.get(t.get('entry_date', ''), 50) <= hi]
        n = len(subset)
        if n == 0:
            result[label] = {'trades': 0, 'wr': 0, 'pf': 0}
            continue
        wins = [t for t in subset if t.get('pnl_leveraged_pct', 0) > 0]
        losses = [t for t in subset if t.get('pnl_leveraged_pct', 0) <= 0]
        gp = sum(t.get('pnl_leveraged_pct', 0) for t in wins)
        gl = abs(sum(t.get('pnl_leveraged_pct', 0) for t in losses))
        result[label] = {
            'trades': n,
            'wr': len(wins) / n * 100 if n > 0 else 0,
            'pf': gp / gl if gl > 0 else 999,
        }
    return result


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()

    print("=" * 70)
    print("  最長期間バックテスト: 7 Bot × 5 レバ = 35 回")
    print(f"  最長期間: {MAX_START} ~ {MAX_END}")
    print(f"  比較期間: {SHORT_START} ~ {SHORT_END}")
    print("=" * 70)

    # ===== Table 1: 全組み合わせ（最長期間）=====
    all_results = []
    for bot in BOTS:
        for lev in LEVERAGES:
            print(f"  {BOT_LABELS.get(bot, bot):15s} lev={lev:2d}x ... ", end='', flush=True)
            r = run_single(bot, lev, MAX_START, MAX_END, config, db)
            all_results.append(r)
            bankrupt_mark = " 💀BANKRUPT" if r['bankrupt'] else ""
            print(f"T={r['trades']:>4d} WR={r['wr']:>5.1f}% PF={r['pf']:>6.2f} Ret={r['return']:>+9.1f}% MDD={r['mdd']:>6.1f}%{bankrupt_mark}")

    # ===== Table 3: 2年間比較（レバ2×固定）=====
    print(f"\n{'='*70}")
    print("  Table 3: 2年間 vs 最長期間 (レバ2×)")
    print(f"{'='*70}")

    short_results = {}
    for bot in BOTS:
        r = run_single(bot, 2, SHORT_START, SHORT_END, config, db)
        short_results[bot] = r

    print(f"\n  {'Bot':<16s} {'2Y_T':>5s} {'2Y_PF':>7s} {'2Y_Ret':>9s} {'Max_T':>6s} {'Max_PF':>7s} {'Max_Ret':>10s} {'PF変化':>8s}")
    print(f"  {'-'*70}")
    for bot in BOTS:
        sr = short_results[bot]
        # max期間のlev=2結果を探す
        mr = next((r for r in all_results if r['bot'] == bot and r['leverage'] == 2), None)
        if mr:
            pf_change = ((mr['pf'] / sr['pf']) - 1) * 100 if sr['pf'] > 0 else 0
            print(f"  {BOT_LABELS.get(bot, bot):<16s} {sr['trades']:>5d} {sr['pf']:>7.2f} {sr['return']:>+8.1f}% {mr['trades']:>6d} {mr['pf']:>7.2f} {mr['return']:>+9.1f}% {pf_change:>+7.0f}%")

    # ===== Table 4: 年度別成績（レバ2×、主力Bot）=====
    print(f"\n{'='*70}")
    print("  Table 4: 年度別成績 (レバ2×)")
    print(f"{'='*70}")

    for bot in BOTS:
        mr = next((r for r in all_results if r['bot'] == bot and r['leverage'] == 2), None)
        if not mr or mr['trades'] == 0:
            continue
        yearly = yearly_breakdown(mr['trades_list'])
        if not yearly:
            continue
        print(f"\n  {BOT_LABELS.get(bot, bot)}:")
        print(f"  {'Year':<8s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>9s}")
        for year in sorted(yearly.keys()):
            y = yearly[year]
            wr = y['wins'] / y['trades'] * 100 if y['trades'] > 0 else 0
            pf = y['profit'] / y['loss'] if y['loss'] > 0 else 999
            ret = y['profit'] - y['loss']
            bear_mark = " ⚠️" if year == '2022' else ""
            print(f"  {year:<8s} {y['trades']:>7d} {wr:>5.1f}% {pf:>7.2f} {ret:>+8.1f}%{bear_mark}")

    # ===== Table 5: 推奨レバレッジ =====
    print(f"\n{'='*70}")
    print("  Table 5: 推奨レバレッジ")
    print(f"{'='*70}")
    print(f"  {'Bot':<16s} {'保守(MDD<10%)':>14s} {'積極(MDD<20%)':>14s} {'最大許容':>10s} {'破産レバ':>10s}")
    print(f"  {'-'*66}")
    for bot in BOTS:
        conservative = '-'
        aggressive = '-'
        max_viable = '-'
        bankrupt_lev = '-'
        for lev in LEVERAGES:
            r = next((r for r in all_results if r['bot'] == bot and r['leverage'] == lev), None)
            if not r:
                continue
            if r['bankrupt']:
                bankrupt_lev = f"{lev}x"
                continue
            if abs(r['mdd']) < 10:
                conservative = f"{lev}x ({r['return']:+.0f}%)"
            if abs(r['mdd']) < 20:
                aggressive = f"{lev}x ({r['return']:+.0f}%)"
            max_viable = f"{lev}x"
        print(f"  {BOT_LABELS.get(bot, bot):<16s} {conservative:>14s} {aggressive:>14s} {max_viable:>10s} {bankrupt_lev:>10s}")

    # ===== Table 6: Fear帯別成績（レバ2×）=====
    print(f"\n{'='*70}")
    print("  Table 6: Fear帯別成績 (レバ2×)")
    print(f"{'='*70}")
    print(f"  {'Bot':<16s} {'Fear<25':>15s} {'Fear25-50':>15s} {'Fear50-75':>15s} {'Fear>75':>15s}")
    print(f"  {'-'*78}")
    for bot in BOTS:
        mr = next((r for r in all_results if r['bot'] == bot and r['leverage'] == 2), None)
        if not mr or mr['trades'] == 0:
            continue
        fb = fear_breakdown(mr['trades_list'], mr['equity_curve'])
        parts = []
        for band in ['<25', '25-50', '50-75', '>75']:
            b = fb.get(band, {})
            if b.get('trades', 0) > 0:
                parts.append(f"{b['trades']:>3d}t PF{b['pf']:>.1f}")
            else:
                parts.append(f"{'  -':>15s}")
        print(f"  {BOT_LABELS.get(bot, bot):<16s} {parts[0]:>15s} {parts[1]:>15s} {parts[2]:>15s} {parts[3]:>15s}")

    # ===== CSV保存 =====
    outdir = 'vault/backtest_results'
    csv_path = f"{outdir}/extended_backtest_summary.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['bot', 'leverage', 'period', 'trades', 'wr', 'pf', 'return', 'mdd', 'sharpe', 'min_cap', 'bankrupt'])
        for r in all_results:
            writer.writerow([r['bot'], r['leverage'], r['period'], r['trades'], round(r['wr'], 1),
                             round(r['pf'], 2), round(r['return'], 1), round(r['mdd'], 1),
                             round(r['sharpe'], 2), round(r['min_cap']), r['bankrupt']])
    print(f"\n  📁 CSV保存: {csv_path}")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    # Return all data for HTML generation
    return all_results, short_results


if __name__ == '__main__':
    asyncio.run(main())
