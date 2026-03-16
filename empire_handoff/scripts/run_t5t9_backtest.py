"""T4-T9 × 3 S×E combos = 18パターン バックテスト"""
import copy
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_engine.backtest_runner import run_backtest_from_screening, compute_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

VAULT = Path(__file__).resolve().parent.parent / "vault"

# Load config
with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)

# Screening files (full period)
SCREENING_FILES = {
    "S1": VAULT / "screening_results" / "S1_v1.1_2020-01-06_2026-03-07.csv",
    "S5": VAULT / "screening_results" / "S5_v1.0_2020-01-06_2026-03-07.csv",
    "S10": VAULT / "screening_results" / "S10_v1.0_2020-01-06_2026-03-07.csv",
}

COMBOS = [
    ("S1", "E16"),
    ("S10", "E16"),
    ("S5", "E16"),
]

T_VARIANTS = ["T4", "T5", "T6", "T7", "T8", "T9"]

results = []

for s_id, e_id in COMBOS:
    csv_path = SCREENING_FILES[s_id]
    screening_df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"\n{'='*60}")
    print(f"Combo: {s_id} × {e_id} ({len(screening_df)} screening hits)")
    print(f"{'='*60}")

    for t_id in T_VARIANTS:
        config = copy.deepcopy(BASE_CONFIG)
        try:
            result = run_backtest_from_screening(
                config, VAULT, screening_df,
                logic_e=e_id,
                override_trade_logic=t_id,
            )

            # Calculate MaxSingleDD% (worst single trade loss × position_pct)
            # Position pct is already factored into compute_summary for cumulative,
            # but we need raw pnl_pct for MaxSingleDD calculation
            from trading_engine.core.config_loader import resolve_logic_path
            from trading_engine.core.logic_parser import parse_logic_file
            logics_dir = VAULT / "logics"
            t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
            t_parsed = parse_logic_file(t_path)
            pos_sizing = t_parsed["blocks"].get("position_sizing", {})
            pos_pct = float(pos_sizing.get("value", 100))

            trades = result.trades
            if trades:
                worst_pnl = min(t.pnl_pct for t in trades)
                max_single_dd = worst_pnl * (pos_pct / 100)
            else:
                worst_pnl = 0
                max_single_dd = 0

            row = {
                "combo": f"{s_id}×{e_id}",
                "T": t_id,
                "pos_pct": pos_pct,
                "trades": result.total_trades,
                "WR%": round(result.win_rate, 1),
                "PF": round(result.profit_factor, 2),
                "TotalRet%": round(result.total_return_pct, 1),
                "MDD%": round(result.max_drawdown_pct, 1),
                "AvgPnl%": round(result.avg_pnl_pct, 2),
                "AvgHold": round(result.avg_holding_days, 1),
                "WorstTrade%": round(worst_pnl, 2),
                "MaxSingleDD%": round(max_single_dd, 2),
                "MDD_meets_3pct": "YES" if abs(max_single_dd) <= 3.0 else "NO",
            }
            results.append(row)
            print(f"  {t_id}: PF={row['PF']}, WR={row['WR%']}%, Trades={row['trades']}, "
                  f"MDD={row['MDD%']}%, MaxSingleDD={row['MaxSingleDD%']}%")

        except Exception as e:
            print(f"  {t_id}: ERROR - {e}")
            results.append({
                "combo": f"{s_id}×{e_id}", "T": t_id, "pos_pct": 0,
                "trades": 0, "WR%": 0, "PF": 0, "TotalRet%": 0,
                "MDD%": 0, "AvgPnl%": 0, "AvgHold": 0,
                "WorstTrade%": 0, "MaxSingleDD%": 0, "MDD_meets_3pct": "ERR",
            })

# Output
df = pd.DataFrame(results)
print(f"\n\n{'='*80}")
print("FULL COMPARISON TABLE: T4-T9 × 3 S×E combos")
print(f"{'='*80}")
print(df.to_string(index=False))

out_path = VAULT / "backtest_results" / "t5t9_comparison.csv"
df.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")
