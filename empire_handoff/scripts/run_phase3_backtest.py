"""Phase 3: Top3 S×T × 5 E = 15パターン バックテスト"""
import copy
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_engine.backtest_runner import run_backtest_from_screening
from trading_engine.core.config_loader import resolve_logic_path
from trading_engine.core.logic_parser import parse_logic_file

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

VAULT = Path(__file__).resolve().parent.parent / "vault"

with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)

SCREENING_FILES = {
    "S1": VAULT / "screening_results" / "S1_v1.1_2020-01-06_2026-03-07.csv",
    "S15": VAULT / "screening_results" / "S15_v1.0_2020-01-06_2026-03-07.csv",
}

# Top 3 from Phase 2
ST_COMBOS = [
    ("S1", "T14"),   # Return 157.9%
    ("S15", "T12"),  # Return 93.0%
    ("S1", "T11"),   # Return 91.7%
]

E_VARIANTS = ["E1", "E16", "E10", "E18", "E19"]

logics_dir = VAULT / "logics"
results = []
total = len(ST_COMBOS) * len(E_VARIANTS)
done = 0

for s_id, t_id in ST_COMBOS:
    csv_path = SCREENING_FILES[s_id]
    screening_df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # Get position_pct for this T
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    pos_sizing = t_parsed["blocks"].get("position_sizing", {})
    pos_pct = float(pos_sizing.get("value", 100))

    for e_id in E_VARIANTS:
        done += 1
        config = copy.deepcopy(BASE_CONFIG)
        try:
            result = run_backtest_from_screening(
                config, VAULT, screening_df,
                logic_e=e_id,
                override_trade_logic=t_id,
            )

            trades = result.trades
            if trades:
                worst_pnl = min(t.pnl_pct for t in trades)
                max_single_dd = worst_pnl * (pos_pct / 100)
            else:
                worst_pnl = 0
                max_single_dd = 0

            row = {
                "S": s_id, "E": e_id, "T": t_id,
                "pos_pct": pos_pct,
                "Trades": result.total_trades,
                "WR%": round(result.win_rate, 1),
                "PF": round(result.profit_factor, 2),
                "Return%": round(result.total_return_pct, 1),
                "MDD%": round(result.max_drawdown_pct, 1),
                "MaxSingleDD%": round(max_single_dd, 2),
                "AvgPnL%": round(result.avg_pnl_pct, 2),
            }
            results.append(row)
            print(f"[{done}/{total}] {s_id}×{e_id}×{t_id}: Ret={row['Return%']}%, PF={row['PF']}, Trades={row['Trades']}")

        except Exception as e:
            print(f"[{done}/{total}] {s_id}×{e_id}×{t_id}: ERROR - {e}")
            results.append({
                "S": s_id, "E": e_id, "T": t_id,
                "pos_pct": pos_pct, "Trades": 0, "WR%": 0, "PF": 0,
                "Return%": 0, "MDD%": 0, "MaxSingleDD%": 0, "AvgPnL%": 0,
            })

df = pd.DataFrame(results)
df_sorted = df.sort_values("Return%", ascending=False).reset_index(drop=True)
df_sorted.index = df_sorted.index + 1
df_sorted.index.name = "Rank"

print(f"\n\n{'='*100}")
print("PHASE 3 RESULTS: Top3 S×T × 5 E = 15 patterns (sorted by Return%)")
print(f"{'='*100}")
print(df_sorted.to_string())

out_path = VAULT / "backtest_results" / "phase3_entry_optimize.csv"
df_sorted.to_csv(out_path, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")
