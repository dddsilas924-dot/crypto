"""大規模グリッドサーチ: S系×E系×T系"""
import copy
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_engine.backtest_runner import run_backtest_from_screening
from trading_engine.core.config_loader import resolve_logic_path
from trading_engine.core.logic_parser import parse_logic_file

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

VAULT = Path(__file__).resolve().parent.parent / "vault"
SCREENING_DIR = VAULT / "screening_results"
RESULTS_DIR = VAULT / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)


def get_pos_pct(t_id):
    logics_dir = VAULT / "logics"
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    pos_sizing = t_parsed["blocks"].get("position_sizing", {})
    return float(pos_sizing.get("value", 100))


def run_one(s_id, e_id, t_id, screening_df):
    config = copy.deepcopy(BASE_CONFIG)
    pos_pct = get_pos_pct(t_id)
    try:
        result = run_backtest_from_screening(
            config, VAULT, screening_df,
            logic_e=e_id,
            override_trade_logic=t_id,
        )
        trades = result.trades
        worst_pnl = min(t.pnl_pct for t in trades) if trades else 0
        max_single_dd = worst_pnl * (pos_pct / 100)
        return {
            "S": s_id, "E": e_id, "T": t_id,
            "Trades": result.total_trades,
            "WR%": round(result.win_rate, 1),
            "PF": round(result.profit_factor, 2),
            "Return%": round(result.total_return_pct, 1),
            "MDD%": round(result.max_drawdown_pct, 1),
            "MaxSingleDD%": round(max_single_dd, 2),
            "AvgPnL%": round(result.avg_pnl_pct, 2),
        }
    except Exception as e:
        return {
            "S": s_id, "E": e_id, "T": t_id,
            "Trades": 0, "WR%": 0, "PF": 0, "Return%": 0,
            "MDD%": 0, "MaxSingleDD%": 0, "AvgPnL%": 0,
        }


# Load screening data
SCREENING_FILES = {
    "S1": "S1_v1.1_2020-01-06_2026-03-07.csv",
    "S5": "S5_v1.0_2020-01-06_2026-03-07.csv",
    "S15": "S15_v1.0_2020-01-06_2026-03-07.csv",
    "S20": "S20_v1.0_2020-01-06_2026-03-07.csv",
    "S21": "S21_v1.0_2020-01-06_2026-03-07.csv",
    "S22": "S22_v1.0_2020-01-06_2026-03-07.csv",
    "S31": "S31_v1.0_2020-01-06_2026-03-07.csv",
}

screening_cache = {}
for s_id, fname in SCREENING_FILES.items():
    path = SCREENING_DIR / fname
    if path.exists():
        screening_cache[s_id] = pd.read_csv(path, encoding="utf-8-sig")
    else:
        print(f"WARNING: {fname} not found, skipping {s_id}")

print("=" * 80)
print("GRID SEARCH: S x E x T")
print("=" * 80)
for s_id, df in screening_cache.items():
    print(f"  {s_id}: {len(df)} hits")

# ═══════════════════════════════════════════════
# Stage 1: E系スクリーニング (S1 × 12 E × T31)
# ═══════════════════════════════════════════════

ALL_E = ["E1", "E10", "E16", "E18", "E19", "E20", "E21", "E30", "E31", "E32", "E33", "E34"]

print(f"\n{'=' * 80}")
print("STAGE 1: E系スクリーニング (S1 × 12E × T31)")
print(f"{'=' * 80}")

s1_df = screening_cache["S1"]
stage1_results = []

for i, e_id in enumerate(ALL_E):
    print(f"  [{i+1}/{len(ALL_E)}] S1 × {e_id} × T31")
    r = run_one("S1", e_id, "T31", s1_df)
    stage1_results.append(r)

