"""高頻度Bot バックテスト: 5 HF Bot × 3 レバ = 15回

使い方:
  python scripts/run_hf_backtest.py
"""
import sys
import yaml
import csv
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.hf_backtest_engine import HFBacktestEngine

HF_BOTS = ['hf_meanrevert', 'hf_momentum', 'hf_spread', 'hf_break', 'hf_frarb']
BOT_LABELS = {
    'hf_meanrevert': 'HF-MeanRevert',
    'hf_momentum': 'HF-Momentum',
    'hf_spread': 'HF-Spread',
    'hf_break': 'HF-Break',
    'hf_frarb': 'HF-FRArb',
}
LEVERAGES = [3, 5, 10]


def run_single(bot_type: str, leverage: int, start: str, end: str,
               config: dict, db: HistoricalDB) -> dict:
    bot_config = config.get(f'bot_{bot_type}', {}).copy()
    bot_config['leverage'] = leverage
    bot_config['max_position_pct'] = 50

    engine = HFBacktestEngine(bot_type, bot_config, db)
    results = engine.run(start, end)

    return {
        'bot': bot_type,
        'label': BOT_LABELS.get(bot_type, bot_type),
        'leverage': leverage,
        'period': f"{start}~{end}",
        'trades': results.get('total_trades', 0),
        'wr': results.get('win_rate', 0),
        'pf': results.get('profit_factor', 0),
        'return': results.get('total_return_pct', 0),
        'mdd': results.get('max_drawdown_pct', 0),
        'sharpe': results.get('sharpe_ratio', 0),
        'avg_hold_h': results.get('avg_holding_hours', 0),
        'trades_day': results.get('trades_per_day', 0),
        'max_simul': results.get('max_simultaneous', 0),
        'skipped': results.get('skipped_count', 0),
        'final_cap': results.get('final_capital', 1_000_000),
        'trades_list': engine.trades,
        'equity_curve': results.get('equity_curve', []),
    }


def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    conn = db._get_conn()

    # 1h足データ範囲確認
    r = conn.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT symbol) FROM ohlcv WHERE timeframe='1h'").fetchone()
    if not r[0]:
        print("ERROR: 1h足データなし")
        return
    oldest = datetime.fromtimestamp(r[0] / 1000)
    newest = datetime.fromtimestamp(r[1] / 1000)
    n_symbols = r[2]
    conn.close()

    # バックテスト期間（1h足データ範囲に合わせる）
    # MA20計算に20h必要なので少し後ろからスタート
    start_date = (oldest + __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')
    end_date = newest.strftime('%Y-%m-%d')

    print("=" * 80, flush=True)
    print(f"  高頻度Bot バックテスト: {len(HF_BOTS)} Bot × {len(LEVERAGES)} レバ = {len(HF_BOTS)*len(LEVERAGES)} 回", flush=True)
    print(f"  1h足データ: {oldest.date()} ~ {newest.date()} ({n_symbols}銘柄)", flush=True)
    print(f"  バックテスト期間: {start_date} ~ {end_date}", flush=True)
    print("=" * 80, flush=True)

    all_results = []
    start_time = time.time()

    for bot in HF_BOTS:
        for lev in LEVERAGES:
            print(f"  {BOT_LABELS[bot]:20s} {lev:2d}x ... ", end='', flush=True)
            t0 = time.time()
            r = run_single(bot, lev, start_date, end_date, config, db)
            elapsed = time.time() - t0
            all_results.append(r)
            print(f"T={r['trades']:>5d} WR={r['wr']:>5.1f}% PF={r['pf']:>6.2f} "
                  f"Ret={r['return']:>+9.1f}% MDD={r['mdd']:>6.1f}% "
                  f"T/d={r['trades_day']:>4.1f} AvgH={r['avg_hold_h']:>4.1f}h "
                  f"({elapsed:.1f}s)", flush=True)

    # 合算シミュレーション
    print(f"\n{'='*80}", flush=True)
    print("  合算シミュレーション (全5Bot同時稼働, レバ5×)", flush=True)
    print(f"{'='*80}", flush=True)

    total_trades = sum(r['trades'] for r in all_results if r['leverage'] == 5)
    total_days = len(all_results[0]['equity_curve']) if all_results[0]['equity_curve'] else 1
    avg_trades_day = total_trades / max(total_days, 1)

    # レバ5×の各Bot結果
    lev5_results = [r for r in all_results if r['leverage'] == 5]
    print(f"\n  {'Bot':<20s} {'Trades':>7s} {'T/d':>5s} {'WR':>6s} {'PF':>7s} {'Return':>10s} {'MDD':>7s}", flush=True)
    print(f"  {'-'*70}", flush=True)
    for r in lev5_results:
        print(f"  {r['label']:<20s} {r['trades']:>7d} {r['trades_day']:>5.1f} {r['wr']:>5.1f}% "
              f"{r['pf']:>7.2f} {r['return']:>+9.1f}% {r['mdd']:>6.1f}%", flush=True)
    print(f"  {'合計':<20s} {total_trades:>7d} {avg_trades_day:>5.1f}", flush=True)
    print(f"\n  目標: 1日20回 → 実績: {avg_trades_day:.1f}回/日", flush=True)

    # CSV保存
    csv_path = 'vault/backtest_results/hf_backtest_summary.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['bot', 'leverage', 'period', 'trades', 'wr', 'pf', 'return', 'mdd',
                         'sharpe', 'avg_hold_h', 'trades_per_day', 'max_simultaneous', 'skipped'])
        for r in all_results:
            writer.writerow([r['bot'], r['leverage'], r['period'], r['trades'],
                             round(r['wr'], 1), round(r['pf'], 2), round(r['return'], 1),
                             round(r['mdd'], 1), round(r['sharpe'], 2), round(r['avg_hold_h'], 1),
                             round(r['trades_day'], 1), r['max_simul'], r['skipped']])
    print(f"\n  CSV: {csv_path}", flush=True)

    total_elapsed = time.time() - start_time
    print(f"\n  処理時間: {total_elapsed:.0f}秒", flush=True)

    return all_results


if __name__ == '__main__':
    main()
