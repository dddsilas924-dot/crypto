"""BOT-A / BOT-B 微調整バックテスト + 2025Q2除外分析"""
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

# ═══════════════════════════════════════════════
# Pattern definitions
# ═══════════════════════════════════════════════

BOT_A = [
    ("A1", "S1", "E16", "T40", "pos15% MDD3%狙い"),
    ("A2", "S1", "E16", "T41", "pos25%"),
    ("A3", "S1", "E16", "T42", "pos40% バランス"),
    ("A4", "S1", "E16", "T14", "pos80% 既存"),
    ("A5", "S1", "E16", "T43", "pos100% フルベット"),
    ("A6", "S1", "E16", "T44", "SLタイト2.5%/TP12%"),
    ("A7", "S1", "E16", "T45", "TP20%/5日ガチホ"),
    ("A8", "S1", "E16", "T46", "T14+5MA動的Exit"),
]

BOT_B = [
    ("B1", "S12", "E16", "T50", "T6類似安全版"),
    ("B2", "S12", "E16", "T51", "T14縮小pos20%"),
    ("B3", "S12", "E16", "T52", "5MA動的Exit pos20%"),
    ("B4", "S12", "E16", "T53", "ワイドSL+利伸ばし"),
    ("B5", "S12", "E16", "T54", "攻撃pos50%"),
    ("B6", "S12", "E16", "T55", "超防衛SL2%/pos15%"),
    ("B7", "S12", "E18", "T52", "E18+5MA動的Exit"),
    ("B8", "S12", "E32", "T52", "E32(GU必須)+5MA動的Exit"),
]


def get_pos_pct(t_id):
    logics_dir = VAULT / "logics"
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    pos_sizing = t_parsed["blocks"].get("position_sizing", {})
    return float(pos_sizing.get("value", 100))


def is_q2_2025(date_str):
    dt = pd.Timestamp(date_str)
    return dt.year == 2025 and 4 <= dt.month <= 6


def run_pattern(label, s_id, e_id, t_id, desc, screening_df):
    config = copy.deepcopy(BASE_CONFIG)
    pos_pct = get_pos_pct(t_id)

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
            "BOT": label[0], "Pattern": label, "S": s_id, "E": e_id, "T": t_id,
            "pos%": pos_pct, "Desc": desc,
            "Trades": 0, "WR%": 0, "PF": 0, "Return%": 0, "MDD%": 0, "MaxSingleDD%": 0,
            "Trades_exQ2": 0, "Return%_exQ2": 0, "PF_exQ2": 0, "依存度%": 0,
        }

    # Save trades CSV
    trades_df = pd.DataFrame([{
        "ticker": t.ticker, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "exit_date": t.exit_date,
        "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "pnl_pct": t.pnl_pct, "holding_days": t.holding_days,
    } for t in trades])
    trades_df.to_csv(
        RESULTS_DIR / f"trades_bot_{label}_{s_id}_{e_id}_{t_id}.csv",
        index=False, encoding="utf-8-sig"
    )

    # Full period stats
    worst_pnl = min(t.pnl_pct for t in trades)
    max_single_dd = worst_pnl * (pos_pct / 100)

    # 2025Q2除外stats
    trades_exq2 = [t for t in trades if not is_q2_2025(t.entry_date)]
    if trades_exq2:
        result_exq2 = compute_summary(trades_exq2, position_pct=pos_pct)
        trades_exq2_n = result_exq2.total_trades
        return_exq2 = result_exq2.total_return_pct
        pf_exq2 = result_exq2.profit_factor
    else:
        trades_exq2_n = 0
        return_exq2 = 0
        pf_exq2 = 0

    dep = 0
    if result.total_return_pct != 0:
        dep = round((result.total_return_pct - return_exq2) / abs(result.total_return_pct) * 100, 1)

    return {
        "BOT": label[0], "Pattern": label, "S": s_id, "E": e_id, "T": t_id,
        "pos%": pos_pct, "Desc": desc,
        "Trades": result.total_trades,
        "WR%": round(result.win_rate, 1),
        "PF": round(result.profit_factor, 2),
        "Return%": round(result.total_return_pct, 1),
        "MDD%": round(result.max_drawdown_pct, 1),
        "MaxSingleDD%": round(max_single_dd, 2),
        "Trades_exQ2": trades_exq2_n,
        "Return%_exQ2": round(return_exq2, 1),
        "PF_exQ2": round(pf_exq2, 2),
        "依存度%": dep,
    }


