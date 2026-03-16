"""全好成績パターンの四半期別分析+2025Q2依存度+損益分布+連敗分析+銘柄集中度"""
import copy
import logging
import sys
from pathlib import Path
from collections import Counter

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
    ("P01_ベースライン",    "S1",  "E16", "T6"),
    ("P02_B2bベスト",       "S21", "E16", "T21"),
    ("P03_B1ベスト",        "S20", "E20", "T20"),
    ("P04_リターン王",      "S1",  "E16", "T14"),
    ("P05_品質王",          "S15", "E18", "T12"),
    ("P06_S10ベスト",       "S10", "E16", "T6"),
    ("P07_S12ベスト",       "S12", "E16", "T6"),
    ("P08_安全版チャンプ",  "S15", "E18", "T32"),
    ("P09_E16T7",           "S1",  "E16", "T7"),
    ("P10_S5多取引",        "S5",  "E16", "T31"),
]

SCREENING_FILES = {
    "S1":  "S1_v1.1_2020-01-06_2026-03-07.csv",
    "S5":  "S5_v1.0_2020-01-06_2026-03-07.csv",
    "S10": "S10_v1.0_2020-01-06_2026-03-07.csv",
    "S12": "S12_v1.0_2020-01-06_2026-03-07.csv",
    "S15": "S15_v1.0_2020-01-06_2026-03-07.csv",
    "S20": "S20_v1.0_2020-01-06_2026-03-07.csv",
    "S21": "S21_v1.0_2020-01-06_2026-03-07.csv",
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


def get_pos_pct(t_id):
    logics_dir = VAULT / "logics"
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    pos_sizing = t_parsed["blocks"].get("position_sizing", {})
    return float(pos_sizing.get("value", 100))


def run_and_get_trades(name, s_id, e_id, t_id):
    safe_name = name.replace("/", "_").replace("\\", "_")
    csv_path = RESULTS_DIR / f"trades_full_{safe_name}.csv"
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
    pd.DataFrame().to_csv(csv_path, index=False, encoding="utf-8-sig")
    return pd.DataFrame()


def max_consecutive(series, target):
    """Max consecutive True/False runs."""
    max_run = 0
    current = 0
    for v in series:
        if v == target:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def analyze_pattern(name, s_id, e_id, t_id):
    print(f"\n{'=' * 70}")
    print(f"  {name}: {s_id} × {e_id} × {t_id}")
    print(f"{'=' * 70}")

    trades_df = run_and_get_trades(name, s_id, e_id, t_id)
    pos_pct = get_pos_pct(t_id)

    if trades_df.empty or len(trades_df) == 0:
        print("  No trades.")
        return {
            "Pattern": name, "S": s_id, "E": e_id, "T": t_id,
            "Trades": 0, "PF": 0, "Return%": 0,
            "2025Q2_PnL%": 0, "ExQ2_Return%": 0, "依存度%": 0,
            "MaxConsecLoss": 0, "MaxConsecWin": 0,
            "UniqueTickers": 0, "ExTop3_Return%": 0,
        }

    trades_df["quarter"] = trades_df["entry_date"].apply(quarter_label)
    trades_df["win"] = trades_df["pnl_pct"] > 0

    # === A) 四半期別PnL%テーブル ===
    print("\n  A) 四半期別パフォーマンス")
    print(f"  {'Quarter':<10} {'Trades':>6} {'PnL%':>8}")
    print(f"  {'-'*10} {'-'*6} {'-'*8}")
    q_pnl = {}
    for q in QUARTERS:
        qdf = trades_df[trades_df["quarter"] == q]
        n = len(qdf)
        pnl = round(qdf["pnl_pct"].sum(), 2) if n > 0 else 0.0
        q_pnl[q] = pnl
        print(f"  {q:<10} {n:>6} {pnl:>8.2f}")
    total_pnl = round(trades_df["pnl_pct"].sum(), 2)
    print(f"  {'TOTAL':<10} {len(trades_df):>6} {total_pnl:>8.2f}")

    # === B) 2025Q2依存度 ===
    q2_pnl = q_pnl.get("2025Q2", 0.0)
    # Return% uses position_pct weighted cumulative, but for simplicity use sum of pnl_pct
    # For dependency analysis, raw pnl sum is more meaningful
    ex_q2_pnl = round(total_pnl - q2_pnl, 2)
    dep_pct = round(q2_pnl / total_pnl * 100, 1) if total_pnl != 0 else 0.0

    print(f"\n  B) 2025Q2依存度")
    print(f"     2025Q2 PnL%:        {q2_pnl:+.2f}")
    print(f"     全期間 合計PnL%:     {total_pnl:+.2f}")
    print(f"     Q2除外 合計PnL%:     {ex_q2_pnl:+.2f}")
    print(f"     依存度:              {dep_pct:.1f}%")

    # === C) トレード損益分布 ===
    sorted_pnl = trades_df.sort_values("pnl_pct", ascending=False)
    print(f"\n  C) トレード損益分布")
    print(f"     上位5件:")
    for _, r in sorted_pnl.head(5).iterrows():
        print(f"       {r['ticker']:<8} {r['entry_date']}  {r['pnl_pct']:+.2f}%")
    print(f"     下位5件:")
    for _, r in sorted_pnl.tail(5).iterrows():
        print(f"       {r['ticker']:<8} {r['entry_date']}  {r['pnl_pct']:+.2f}%")

    # Top3除外Return
    top3_pnl = sorted_pnl.head(3)["pnl_pct"].sum()
    ex_top3 = round(total_pnl - top3_pnl, 2)
    print(f"     上位3トレード除外 合計PnL%: {ex_top3:+.2f}")

    best = sorted_pnl.iloc[0]
    worst = sorted_pnl.iloc[-1]
    print(f"     最大利益: {best['ticker']} {best['entry_date']} {best['pnl_pct']:+.2f}%")
    print(f"     最大損失: {worst['ticker']} {worst['entry_date']} {worst['pnl_pct']:+.2f}%")

    # PF計算
    gross_profit = trades_df[trades_df["pnl_pct"] > 0]["pnl_pct"].sum()
    gross_loss = abs(trades_df[trades_df["pnl_pct"] <= 0]["pnl_pct"].sum())
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0

    # === D) 連敗分析 ===
    wins_series = trades_df["win"].tolist()
    max_consec_loss = max_consecutive(wins_series, False)
    max_consec_win = max_consecutive(wins_series, True)
    print(f"\n  D) 連敗/連勝分析")
    print(f"     最大連敗: {max_consec_loss}")
    print(f"     最大連勝: {max_consec_win}")

    # === E) 銘柄集中度 ===
    unique_tickers = trades_df["ticker"].nunique()
    ticker_counts = Counter(trades_df["ticker"])
    top3_tickers = ticker_counts.most_common(3)
    print(f"\n  E) 銘柄集中度")
    print(f"     ユニーク銘柄: {unique_tickers} / {len(trades_df)} trades")
    print(f"     最多銘柄Top3:")
    for tk, cnt in top3_tickers:
        print(f"       {tk}: {cnt}回")

    return {
        "Pattern": name, "S": s_id, "E": e_id, "T": t_id,
        "Trades": len(trades_df),
        "PF": pf,
        "Return%": total_pnl,
        "2025Q2_PnL%": q2_pnl,
        "ExQ2_Return%": ex_q2_pnl,
        "依存度%": dep_pct,
        "MaxConsecLoss": max_consec_loss,
        "MaxConsecWin": max_consec_win,
        "UniqueTickers": unique_tickers,
        "ExTop3_Return%": ex_top3,
    }


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════

print("=" * 70)
print("FULL ANALYSIS: 10 BEST PATTERNS")
print("=" * 70)

summaries = []
for name, s_id, e_id, t_id in PATTERNS:
    summary = analyze_pattern(name, s_id, e_id, t_id)
    summaries.append(summary)

# Final comparison table
print(f"\n\n{'=' * 140}")
print("FINAL COMPARISON TABLE")
print(f"{'=' * 140}")
df = pd.DataFrame(summaries)
print(df[["Pattern", "Trades", "PF", "Return%", "2025Q2_PnL%", "ExQ2_Return%",
          "依存度%", "MaxConsecLoss", "UniqueTickers", "ExTop3_Return%"]].to_string(index=False))

df.to_csv(RESULTS_DIR / "full_analysis_10patterns.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: full_analysis_10patterns.csv")
