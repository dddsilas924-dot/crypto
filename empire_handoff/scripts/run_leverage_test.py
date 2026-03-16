"""レバレッジバックテスト: BOT-A(S1×E16) / BOT-B(S12×E16) × T60-T65"""
import copy
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_engine.backtest_runner import run_backtest_from_screening, compute_summary
from trading_engine.core.config_loader import resolve_logic_path
from trading_engine.core.logic_parser import parse_logic_file

logging.basicConfig(level=logging.WARNING)

VAULT = Path(__file__).resolve().parent.parent / "vault"
SCREENING_DIR = VAULT / "screening_results"
RESULTS_DIR = VAULT / "backtest_results"

with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)

PATTERNS = [
    ("A_T60", "S1",  "E16", "T60", "レバ3×pos80%"),
    ("A_T61", "S1",  "E16", "T61", "レバ3×pos50%"),
    ("A_T62", "S1",  "E16", "T62", "レバ3×pos30%"),
    ("A_T63", "S1",  "E16", "T63", "レバ2×pos50%"),
    ("A_T64", "S1",  "E16", "T64", "レバ1.5×pos50%"),
    ("A_T65", "S1",  "E16", "T65", "レバ3×pos100% 限界"),
    ("B_T60", "S12", "E16", "T60", "レバ3×pos80%"),
    ("B_T61", "S12", "E16", "T61", "レバ3×pos50%"),
    ("B_T62", "S12", "E16", "T62", "レバ3×pos30%"),
    ("B_T63", "S12", "E16", "T63", "レバ2×pos50%"),
    ("B_T64", "S12", "E16", "T64", "レバ1.5×pos50%"),
    ("B_T65", "S12", "E16", "T65", "レバ3×pos100% 限界"),
]


def get_pos_info(t_id):
    logics_dir = VAULT / "logics"
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    ps = t_parsed["blocks"].get("position_sizing", {})
    pos_pct = float(ps.get("value", 100))
    lev = float(ps.get("leverage", 1.0))
    return pos_pct, lev


def is_q2_2025(date_str):
    dt = pd.Timestamp(date_str)
    return dt.year == 2025 and 4 <= dt.month <= 6


def run_pattern(label, s_id, e_id, t_id, desc, screening_df):
    config = copy.deepcopy(BASE_CONFIG)
    pos_pct, lev = get_pos_info(t_id)
    effective = pos_pct * lev

    try:
        result = run_backtest_from_screening(
            config, VAULT, screening_df,
            logic_e=e_id,
            override_trade_logic=t_id,
        )
    except Exception as e:
        print(f"  ERROR {label}: {e}")
        return None

    trades = result.trades
    if not trades:
        return {
            "Pattern": label, "S": s_id, "E": e_id, "T": t_id,
            "Lev": lev, "Pos%": pos_pct, "実質投入%": effective, "Desc": desc,
            "Trades": 0, "WR%": 0, "PF": 0, "Return%": 0, "MDD%": 0,
            "MaxSingleDD%": 0, "破産": "N",
            "Trades_exQ2": 0, "Return%_exQ2": 0, "PF_exQ2": 0, "依存度%": 0,
            "WorstTrade": "", "WorstPnL%": 0, "WorstLevLoss%": 0,
        }

    # Save trades
    trades_df = pd.DataFrame([{
        "ticker": t.ticker, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "exit_date": t.exit_date,
        "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "pnl_pct": t.pnl_pct, "holding_days": t.holding_days,
    } for t in trades])
    trades_df.to_csv(
        RESULTS_DIR / f"trades_lev_{label}_{t_id}.csv",
        index=False, encoding="utf-8-sig"
    )

    # Worst trade
    worst_t = min(trades, key=lambda t: t.pnl_pct)
    worst_lev_loss = worst_t.pnl_pct * (effective / 100)

    # Bankruptcy check
    bankrupt = result.total_return_pct <= -99.9

    # Q2-excluded
    trades_exq2 = [t for t in trades if not is_q2_2025(t.entry_date)]
    if trades_exq2:
        res_exq2 = compute_summary(trades_exq2, position_pct=pos_pct, leverage=lev)
        trades_exq2_n = res_exq2.total_trades
        return_exq2 = res_exq2.total_return_pct
        pf_exq2 = res_exq2.profit_factor
    else:
        trades_exq2_n = 0
        return_exq2 = 0
        pf_exq2 = 0

    dep = 0
    if result.total_return_pct != 0:
        dep = round((result.total_return_pct - return_exq2) / abs(result.total_return_pct) * 100, 1)

    return {
        "Pattern": label, "S": s_id, "E": e_id, "T": t_id,
        "Lev": lev, "Pos%": pos_pct, "実質投入%": effective, "Desc": desc,
        "Trades": result.total_trades,
        "WR%": round(result.win_rate, 1),
        "PF": round(result.profit_factor, 2),
        "Return%": round(result.total_return_pct, 1),
        "MDD%": round(result.max_drawdown_pct, 1),
        "MaxSingleDD%": round(worst_lev_loss, 2),
        "破産": "Y" if bankrupt else "N",
        "Trades_exQ2": trades_exq2_n,
        "Return%_exQ2": round(return_exq2, 1),
        "PF_exQ2": round(pf_exq2, 2),
        "依存度%": dep,
        "WorstTrade": f"{worst_t.ticker} {worst_t.entry_date}",
        "WorstPnL%": round(worst_t.pnl_pct, 2),
        "WorstLevLoss%": round(worst_lev_loss, 2),
    }


