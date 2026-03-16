"""
LevBurn-Evolved バックテスト — 追加ロジック組み合わせ検証
Base: levburn_sec_agg_7x_fr (Sharpe 5.97)

追加候補の組み合わせを網羅:
  oi_classify    : OI方向分類
  slip_filter    : 滑りやすさ係数
  weakshort_mix  : WeakShort統合
  multi_confirm  : 過熱多重確認
  meta_variant   : メタvariant切替

2年間BT (2024-03-14 ~ 2026-03-14)
"""
import sys
import csv
import time
import traceback
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

START = '2024-03-14'
END = '2026-03-14'
OUT_DIR = Path('vault/backtest_results/variants')

# 全追加候補
ALL_FEATURES = ['oi_classify', 'slip_filter', 'weakshort_mix', 'multi_confirm', 'meta_variant']

# テスト構成: 単体 + 2個組み合わせ + 3個組み合わせ + フルスタック + ベース
CONFIGS = []

# 0. ベース（追加なし = 7x_fr相当）
CONFIGS.append({'key': 'base_7x_fr', 'features': [], 'label': 'Base (7x FR filter)'})

# 1. 単体追加（5パターン）
for f in ALL_FEATURES:
    CONFIGS.append({'key': f'add_{f}', 'features': [f], 'label': f'+{f}'})

# 2. 2個組み合わせ（10パターン）
for combo in combinations(ALL_FEATURES, 2):
    key = '+'.join(combo)
    CONFIGS.append({'key': f'add_{key}', 'features': list(combo), 'label': f'+{"+".join(combo)}'})

# 3. 有望な3個組み合わせ（厳選5パターン）
triple_combos = [
    ['oi_classify', 'multi_confirm', 'slip_filter'],
    ['oi_classify', 'weakshort_mix', 'multi_confirm'],
    ['oi_classify', 'slip_filter', 'weakshort_mix'],
    ['multi_confirm', 'slip_filter', 'weakshort_mix'],
    ['oi_classify', 'multi_confirm', 'meta_variant'],
]
for combo in triple_combos:
    key = '+'.join(combo)
    CONFIGS.append({'key': f'add_{key}', 'features': combo, 'label': f'+{"+".join(combo)}'})

# 4. フルスタック
CONFIGS.append({'key': 'full_stack', 'features': ALL_FEATURES, 'label': 'Full Stack (all 5)'})

# 5. OI strict mode（焼かれた後を完全スキップ）
CONFIGS.append({'key': 'oi_strict', 'features': ['oi_classify'], 'extra': {'oi_strict': True}, 'label': '+oi_classify (strict)'})

# 6. multi_confirm 3確認必須
CONFIGS.append({'key': 'multi_3conf', 'features': ['multi_confirm'], 'extra': {'min_confirmations': 3}, 'label': '+multi_confirm (3確認)'})

# 7. OI strict + multi 3確認
CONFIGS.append({'key': 'oi_strict_multi3', 'features': ['oi_classify', 'multi_confirm'], 'extra': {'oi_strict': True, 'min_confirmations': 3}, 'label': '+oi_strict+multi3'})

# 8. slip厳格（slip_max=1.5）
CONFIGS.append({'key': 'slip_tight', 'features': ['slip_filter'], 'extra': {'slip_max': 1.5}, 'label': '+slip (tight 1.5)'})

print(f"Total configs: {len(CONFIGS)}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = HistoricalDB()
    results = []
    total = len(CONFIGS)
    t0 = time.time()

    print(f"=== LevBurn-Evolved BT ({total} configs, {START}~{END}) ===\n")

    for i, cfg in enumerate(CONFIGS, 1):
        print(f"[{i}/{total}] {cfg['key']} ({cfg['label']}) ... ", end='', flush=True)

        bot_cfg = {
            'leverage': 7,
            'take_profit_pct': 3.0,
            'stop_loss_pct': 1.0,
            'position_size_pct': 30,
            'max_holding_days': 14,
            'max_total_positions': 20,
            'fr_threshold': 0.3,
            'vol_threshold': 3.0,
            'fr_direction_filter': True,  # FR filter ON
            'evolve_features': cfg['features'],
        }
        # Extra overrides
        if 'extra' in cfg:
            bot_cfg.update(cfg['extra'])

        engine = BacktestEngine('levburn_evolved', bot_cfg, db)
        try:
            t1 = time.time()
            result = engine.run(START, END)
            dt = time.time() - t1

            if 'error' in result:
                print(f"SKIP ({dt:.0f}s): {result['error']}")
                continue

            trades = result.get('trades', 0)
            if isinstance(trades, list):
                trades = len(trades)

            r = {
                'key': cfg['key'],
                'label': cfg['label'],
                'features': ','.join(cfg['features']) if cfg['features'] else 'none',
                'trades': trades,
                'win_rate': result.get('win_rate', 0),
                'profit_factor': result.get('profit_factor', 0),
                'total_return_pct': result.get('total_return_pct', 0),
                'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                'sharpe_ratio': result.get('sharpe_ratio', 0),
                'final_capital': result.get('final_capital', 1000000),
            }
            results.append(r)
            print(f"OK ({dt:.0f}s) tr={r['trades']} WR={r['win_rate']:.1f}% PF={r['profit_factor']:.2f} "
                  f"ret={r['total_return_pct']:.1f}% sharpe={r['sharpe_ratio']:.2f}")

        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()

        # 途中保存
        if results:
            csv_path = OUT_DIR / 'evolved_bt.csv'
            fields = list(results[0].keys())
            with open(csv_path, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for rr in sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True):
                    w.writerow(rr)

    elapsed = time.time() - t0
    print(f"\n=== Done ({elapsed:.0f}s, {len(results)}/{total} OK) ===\n")

    # Summary
    print(f"{'#':>2} {'Key':<35} {'Features':<45} {'Tr':>4} {'WR%':>6} {'PF':>6} {'Ret%':>9} {'MDD%':>7} {'Sha':>6}")
    print('=' * 125)
    for idx, r in enumerate(sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True), 1):
        feats = r['features'][:40] if len(r['features']) > 40 else r['features']
        print(f"{idx:>2} {r['key']:<35} {feats:<45} {r['trades']:>4} {r['win_rate']:>6.1f} "
              f"{r['profit_factor']:>6.2f} {r['total_return_pct']:>9.1f} {r['max_drawdown_pct']:>7.1f} {r['sharpe_ratio']:>6.2f}")


if __name__ == '__main__':
    main()
