"""
派生BOTバックテスト — 全新規BOTを6年分バックテスト
GUI起動中でも別プロセスで実行可能

Usage: python scripts/run_variant_backtest.py
"""
import sys
import csv
import time
import traceback
from pathlib import Path
from copy import deepcopy
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import yaml
from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# ══════════════════════════════════════════════════════════════
# 設定
# ══════════════════════════════════════════════════════════════
START = '2020-03-14'
END   = '2026-03-14'
INITIAL_CAPITAL = 1_000_000
OUT_DIR = Path('vault/backtest_results/variants')
LEVERAGE_GRID = [1, 3, 5, 10]

# ══════════════════════════════════════════════════════════════
# 派生BOT定義
# ══════════════════════════════════════════════════════════════

VARIANT_BOTS = [
    # --- SectorSync NoFear (4 timeframes) ---
    {'key': 'sectorsync_nofear', 'bot_type': 'sectorsync_nofear', 'config_overrides': {'timeframe': '1d'}},
    {'key': 'sectorsync_nofear_3d', 'bot_type': 'sectorsync_nofear_3d', 'config_overrides': {}},
    {'key': 'sectorsync_nofear_1h', 'bot_type': 'sectorsync_nofear_1h', 'config_overrides': {}},
    {'key': 'sectorsync_nofear_1m', 'bot_type': 'sectorsync_nofear_1m', 'config_overrides': {}},

    # --- WeakShort StrongFilter ---
    {'key': 'weakshort_strongfilter', 'bot_type': 'weakshort_strongfilter',
     'config_overrides': {'fear_min': 50, 'fear_max': 75, 'btc_gain_min': 1.0, 'divergence_min': 3.0}},

    # --- MeanRevert-FRArb (HF+MR融合) ---
    {'key': 'meanrevert_frarb', 'bot_type': 'meanrevert_frarb',
     'config_overrides': {'fear_min': 45, 'fear_max': 80, 'ma20_threshold': 12.0,
                          'take_profit_pct': 8.0, 'stop_loss_pct': 3.0}},

    # --- MeanRevert Wide A/B ---
    {'key': 'meanrevert_wide_a', 'bot_type': 'meanrevert_wide',
     'config_overrides': {'variant': 'wide_a', 'take_profit_pct': 9.0, 'stop_loss_pct': 4.0}},
    {'key': 'meanrevert_wide_b', 'bot_type': 'meanrevert_wide',
     'config_overrides': {'variant': 'wide_b', 'take_profit_pct': 12.0, 'stop_loss_pct': 5.0}},

    # --- MeanRevert Strict A/B ---
    {'key': 'meanrevert_strict_a', 'bot_type': 'meanrevert_strict',
     'config_overrides': {'variant': 'strict_a', 'take_profit_pct': 5.0, 'stop_loss_pct': 2.0}},
    {'key': 'meanrevert_strict_b', 'bot_type': 'meanrevert_strict',
     'config_overrides': {'variant': 'strict_b', 'take_profit_pct': 4.0, 'stop_loss_pct': 1.5}},

    # --- Alpha Relaxed (10 variants) ---
    *[{'key': f'alpha_r{i}', 'bot_type': 'alpha_relaxed',
       'config_overrides': {'variant': f'alpha_r{i}',
                            'take_profit_pct': v['tp'], 'stop_loss_pct': v['sl'],
                            'leverage': 3}}
      for i, v in enumerate([
          {'tp': 10, 'sl': 3}, {'tp': 10, 'sl': 3}, {'tp': 12, 'sl': 4},
          {'tp': 10, 'sl': 3}, {'tp': 12, 'sl': 4}, {'tp': 15, 'sl': 5},
          {'tp': 8, 'sl': 2}, {'tp': 15, 'sl': 5}, {'tp': 20, 'sl': 5},
          {'tp': 10, 'sl': 3},
      ], 1)],

    # --- Sniper Improved (3 variants) ---
    {'key': 'sniper_v1', 'bot_type': 'sniper_improved',
     'config_overrides': {'variant': 'sniper_v1', 'fear_max': 30, 'btc_drop_threshold': -3.0,
                          'vol_spike_min': 5.0, 'corr_max': 0.3,
                          'take_profit_pct': 15.0, 'stop_loss_pct': 5.0, 'leverage': 10}},
    {'key': 'sniper_v2', 'bot_type': 'sniper_improved',
     'config_overrides': {'variant': 'sniper_v2', 'fear_max': 30, 'btc_drop_threshold': -3.0,
                          'vol_spike_min': 5.0, 'corr_max': 0.3,
                          'take_profit_pct': 15.0, 'stop_loss_pct': 5.0, 'leverage': 10}},
    {'key': 'sniper_v3', 'bot_type': 'sniper_improved',
     'config_overrides': {'variant': 'sniper_v3', 'fear_max': 30, 'btc_drop_threshold': -3.0,
                          'vol_spike_min': 5.0, 'corr_max': 0.3,
                          'take_profit_pct': 15.0, 'stop_loss_pct': 5.0, 'leverage': 10}},

    # --- Event Wick (2 variants) ---
    {'key': 'event_wick_v1', 'bot_type': 'event_wick',
     'config_overrides': {'variant': 'wick_v1', 'btc_move_threshold': 6.0,
                          'take_profit_pct': 20.0, 'stop_loss_pct': 8.0, 'leverage': 10}},
    {'key': 'event_wick_v2', 'bot_type': 'event_wick',
     'config_overrides': {'variant': 'wick_v2', 'btc_move_threshold': 6.0,
                          'take_profit_pct': 20.0, 'stop_loss_pct': 8.0, 'leverage': 10}},

    # --- GapTrap 20x ---
    {'key': 'gaptrap_20x', 'bot_type': 'gaptrap',
     'config_overrides': {'leverage': 20, 'take_profit_pct': 5.0, 'stop_loss_pct': 3.0,
                          'max_holding_days': 3}},
]