# ═══════════════════════════════════════════════
# Load screening data
# ═══════════════════════════════════════════════

s1_df = pd.read_csv(SCREENING_DIR / "S1_v1.1_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")
s12_df = pd.read_csv(SCREENING_DIR / "S12_v1.0_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")
print(f"S1: {len(s1_df)} hits, S12: {len(s12_df)} hits")

# ═══════════════════════════════════════════════
# Run all patterns
# ═══════════════════════════════════════════════

print("=" * 80)
print("BOT-A & BOT-B BACKTEST")
print("=" * 80)

results = []

print("\n--- BOT-A (S1 × E16 × T系) ---")
for i, (label, s_id, e_id, t_id, desc) in enumerate(BOT_A):
    print(f"  [{i+1}/{len(BOT_A)}] {label}: {s_id}×{e_id}×{t_id} ({desc})")
    r = run_pattern(label, s_id, e_id, t_id, desc, s1_df)
    if r:
        results.append(r)

print("\n--- BOT-B (S12 × E系 × T系) ---")
for i, (label, s_id, e_id, t_id, desc) in enumerate(BOT_B):
    print(f"  [{i+1}/{len(BOT_B)}] {label}: {s_id}×{e_id}×{t_id} ({desc})")
    r = run_pattern(label, s_id, e_id, t_id, desc, s12_df)
    if r:
        results.append(r)

df = pd.DataFrame(results)

COLS = ["Pattern", "S", "E", "T", "pos%", "Trades", "WR%", "PF", "Return%", "MDD%",
        "MaxSingleDD%", "Trades_exQ2", "Return%_exQ2", "PF_exQ2", "依存度%"]

# ═══════════════════════════════════════════════
# Output tables
# ═══════════════════════════════════════════════

bot_a = df[df["BOT"] == "A"].copy()
bot_b = df[df["BOT"] == "B"].copy()

print(f"\n\n{'=' * 140}")
print("TABLE 1: BOT-A (Return% 降順)")
print(f"{'=' * 140}")
print(bot_a.sort_values("Return%", ascending=False)[COLS].to_string(index=False))

print(f"\n{'=' * 140}")
print("TABLE 2: BOT-B (Return% 降順)")
print(f"{'=' * 140}")
print(bot_b.sort_values("Return%", ascending=False)[COLS].to_string(index=False))

print(f"\n{'=' * 140}")
print("TABLE 3: BOT-A (Return%_exQ2 降順)")
print(f"{'=' * 140}")
print(bot_a.sort_values("Return%_exQ2", ascending=False)[COLS].to_string(index=False))

print(f"\n{'=' * 140}")
print("TABLE 4: BOT-B (Return%_exQ2 降順)")
print(f"{'=' * 140}")
print(bot_b.sort_values("Return%_exQ2", ascending=False)[COLS].to_string(index=False))

print(f"\n{'=' * 140}")
print("TABLE 5: ALL PATTERNS (PF_exQ2 降順 Top10)")
print(f"{'=' * 140}")
top10 = df[df["Trades_exQ2"] >= 5].sort_values("PF_exQ2", ascending=False).head(10)
print(top10[COLS].to_string(index=False))

# Save
df.to_csv(RESULTS_DIR / "bot_ab_results.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: bot_ab_results.csv")