# Load screening data
s1_df = pd.read_csv(SCREENING_DIR / "S1_v1.1_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")
s12_df = pd.read_csv(SCREENING_DIR / "S12_v1.0_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")

print("=" * 80)
print("LEVERAGE BACKTEST: BOT-A(S1×E16) / BOT-B(S12×E16)")
print("=" * 80)

results = []
for i, (label, s_id, e_id, t_id, desc) in enumerate(PATTERNS):
    s_df = s1_df if s_id == "S1" else s12_df
    print(f"  [{i+1}/{len(PATTERNS)}] {label}: {s_id}×{e_id}×{t_id} ({desc})")
    r = run_pattern(label, s_id, e_id, t_id, desc, s_df)
    if r:
        results.append(r)

df = pd.DataFrame(results)

COLS1 = ["Pattern", "Lev", "Pos%", "実質投入%", "Trades", "WR%", "PF",
         "Return%", "MDD%", "MaxSingleDD%", "破産"]
COLS2 = ["Pattern", "Lev", "Pos%", "実質投入%", "Trades", "PF", "Return%",
         "Return%_exQ2", "PF_exQ2", "依存度%", "破産"]
COLS3 = ["Pattern", "WorstTrade", "WorstPnL%", "Lev", "実質投入%", "WorstLevLoss%"]

bot_a = df[df["Pattern"].str.startswith("A")].copy()
bot_b = df[df["Pattern"].str.startswith("B")].copy()

print(f"\n{'=' * 130}")
print("TABLE 1: BOT-A (S1×E16) — Return% 降順")
print(f"{'=' * 130}")
print(bot_a.sort_values("Return%", ascending=False)[COLS1].to_string(index=False))

print(f"\n{'=' * 130}")
print("TABLE 2: BOT-B (S12×E16) — Return% 降順")
print(f"{'=' * 130}")
print(bot_b.sort_values("Return%", ascending=False)[COLS1].to_string(index=False))

print(f"\n{'=' * 130}")
print("TABLE 3: ALL PATTERNS — PF 降順")
print(f"{'=' * 130}")
print(df.sort_values("PF", ascending=False)[COLS2].to_string(index=False))

print(f"\n{'=' * 130}")
print("TABLE 4: GDリスク分析 — 最悪トレード一覧")
print(f"{'=' * 130}")
print(df.sort_values("WorstLevLoss%")[COLS3].to_string(index=False))

df.to_csv(RESULTS_DIR / "leverage_test_results.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: leverage_test_results.csv")