def load_config():
    with open('config/settings.yaml', 'r') as f:
        return yaml.safe_load(f)


def run_single_backtest(db, bot_key, bot_type, config_overrides, leverage):
    """1つのBOT × 1レバレッジのバックテストを実行"""
    config = deepcopy(config_overrides)
    config['leverage'] = leverage
    config.setdefault('take_profit_pct', 8.0)
    config.setdefault('stop_loss_pct', 3.0)
    config.setdefault('position_size_pct', 30)
    config.setdefault('max_holding_days', 14)
    config.setdefault('max_total_positions', 20)

    engine = BacktestEngine(bot_type, config, db)
    try:
        result = engine.run(START, END)
        if 'error' in result:
            return None
        return {
            'key': f'{bot_key}_lev{leverage}',
            'bot_type': bot_type,
            'leverage': leverage,
            'trades': result.get('trades', 0),
            'win_rate': result.get('win_rate', 0),
            'profit_factor': result.get('profit_factor', 0),
            'total_return_pct': result.get('total_return_pct', 0),
            'max_drawdown_pct': result.get('max_drawdown_pct', 0),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'final_capital': result.get('final_capital', INITIAL_CAPITAL),
        }
    except Exception as e:
        print(f"  ERROR {bot_key} lev{leverage}: {e}")
        traceback.print_exc()
        return None


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = HistoricalDB()
    base_config = load_config()
    results = []

    total = len(VARIANT_BOTS) * len(LEVERAGE_GRID)
    done = 0
    t0 = time.time()

    print(f"=== Variant Backtest Start ===")
    print(f"  Bots: {len(VARIANT_BOTS)} | Leverage Grid: {LEVERAGE_GRID} | Total: {total}")
    print(f"  Period: {START} ~ {END}")
    print()

    for bot_def in VARIANT_BOTS:
        bot_key = bot_def['key']
        bot_type = bot_def['bot_type']
        overrides = bot_def['config_overrides']

        for lev in LEVERAGE_GRID:
            done += 1
            tag = f'[{done}/{total}]'
            print(f"{tag} {bot_key} lev{lev} ... ", end='', flush=True)

            result = run_single_backtest(db, bot_key, bot_type, overrides, lev)
            if result:
                results.append(result)
                wr = result['win_rate']
                ret = result['total_return_pct']
                sr = result['sharpe_ratio']
                print(f"OK  trades={result['trades']}  WR={wr:.1f}%  ret={ret:.1f}%  sharpe={sr:.2f}")
            else:
                print("SKIP/ERROR")

    elapsed = time.time() - t0

    # CSV出力
    csv_path = OUT_DIR / 'variant_summary.csv'
    if results:
        fields = ['key', 'bot_type', 'leverage', 'trades', 'win_rate', 'profit_factor',
                  'total_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'final_capital']
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                w.writerow(r)

    # サマリー表示
    print()
    print(f"=== Variant Backtest Complete ({elapsed:.0f}s) ===")
    print(f"  Results: {len(results)} / {total}")
    print(f"  Output: {csv_path}")

    if results:
        # Top 10
        top = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)[:10]
        print()
        print("  Top 10 by Sharpe:")
        print(f"  {'Key':<30} {'Lev':>4} {'Trades':>6} {'WR%':>6} {'PF':>6} {'Return%':>10} {'MDD%':>8} {'Sharpe':>7}")
        for r in top:
            print(f"  {r['key']:<30} {r['leverage']:>4}x {r['trades']:>6} {r['win_rate']:>6.1f} "
                  f"{r['profit_factor']:>6.2f} {r['total_return_pct']:>10.1f} "
                  f"{r['max_drawdown_pct']:>8.1f} {r['sharpe_ratio']:>7.2f}")


if __name__ == '__main__':
    main()
