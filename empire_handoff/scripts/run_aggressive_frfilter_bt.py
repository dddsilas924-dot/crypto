"""
aggressive系 FR方向フィルター付きバックテスト
5 BOT種 × depth(1x~5x) × fr_direction_filter = 30 configs
2年間 (2024-03-14 ~ 2026-03-14)
"""
import sys
import csv
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

START = '2024-03-14'
END = '2026-03-14'
OUT_DIR = Path('vault/backtest_results/variants')

BASE_TP = 3.0
BASE_SL = 1.0

# 3 leverage × 5 depth × fr_filter ON/OFF... but user said "同じ30パターン"
# So: lev1/lev3/7x × depth 1x~5x × fr_direction_filter=True = 15 configs
# Plus fr_direction_filter=False for comparison = 15 configs → total 30
CONFIGS = []
for lev, lev_tag in [(1, 'lev1'), (3, 'lev3'), (7, '7x')]:
    for depth in [1, 2, 3, 4, 5]:
        for fr_filter in [False, True]:
            ff_tag = 'fr' if fr_filter else 'nf'
            CONFIGS.append({
                'key': f'agg_{lev_tag}_{depth}x_{ff_tag}',
                'lev': lev,
                'tp_mult': depth,
                'sl_mult': depth,
                'fr_direction_filter': fr_filter,
            })


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = HistoricalDB()
    results = []
    total = len(CONFIGS)
    t0 = time.time()

    print(f"=== Aggressive FR-Filter Backtest ({total} configs, {START}~{END}) ===\n")

    for i, cfg in enumerate(CONFIGS, 1):
        tp = BASE_TP * cfg['tp_mult']
        sl = BASE_SL * cfg['sl_mult']
        fr_tag = 'FR_FILTER' if cfg['fr_direction_filter'] else 'NO_FILTER'

        print(f"[{i}/{total}] {cfg['key']} (lev{cfg['lev']} TP{tp:.0f}/SL{sl:.0f} {fr_tag}) ... ", end='', flush=True)

        bot_cfg = {
            'leverage': cfg['lev'],
            'take_profit_pct': tp,
            'stop_loss_pct': sl,
            'position_size_pct': 30,
            'max_holding_days': 14,
            'max_total_positions': 20,
            'short_only': False,
            'fr_direction_filter': cfg['fr_direction_filter'],
            'fr_threshold': 0.3,
            'vol_threshold': 3.0,
            'fallback_to_proxy': True,
        }

        engine = BacktestEngine('levburn_sec', bot_cfg, db)
        try:
            result = engine.run(START, END)
            if 'error' in result:
                print(f"SKIP: {result['error']}")
                continue

            trades = result.get('trades', 0)
            if isinstance(trades, list):
                trades = len(trades)

            r = {
                'key': cfg['key'],
                'leverage': cfg['lev'],
                'tp_pct': tp,
                'sl_pct': sl,
                'depth': f"{cfg['tp_mult']}x",
                'fr_filter': cfg['fr_direction_filter'],
                'trades': trades,
                'win_rate': result.get('win_rate', 0),
                'profit_factor': result.get('profit_factor', 0),
                'total_return_pct': result.get('total_return_pct', 0),
                'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                'sharpe_ratio': result.get('sharpe_ratio', 0),
                'final_capital': result.get('final_capital', 1000000),
            }
            results.append(r)
            print(f"OK  tr={r['trades']} WR={r['win_rate']:.1f}% PF={r['profit_factor']:.2f} "
                  f"ret={r['total_return_pct']:.1f}% sharpe={r['sharpe_ratio']:.2f}")
        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()

    elapsed = time.time() - t0

    # CSV
    csv_path = OUT_DIR / 'aggressive_frfilter_bt.csv'
    if results:
        fields = list(results[0].keys())
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                w.writerow(r)

    print(f"\n=== Done ({elapsed:.0f}s) — {csv_path} ===\n")

    # Summary: grouped by leverage for easy comparison
    for lev in [1, 3, 7]:
        lev_results = [r for r in results if r['leverage'] == lev]
        if not lev_results:
            continue
        print(f"\n--- Leverage {lev}x ---")
        print(f"{'Key':<22} {'Depth':>5} {'Filter':>6} {'Tr':>4} {'WR%':>6} {'PF':>6} {'Ret%':>9} {'MDD%':>7} {'Sharpe':>6}")
        for r in sorted(lev_results, key=lambda x: (x['depth'], x['fr_filter'])):
            ff = 'FR' if r['fr_filter'] else '--'
            print(f"{r['key']:<22} {r['depth']:>5} {ff:>6} {r['trades']:>4} {r['win_rate']:>6.1f} "
                  f"{r['profit_factor']:>6.2f} {r['total_return_pct']:>9.1f} {r['max_drawdown_pct']:>7.1f} {r['sharpe_ratio']:>6.2f}")


if __name__ == '__main__':
    main()
