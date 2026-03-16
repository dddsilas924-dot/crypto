"""Task 1: ポジションキャップ感度分析

対象: Surge, MeanRevert, WeakShort
max_position_jpy: 300万, 500万, 1000万, None (キャップなし)
leverage: 3x固定
"""
import sys
import copy
import yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine


def safe_pf(r):
    pf = r.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start, end = '2024-01-01', '2026-03-01'

    BOTS = ['surge', 'meanrevert', 'weakshort']
    BOT_LABELS = {'surge': 'Surge', 'meanrevert': 'MeanRevert', 'weakshort': 'WeakShort'}
    CAPS = [
        ('300万', 3_000_000),
        ('500万', 5_000_000),
        ('1000万', 10_000_000),
        ('なし', None),
    ]

    print("=" * 120)
    print("  ポジションキャップ感度分析  lev=3x  期間: 2024-01-01〜2026-03-01")
    print("=" * 120)
    print(f"  {'Bot':>12s} {'Cap':>8s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>12s} {'MDD':>8s} {'Sharpe':>8s} {'MaxSim':>7s} {'Skip':>5s} {'Final':>14s} {'判定'}")
    print(f"  {'─' * 116}")

    all_results = {}

    for bot in BOTS:
        label = BOT_LABELS[bot]
        base_config = config.get(f'bot_{bot}', {})
        bot_results = []

        for cap_label, cap_val in CAPS:
            cfg = copy.deepcopy(base_config)
            cfg['leverage'] = 3
            if cap_val is not None:
                cfg['max_position_jpy'] = cap_val
            else:
                # キャップなし = max_position_pctも外す
                cfg.pop('max_position_jpy', None)
                cfg['max_position_pct'] = 100

            engine = BacktestEngine(bot, cfg, db)
            r = engine.run(start, end)

            trades = r.get('total_trades', 0)
            wr = r.get('win_rate', 0)
            pf = safe_pf(r)
            ret = r.get('total_return_pct', 0)
            mdd = r.get('max_drawdown_pct', 0)
            sharpe = r.get('sharpe_ratio', 0)
            max_sim = r.get('max_simultaneous', 0)
            skip = r.get('skipped_count', 0)
            final = r.get('final_capital', 0)
            min_cap = r.get('min_capital', 1_000_000)

            pf_str = f"{pf:.2f}" if pf < 999 else "inf"

            # 判定ロジック
            # キャップ変えてもPF/WR/Tradesが変わらない = ロジック健全
            # PFが大幅に変わる or MDDが-20%超 = 要注意
            if mdd < -20:
                verdict = "⚠MDD大"
            elif min_cap <= 0:
                verdict = "⚠破産"
            else:
                verdict = "✓"

            print(f"  {label:>12s} {cap_label:>8s} {trades:7d} {wr:5.1f}% {pf_str:>7s} {ret:+11.1f}% {mdd:7.1f}% {sharpe:8.2f} {max_sim:>7d} {skip:>5d} {final:>14,.0f} {verdict}")

            bot_results.append({
                'cap_label': cap_label, 'cap_val': cap_val,
                'trades': trades, 'wr': wr, 'pf': pf,
                'ret': ret, 'mdd': mdd, 'sharpe': sharpe,
                'max_sim': max_sim, 'skip': skip, 'final': final,
                'min_cap': min_cap,
            })

        all_results[bot] = bot_results
        print(f"  {'─' * 116}")

    # 健全性判定サマリー
    print(f"\n{'=' * 80}")
    print("  健全性判定サマリー")
    print(f"{'=' * 80}")

    for bot in BOTS:
        label = BOT_LABELS[bot]
        results = all_results[bot]
        pfs = [r['pf'] for r in results]
        wrs = [r['wr'] for r in results]
        trades_list = [r['trades'] for r in results]

        # PFの変動幅
        pf_range = max(pfs) - min(pfs) if pfs else 0
        wr_range = max(wrs) - min(wrs) if wrs else 0
        trades_same = len(set(trades_list)) == 1

        # MDD全て-20%以内か
        mdd_ok = all(r['mdd'] > -20 for r in results)
        # 破産なしか
        no_bankrupt = all(r['min_cap'] > 0 for r in results)

        if trades_same and pf_range < 0.1 and mdd_ok and no_bankrupt:
            verdict = "ロジック健全 ✓✓"
            reason = f"全Cap同一トレード数, PF変動<0.1, MDD安全"
        elif trades_same and pf_range < 0.5 and mdd_ok:
            verdict = "概ね健全 ✓"
            reason = f"PF変動={pf_range:.2f}"
        elif not mdd_ok:
            verdict = "要注意 ⚠"
            reason = f"一部CAPでMDD>-20%"
        elif not no_bankrupt:
            verdict = "危険 ⚠⚠"
            reason = "破産リスクあり"
        else:
            verdict = "要検討"
            reason = f"PF変動={pf_range:.2f}, WR変動={wr_range:.1f}%"

        print(f"  {label:>12s}: {verdict}  ({reason})")


if __name__ == "__main__":
    main()
