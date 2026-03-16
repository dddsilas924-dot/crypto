"""Top5パターンの四半期別パフォーマンス分析"""
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

logging.basicConfig(level=logging.WARNING)

VAULT = Path(__file__).resolve().parent.parent / "vault"
SCREENING_DIR = VAULT / "screening_results"
RESULTS_DIR = VAULT / "backtest_results"

with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)

PATTERNS = [
    ("P1", "S15", "E18", "T33"),
    ("P2", "S5",  "E20", "T33"),
    ("P3", "S15", "E16", "T33"),
    ("P4", "S15", "E20", "T33"),
    ("P5", "S15", "E18", "T31"),
]

SCREENING_FILES = {
    "S1":  "S1_v1.1_2020-01-06_2026-03-07.csv",
    "S5":  "S5_v1.0_2020-01-06_2026-03-07.csv",
    "S15": "S15_v1.0_2020-01-06_2026-03-07.csv",
}

QUARTERS = [
    "2020Q4", "2021Q1", "2021Q2", "2021Q3", "2021Q4",
    "2022Q1", "2022Q2", "2022Q3", "2022Q4",
    "2023Q1", "2023Q2", "2023Q3", "2023Q4",
    "2024Q1", "2024Q2", "2024Q3", "2024Q4",
    "2025Q1", "2025Q2", "2025Q3", "2025Q4",
    "2026Q1",
]


def quarter_label(date_str):
    dt = pd.Timestamp(date_str)
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{q}"


def run_and_get_trades(s_id, e_id, t_id):
    csv_name = f"trades_top5_{s_id}_{e_id}_{t_id}.csv"
    csv_path = RESULTS_DIR / csv_name
    if csv_path.exists():
        return pd.read_csv(csv_path, encoding="utf-8-sig")

    s_file = SCREENING_FILES[s_id]
    s_df = pd.read_csv(SCREENING_DIR / s_file, encoding="utf-8-sig")
    config = copy.deepcopy(BASE_CONFIG)
    result = run_backtest_from_screening(
        config, VAULT, s_df,
        logic_e=e_id,
        override_trade_logic=t_id,
    )
    if result.trades:
        trades_df = pd.DataFrame([{
            "ticker": t.ticker, "entry_date": t.entry_date,
            "entry_price": t.entry_price, "exit_date": t.exit_date,
            "exit_price": t.exit_price, "exit_reason": t.exit_reason,
            "pnl_pct": t.pnl_pct, "holding_days": t.holding_days,
        } for t in result.trades])
        trades_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return trades_df
    return pd.DataFrame()


def analyze_quarterly(trades_df):
    rows = []
    if trades_df.empty:
        for q in QUARTERS:
            rows.append({"Quarter": q, "Trades": 0, "WR%": "-", "PnL%": 0.0, "AvgWin%": "-", "AvgLoss%": "-"})
        return rows

    trades_df["quarter"] = trades_df["entry_date"].apply(quarter_label)

    for q in QUARTERS:
        qdf = trades_df[trades_df["quarter"] == q]
        n = len(qdf)
        if n == 0:
            rows.append({"Quarter": q, "Trades": 0, "WR%": "-", "PnL%": 0.0, "AvgWin%": "-", "AvgLoss%": "-"})
            continue
        wins = qdf[qdf["pnl_pct"] > 0]
        losses = qdf[qdf["pnl_pct"] <= 0]
        wr = round(len(wins) / n * 100, 1)
        pnl = round(qdf["pnl_pct"].sum(), 2)
        avg_win = round(wins["pnl_pct"].mean(), 2) if len(wins) > 0 else "-"
        avg_loss = round(losses["pnl_pct"].mean(), 2) if len(losses) > 0 else "-"
        rows.append({"Quarter": q, "Trades": n, "WR%": wr, "PnL%": pnl, "AvgWin%": avg_win, "AvgLoss%": avg_loss})

    # Total row
    n = len(trades_df)
    wins = trades_df[trades_df["pnl_pct"] > 0]
    losses = trades_df[trades_df["pnl_pct"] <= 0]
    wr = round(len(wins) / n * 100, 1) if n > 0 else "-"
    pnl = round(trades_df["pnl_pct"].sum(), 2)
    avg_win = round(wins["pnl_pct"].mean(), 2) if len(wins) > 0 else "-"
    avg_loss = round(losses["pnl_pct"].mean(), 2) if len(losses) > 0 else "-"
    rows.append({"Quarter": "TOTAL", "Trades": n, "WR%": wr, "PnL%": pnl, "AvgWin%": avg_win, "AvgLoss%": avg_loss})
    return rows


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════

print("=" * 80)
print("QUARTERLY PERFORMANCE ANALYSIS — TOP 5 PATTERNS")
print("=" * 80)

all_quarterly = {}  # pattern_name -> quarterly rows

for label, s_id, e_id, t_id in PATTERNS:
    name = f"{s_id}×{e_id}×{t_id}"
    print(f"\nRunning {label}: {name}...")
    trades_df = run_and_get_trades(s_id, e_id, t_id)
    print(f"  {len(trades_df)} trades")
    quarterly = analyze_quarterly(trades_df)
    all_quarterly[f"{label}({name})"] = quarterly

    # Print individual table
    print(f"\n### {label}: {name}")
    qdf = pd.DataFrame(quarterly)
    print(qdf.to_string(index=False))

# ═══════════════════════════════════════════════
# Cross-comparison table
# ═══════════════════════════════════════════════

print(f"\n\n{'=' * 100}")
print("QUARTERLY PnL% COMPARISON (横並び)")
print(f"{'=' * 100}")

header = ["Quarter"]
for label, s_id, e_id, t_id in PATTERNS:
    header.append(f"{label}({s_id}{e_id}{t_id})")

rows = []
for i, q in enumerate(QUARTERS + ["TOTAL"]):
    row = {"Quarter": q}
    for pat_key in all_quarterly:
        data = all_quarterly[pat_key]
        if i < len(data):
            row[pat_key] = data[i]["PnL%"]
        else:
            row[pat_key] = 0.0
    rows.append(row)

cross_df = pd.DataFrame(rows)
cross_df.columns = header
print(cross_df.to_string(index=False))

# Save
cross_df.to_csv(RESULTS_DIR / "quarterly_top5_comparison.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: quarterly_top5_comparison.csv")
