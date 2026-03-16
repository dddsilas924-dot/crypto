"""Final Top 10 across Phase 2 + Phase 3"""
import pandas as pd
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / "vault"

p2 = pd.read_csv(VAULT / "backtest_results" / "phase2_return_maximize.csv", encoding="utf-8-sig")
p3 = pd.read_csv(VAULT / "backtest_results" / "phase3_entry_optimize.csv", encoding="utf-8-sig")

# Phase 2 has E=E16 for all, Phase 3 has various E
# Combine, deduplicate by S+E+T, keep the one with better data
combined = pd.concat([p2, p3], ignore_index=True)
combined = combined.drop_duplicates(subset=["S", "E", "T"], keep="last")
combined = combined.sort_values("Return%", ascending=False).reset_index(drop=True)
combined.index = combined.index + 1
combined.index.name = "Rank"

print("=" * 110)
print("FINAL TOP 10: S×E×T Return% Ranking (All Patterns)")
print("=" * 110)
top10 = combined.head(10)
print(top10[["S", "E", "T", "Trades", "WR%", "PF", "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%"]].to_string())

print("\n" + "=" * 110)
print("FULL RANKING (55 patterns)")
print("=" * 110)
print(combined[["S", "E", "T", "Trades", "WR%", "PF", "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%"]].to_string())

out_path = VAULT / "backtest_results" / "final_all_patterns.csv"
combined.to_csv(out_path, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")