stage1_df = pd.DataFrame(stage1_results)
print(f"\n{'=' * 80}")
print("STAGE 1 RESULTS (S1 × E × T31, PF降順)")
print(f"{'=' * 80}")
stage1_sorted = stage1_df.sort_values("PF", ascending=False)
stage1_sorted["Selected"] = ""
# Select top 5 by PF (with Trades >= 5)
eligible = stage1_sorted[stage1_sorted["Trades"] >= 5]
top5_e = eligible.head(5)["E"].tolist()
stage1_sorted.loc[stage1_sorted["E"].isin(top5_e), "Selected"] = "***"
print(stage1_sorted[["E", "Trades", "WR%", "PF", "Return%", "MDD%", "AvgPnL%", "Selected"]].to_string(index=False))
print(f"\nTop 5 E系 selected: {top5_e}")

stage1_df.to_csv(RESULTS_DIR / "grid_stage1.csv", index=False, encoding="utf-8-sig")

# ═══════════════════════════════════════════════
# Stage 2: フルグリッド (Selected S × Top5 E × T30-T33)
# ═══════════════════════════════════════════════

S_LIST = list(screening_cache.keys())  # 7 S systems
T_LIST = ["T30", "T31", "T32", "T33"]

total = len(S_LIST) * len(top5_e) * len(T_LIST)
print(f"\n{'=' * 80}")
print(f"STAGE 2: フルグリッド ({len(S_LIST)}S × {len(top5_e)}E × {len(T_LIST)}T = {total} patterns)")
print(f"{'=' * 80}")

stage2_results = []
count = 0
for s_id in S_LIST:
    s_df = screening_cache[s_id]
    for e_id in top5_e:
        for t_id in T_LIST:
            count += 1
            if count % 10 == 0 or count == total:
                print(f"  [{count}/{total}] {s_id} × {e_id} × {t_id}")
            r = run_one(s_id, e_id, t_id, s_df)
            stage2_results.append(r)

stage2_df = pd.DataFrame(stage2_results)
# Filter out patterns with < 5 trades
stage2_valid = stage2_df[stage2_df["Trades"] >= 5].copy()
print(f"\nTotal patterns: {len(stage2_df)}, Valid (>=5 trades): {len(stage2_valid)}")

# Save all results
stage2_df.to_csv(RESULTS_DIR / "grid_stage2_all.csv", index=False, encoding="utf-8-sig")

# ═══════════════════════════════════════════════
# Results
# ═══════════════════════════════════════════════

# Top 30 by PF
print(f"\n{'=' * 100}")
print("TOP 30 BY PF (Trades >= 5)")
print(f"{'=' * 100}")
pf_top = stage2_valid.sort_values("PF", ascending=False).head(30).reset_index(drop=True)
pf_top.index = pf_top.index + 1
pf_top.index.name = "Rank"
print(pf_top[["S", "E", "T", "Trades", "WR%", "PF", "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%"]].to_string())

# Top 30 by Return%
print(f"\n{'=' * 100}")
print("TOP 30 BY RETURN% (Trades >= 5)")
print(f"{'=' * 100}")
ret_top = stage2_valid.sort_values("Return%", ascending=False).head(30).reset_index(drop=True)
ret_top.index = ret_top.index + 1
ret_top.index.name = "Rank"
print(ret_top[["S", "E", "T", "Trades", "WR%", "PF", "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%"]].to_string())

# Top 5 by composite score (PF × Return%)
print(f"\n{'=' * 100}")
print("TOP 5 BY COMPOSITE SCORE (PF × Return%, Trades >= 5, Return > 0)")
print(f"{'=' * 100}")
scored = stage2_valid[stage2_valid["Return%"] > 0].copy()
scored["Score"] = scored["PF"] * scored["Return%"]
score_top = scored.sort_values("Score", ascending=False).head(5).reset_index(drop=True)
score_top.index = score_top.index + 1
score_top.index.name = "Rank"
print(score_top[["S", "E", "T", "Trades", "WR%", "PF", "Return%", "MDD%", "MaxSingleDD%", "Score"]].to_string())

score_top.to_csv(RESULTS_DIR / "grid_top5.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: grid_stage1.csv, grid_stage2_all.csv, grid_top5.csv")
