"""
aggressive系 深掘りバックテスト
5 BOT種 × depth(4x,5x) × long_filter(ON/OFF) + 7x long_filter
2年間 (2024-03-14 ~ 2026-03-14)
"""
import sys
import csv
import time
import traceback
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import yaml
from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

START = '2024-03-14'
END = '2026-03-14'
OUT_DIR = Path('vault/backtest_results/variants')

# Base TP/SL for aggressive: TP=3.0%, SL=1.0%
BASE_TP = 3.0
BASE_SL = 1.0

CONFIGS = [
    # aggressive_lev1 (1x) - depth 4x/5x × long_filter ON/OFF
    {'key': 'agg_lev1_4x',         'lev': 1,  'tp_mult': 4, 'sl_mult': 4, 'short_only': False},
    {'key': 'agg_lev1_4x_so',      'lev': 1,  'tp_mult': 4, 'sl_mult': 4, 'short_only': True},
    {'key': 'agg_lev1_5x',         'lev': 1,  'tp_mult': 5, 'sl_mult': 5, 'short_only': False},
    {'key': 'agg_lev1_5x_so',      'lev': 1,  'tp_mult': 5, 'sl_mult': 5, 'short_only': True},

    # aggressive_lev3 (3x) - depth 4x/5x × long_filter ON/OFF
    {'key': 'agg_lev3_4x',         'lev': 3,  'tp_mult': 4, 'sl_mult': 4, 'short_only': False},
    {'key': 'agg_lev3_4x_so',      'lev': 3,  'tp_mult': 4, 'sl_mult': 4, 'short_only': True},
    {'key': 'agg_lev3_5x',         'lev': 3,  'tp_mult': 5, 'sl_mult': 5, 'short_only': False},
    {'key': 'agg_lev3_5x_so',      'lev': 3,  'tp_mult': 5, 'sl_mult': 5, 'short_only': True},

    # aggressive (7x) - current depth × long_filter ON/OFF
    {'key': 'agg_7x_1x',           'lev': 7,  'tp_mult': 1, 'sl_mult': 1, 'short_only': False},
    {'key': 'agg_7x_1x_so',        'lev': 7,  'tp_mult': 1, 'sl_mult': 1, 'short_only': True},

    # ---- 比較用: 既存の1x,2x,3x depth も含める ----
    # lev1
    {'key': 'agg_lev1_1x',         'lev': 1,  'tp_mult': 1, 'sl_mult': 1, 'short_only': False},
    {'key': 'agg_lev1_1x_so',      'lev': 1,  'tp_mult': 1, 'sl_mult': 1, 'short_only': True},
    {'key': 'agg_lev1_2x',         'lev': 1,  'tp_mult': 2, 'sl_mult': 2, 'short_only': False},
    {'key': 'agg_lev1_2x_so',      'lev': 1,  'tp_mult': 2, 'sl_mult': 2, 'short_only': True},
    {'key': 'agg_lev1_3x',         'lev': 1,  'tp_mult': 3, 'sl_mult': 3, 'short_only': False},
    {'key': 'agg_lev1_3x_so',      'lev': 1,  'tp_mult': 3, 'sl_mult': 3, 'short_only': True},
    # lev3
    {'key': 'agg_lev3_1x',         'lev': 3,  'tp_mult': 1, 'sl_mult': 1, 'short_only': False},
    {'key': 'agg_lev3_1x_so',      'lev': 3,  'tp_mult': 1, 'sl_mult': 1, 'short_only': True},
    {'key': 'agg_lev3_2x',         'lev': 3,  'tp_mult': 2, 'sl_mult': 2, 'short_only': False},
    {'key': 'agg_lev3_2x_so',      'lev': 3,  'tp_mult': 2, 'sl_mult': 2, 'short_only': True},
    {'key': 'agg_lev3_3x',         'lev': 3,  'tp_mult': 3, 'sl_mult': 3, 'short_only': False},
    {'key': 'agg_lev3_3x_so',      'lev': 3,  'tp_mult': 3, 'sl_mult': 3, 'short_only': True},
    # 7x comparison depths
    {'key': 'agg_7x_2x',           'lev': 7,  'tp_mult': 2, 'sl_mult': 2, 'short_only': False},
    {'key': 'agg_7x_2x_so',        'lev': 7,  'tp_mult': 2, 'sl_mult': 2, 'short_only': True},
    {'key': 'agg_7x_3x',           'lev': 7,  'tp_mult': 3, 'sl_mult': 3, 'short_only': False},
    {'key': 'agg_7x_3x_so',        'lev': 7,  'tp_mult': 3, 'sl_mult': 3, 'short_only': True},
    {'key': 'agg_7x_4x',           'lev': 7,  'tp_mult': 4, 'sl_mult': 4, 'short_only': False},
    {'key': 'agg_7x_4x_so',        'lev': 7,  'tp_mult': 4, 'sl_mult': 4, 'short_only': True},
    {'key': 'agg_7x_5x',           'lev': 7,  'tp_mult': 5, 'sl_mult': 5, 'short_only': False},
    {'key': 'agg_7x_5x_so',        'lev': 7,  'tp_mult': 5, 'sl_mult': 5, 'short_only': True},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = HistoricalDB()
    results = []
    total = len(CONFIGS)
    t0 = time.time()

    print(f"=== Aggressive Depth Backtest ({total} configs, {START}~{END}) ===\n")

    for i, cfg in enumerate(CONFIGS, 1):
        tp = BASE_TP * cfg['tp_mult']
        sl = BASE_SL * cfg['sl_mult']
        so_tag = 'SHORT_ONLY' if cfg['short_only'] else 'L+S'

        print(f"[{i}/{total}] {cfg['key']} (lev{cfg['lev']} TP{tp:.1f}/SL{sl:.1f} {so_tag}) ... ", end='', flush=True)

        bot_cfg = {
            'leverage': cfg['lev'],
            'take_profit_pct': tp,
            'stop_loss_pct': sl,
            'position_size_pct': 30,
            'max_holding_days': 14,
            'max_total_positions': 20,
            'short_only': cfg['short_only'],
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
                'short_only': cfg['short_only'],
                'depth': f"{cfg['tp_mult']}x",
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
                  f"ret={r['total_return_pct']:.1f}% mdd={r['max_drawdown_pct']:.1f}% sharpe={r['sharpe_ratio']:.2f}")
        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()

    elapsed = time.time() - t0

    # CSV
    csv_path = OUT_DIR / 'aggressive_depth_bt.csv'
    if results:
        fields = list(results[0].keys())
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                w.writerow(r)

    print(f"\n=== Done ({elapsed:.0f}s) — {csv_path} ===\n")

    # Summary table
    print(f"{'Key':<25} {'Lev':>3} {'TP/SL':>10} {'Mode':<5} {'Tr':>4} {'WR%':>6} {'PF':>6} {'Ret%':>9} {'MDD%':>7} {'Sharpe':>6}")
    print('=' * 90)
    for r in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
        mode = 'SO' if r['short_only'] else 'L+S'
        print(f"{r['key']:<25} {r['leverage']:>3}x {r['tp_pct']:>4.1f}/{r['sl_pct']:<4.1f} {mode:<5} "
              f"{r['trades']:>4} {r['win_rate']:>6.1f} {r['profit_factor']:>6.2f} "
              f"{r['total_return_pct']:>9.1f} {r['max_drawdown_pct']:>7.1f} {r['sharpe_ratio']:>6.2f}")


if __name__ == '__main__':
    main()
