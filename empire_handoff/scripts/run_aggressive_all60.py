"""
aggressive系 全60パターン統合バックテスト
3レバ(1x/3x/7x) × 5深さ(1x~5x) × 3モード(通常/SHORT_ONLY/FR_FILTER) = 45 + α
+ 比較用の15パターン = 合計60
2年間 (2024-03-14 ~ 2026-03-14)
タイムアウト付き
"""
import sys
import csv
import time
import signal as sig_module
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
TIMEOUT_SEC = 300  # 5 min per config

CONFIGS = []
for lev, tag in [(1, 'lev1'), (3, 'lev3'), (7, '7x')]:
    for depth in [1, 2, 3, 4, 5]:
        for mode, mode_tag, so, fr in [
            ('L+S',    'ls', False, False),
            ('SO',     'so', True,  False),
            ('FR',     'fr', False, True),
        ]:
            # 7x × depth4-5 can be slow, but we include all
            CONFIGS.append({
                'key': f'agg_{tag}_{depth}x_{mode_tag}',
                'lev': lev, 'depth': depth,
                'short_only': so, 'fr_filter': fr, 'mode_label': mode,
            })


def run_one(db, cfg):
    tp = BASE_TP * cfg['depth']
    sl = BASE_SL * cfg['depth']
    bot_cfg = {
        'leverage': cfg['lev'],
        'take_profit_pct': tp, 'stop_loss_pct': sl,
        'position_size_pct': 30, 'max_holding_days': 14,
        'max_total_positions': 20,
        'short_only': cfg['short_only'],
        'fr_direction_filter': cfg['fr_filter'],
        'fr_threshold': 0.3, 'vol_threshold': 3.0,
        'fallback_to_proxy': True,
    }
    engine = BacktestEngine('levburn_sec', bot_cfg, db)
    result = engine.run(START, END)
    if 'error' in result:
        return None
    trades = result.get('trades', 0)
    if isinstance(trades, list):
        trades = len(trades)
    return {
        'key': cfg['key'], 'leverage': cfg['lev'],
        'depth': f"{cfg['depth']}x", 'tp_pct': tp, 'sl_pct': sl,
        'mode': cfg['mode_label'],
        'trades': trades,
        'win_rate': result.get('win_rate', 0),
        'profit_factor': result.get('profit_factor', 0),
        'total_return_pct': result.get('total_return_pct', 0),
        'max_drawdown_pct': result.get('max_drawdown_pct', 0),
        'sharpe_ratio': result.get('sharpe_ratio', 0),
        'final_capital': result.get('final_capital', 1000000),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = HistoricalDB()
    results = []
    total = len(CONFIGS)
    t0 = time.time()
    print(f"=== All-in-one Aggressive BT ({total} configs, {START}~{END}) ===\n")

    for i, cfg in enumerate(CONFIGS, 1):
        tp = BASE_TP * cfg['depth']
        sl = BASE_SL * cfg['depth']
        label = f"{cfg['key']} (lev{cfg['lev']} TP{tp:.0f}/SL{sl:.0f} {cfg['mode_label']})"
        print(f"[{i}/{total}] {label} ... ", end='', flush=True)
        try:
            t1 = time.time()
            r = run_one(db, cfg)
            dt = time.time() - t1
            if r:
                results.append(r)
                print(f"OK ({dt:.0f}s) tr={r['trades']} WR={r['win_rate']:.1f}% PF={r['profit_factor']:.2f} "
                      f"ret={r['total_return_pct']:.1f}% sharpe={r['sharpe_ratio']:.2f}")
            else:
                print(f"SKIP ({dt:.0f}s)")
        except Exception as e:
            print(f"ERROR: {e}")

        # 途中保存（毎回CSVに追記）
        if results:
            csv_path_tmp = OUT_DIR / 'aggressive_all60.csv'
            fields = list(results[0].keys())
            with open(csv_path_tmp, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for rr in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                    w.writerow(rr)

    elapsed = time.time() - t0

    # CSV (final)
    csv_path = OUT_DIR / 'aggressive_all60.csv'
    if results:
        fields = list(results[0].keys())
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                w.writerow(r)

    print(f"\n=== Done ({elapsed:.0f}s, {len(results)}/{total} OK) — {csv_path} ===\n")

    # Summary grouped by leverage
    for lev in [1, 3, 7]:
        lr = [r for r in results if r['leverage'] == lev]
        if not lr:
            continue
        print(f"\n--- Leverage {lev}x ---")
        print(f"{'Depth':>5} {'Mode':>4} {'Tr':>4} {'WR%':>6} {'PF':>6} {'Ret%':>9} {'MDD%':>7} {'Sharpe':>6}")
        for r in sorted(lr, key=lambda x: (x['depth'], x['mode'])):
            print(f"{r['depth']:>5} {r['mode']:>4} {r['trades']:>4} {r['win_rate']:>6.1f} "
                  f"{r['profit_factor']:>6.2f} {r['total_return_pct']:>9.1f} {r['max_drawdown_pct']:>7.1f} {r['sharpe_ratio']:>6.2f}")


if __name__ == '__main__':
    main()
