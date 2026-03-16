"""Phase 2: 8 Exit × 5 S×E = 40パターン バックテスト（リターン最大化探索）"""
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
    "S5": VAULT / "screening_results" / "S5_v1.0_2020-01-06_2026-03-07.csv",
    "S10": VAULT / "screening_results" / "S10_v1.0_2020-01-06_2026-03-07.csv",
    "S12": VAULT / "screening_results" / "S12_v1.0_2020-01-06_2026-03-07.csv",
    "S15": VAULT / "screening_results" / "S15_v1.0_2020-01-06_2026-03-07.csv",
}

COMBOS = [
    ("S1", "E16"),
    ("S10", "E16"),
    ("S15", "E16"),
    ("S12", "E16"),
    ("S5", "E16"),
]

T_VARIANTS = ["T4", "T7", "T9", "T10", "T11", "T12", "T13", "T14"]

logics_dir = VAULT / "logics"
results = []
total = len(COMBOS) * len(T_VARIANTS)
done = 0

for s_id, e_id in COMBOS:
    csv_path = SCREENING_FILES[s_id]
    screening_df = pd.read_csv(csv_path, encoding="utf-8-sig")

    for t_id in T_VARIANTS:
        done += 1
        config = copy.deepcopy(BASE_CONFIG)
        try:
            result = run_backtest_from_screening(
                config, VAULT, screening_df,
                logic_e=e_id,
                override_trade_logic=t_id,
            )

            # Get position_pct
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
                "pos_pct": 0, "Trades": 0, "WR%": 0, "PF": 0,
                "Return%": 0, "MDD%": 0, "MaxSingleDD%": 0, "AvgPnL%": 0,
            })

df = pd.DataFrame(results)
df_sorted = df.sort_values("Return%", ascending=False).reset_index(drop=True)
df_sorted.index = df_sorted.index + 1
df_sorted.index.name = "Rank"

print(f"\n\n{'='*100}")
print("PHASE 2 RESULTS: 8T × 5 S×E = 40 patterns (sorted by Return%)")
print(f"{'='*100}")
print(df_sorted.to_string())

out_path = VAULT / "backtest_results" / "phase2_return_maximize.csv"
df_sorted.to_csv(out_path, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")

# Top 3 S×T combos
print(f"\n{'='*60}")
print("TOP 3 S×T combinations (for Phase 3)")
print(f"{'='*60}")
for i in range(min(3, len(df_sorted))):
    r = df_sorted.iloc[i]
    print(f"  #{i+1}: {r['S']}×{r['T']} (Return={r['Return%']}%, PF={r['PF']})")
