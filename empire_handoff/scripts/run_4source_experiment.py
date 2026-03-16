"""4ソース対照実験: A(先生)/B1(Gemini解釈)/B2(Gemini独自)/C(SURF) 8パターン"""
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
logger = logging.getLogger(__name__)

VAULT = Path(__file__).resolve().parent.parent / "vault"
CACHE_DIR = VAULT / "data_cache" / "price"
SCREENING_DIR = VAULT / "screening_results"
RESULTS_DIR = VAULT / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

with open(VAULT / "active_config.yaml", "r", encoding="utf-8") as f:
    BASE_CONFIG = yaml.safe_load(f)

# ═══════════════════════════════════════════════
# Step 1: Generate S20, S21, S22 screening results
# ═══════════════════════════════════════════════

def load_s1():
    """Load existing S1 full-period screening results."""
    path = SCREENING_DIR / "S1_v1.1_2020-01-06_2026-03-07.csv"
    return pd.read_csv(path, encoding="utf-8-sig")


def generate_s20(s1_df):
    """S20 = S1 + GU必須 (open > prev_close on screening day)."""
    cache_dir = CACHE_DIR
    results = []
    for _, row in s1_df.iterrows():
        ticker = str(row["ticker"])
        trigger_date = pd.Timestamp(row["date"])
        csv_path = cache_dir / f"{ticker}.csv"
        if not csv_path.exists():
            continue
        try:
            tdf = pd.read_csv(csv_path, parse_dates=["date"], index_col="date", encoding="utf-8")
            tdf.columns = [c.lower() for c in tdf.columns]
            if tdf.index.tz is not None:
                tdf.index = tdf.index.tz_localize(None)
            if trigger_date not in tdf.index:
                continue
            idx = tdf.index.get_loc(trigger_date)
            if idx < 1:
                continue
            day_open = tdf.iloc[idx]["open"]
            prev_close = tdf.iloc[idx - 1]["close"]
            if day_open > prev_close:
                results.append(row)
        except Exception:
            continue
    return pd.DataFrame(results)


def generate_s21(s1_df):
    """S21 = S1 + GU上限15% (open <= prev_close * 1.15)."""
    cache_dir = CACHE_DIR
    results = []
    for _, row in s1_df.iterrows():
        ticker = str(row["ticker"])
        trigger_date = pd.Timestamp(row["date"])
        csv_path = cache_dir / f"{ticker}.csv"
        if not csv_path.exists():
            continue
        try:
            tdf = pd.read_csv(csv_path, parse_dates=["date"], index_col="date", encoding="utf-8")
            tdf.columns = [c.lower() for c in tdf.columns]
            if tdf.index.tz is not None:
                tdf.index = tdf.index.tz_localize(None)
            if trigger_date not in tdf.index:
                continue
            idx = tdf.index.get_loc(trigger_date)
            if idx < 1:
                continue
            # Check NEXT day's open (entry day) vs screening day close
            future = tdf.iloc[idx + 1:]
            if len(future) < 1:
                continue
            next_open = future.iloc[0]["open"]
            screen_close = tdf.iloc[idx]["close"]
            if next_open <= screen_close * 1.15:
                results.append(row)
        except Exception:
            continue
    return pd.DataFrame(results)


def generate_s22(s1_df):
    """S22 = SURF流: price 100-999, close>sma200, daily_change>=15%, avg_vol_20d>=200000.
    Re-use S1's scanning infrastructure but with different filters.
    S1 already has daily_change>=15% and close>sma200.
    We need to expand price range to 100-999 and add volume filter.
    For simplicity, post-filter S1 with volume, and also run a wider scan.
    Actually S1 has price 200-500. S22 needs 100-999.
    Let's do a fresh scan using the screener v2 approach."""
    # For simplicity, we'll filter from S1 + add volume check
    # AND also scan wider price range from cache
    # But S1 already filters 200-500. We need 100-999.
    # So we run a simplified scan from scratch.
    from trading_engine.pipeline.screener import run_screening_v2
    cache_path = SCREENING_DIR / "S22_v1.0_2020-01-06_2026-03-07.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, encoding="utf-8-sig")

    # Load universe for fundamental filter
    universe_path = VAULT / "universe" / "full_market_enriched.csv"
    universe = pd.read_csv(universe_path, encoding="utf-8")
    # market_cap <= 50B
    if "market_cap" in universe.columns:
        universe = universe[universe["market_cap"] <= 50e9]
    tickers = universe["ticker"].astype(str).tolist()

    results = []
    cache_dir = CACHE_DIR
    processed = 0
    for ticker in tickers:
        csv_path = cache_dir / f"{ticker}.csv"
        if not csv_path.exists():
            continue
        try:
            tdf = pd.read_csv(csv_path, parse_dates=["date"], index_col="date", encoding="utf-8")
            tdf.columns = [c.lower() for c in tdf.columns]
            tdf = tdf[["open", "high", "low", "close", "volume"]].sort_index()
            if tdf.index.tz is not None:
                tdf.index = tdf.index.tz_localize(None)
            if len(tdf) < 210:
                continue

            sma_200 = tdf["close"].rolling(200, min_periods=200).mean()
            vol_avg_20 = tdf["volume"].rolling(20, min_periods=1).mean()
            prev_close = tdf["close"].shift(1)
            daily_change = (tdf["close"] - prev_close) / prev_close * 100

            for i in range(200, len(tdf)):
                dt = tdf.index[i]
                close_val = tdf.iloc[i]["close"]
                # Price range 100-999
                if close_val < 100 or close_val > 999:
                    continue
                # daily_change >= 15%
                if pd.isna(daily_change.iloc[i]) or daily_change.iloc[i] < 15.0:
                    continue
                # close > sma_200
                if pd.isna(sma_200.iloc[i]) or close_val <= sma_200.iloc[i]:
                    continue
                # avg_volume_20d >= 200000
                if pd.isna(vol_avg_20.iloc[i]) or vol_avg_20.iloc[i] < 200000:
                    continue
                results.append({
                    "ticker": ticker,
                    "date": str(dt.date()),
                    "close": round(close_val, 2),
                    "daily_change_pct": round(daily_change.iloc[i], 2),
                    "volume": int(tdf.iloc[i]["volume"]),
                })
            processed += 1
        except Exception:
            continue

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values(["date", "ticker"]).reset_index(drop=True)
    result_df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"S22: {len(result_df)} hits (scanned {processed} tickers)")
    return result_df


# ═══════════════════════════════════════════════
# Step 2: Run 8 pattern backtests
# ═══════════════════════════════════════════════

def get_pos_pct(t_id):
    logics_dir = VAULT / "logics"
    t_path = resolve_logic_path(t_id, "trade_management", logics_dir)
    t_parsed = parse_logic_file(t_path)
    pos_sizing = t_parsed["blocks"].get("position_sizing", {})
    return float(pos_sizing.get("value", 100))


def run_pattern(name, source, s_id, e_id, t_id, screening_df, extra=""):
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

        # Save trades
        if trades:
            trades_df = pd.DataFrame([{
                "ticker": t.ticker, "entry_date": t.entry_date,
                "entry_price": t.entry_price, "exit_date": t.exit_date,
                "exit_price": t.exit_price, "exit_reason": t.exit_reason,
                "pnl_pct": t.pnl_pct, "holding_days": t.holding_days,
            } for t in trades])
            trades_df.to_csv(
                RESULTS_DIR / f"trades_4src_{name}.csv",
                index=False, encoding="utf-8-sig"
            )

        return {
            "Pattern": name, "Source": source,
            "S": s_id, "E": e_id, "T": t_id,
            "Trades": result.total_trades,
            "WR%": round(result.win_rate, 1),
            "PF": round(result.profit_factor, 2),
            "Return%": round(result.total_return_pct, 1),
            "MDD%": round(result.max_drawdown_pct, 1),
            "MaxSingleDD%": round(max_single_dd, 2),
            "AvgPnL%": round(result.avg_pnl_pct, 2),
            "Extra": extra,
        }
    except Exception as e:
        print(f"  ERROR {name}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "Pattern": name, "Source": source,
            "S": s_id, "E": e_id, "T": t_id,
            "Trades": 0, "WR%": 0, "PF": 0, "Return%": 0,
            "MDD%": 0, "MaxSingleDD%": 0, "AvgPnL%": 0, "Extra": f"ERROR: {e}",
        }


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════

print("=" * 80)
print("4-SOURCE COMPARATIVE EXPERIMENT")
print("A(Teacher) / B1(Gemini Interp) / B2(Gemini Original) / C(SURF)")
print("=" * 80)

# Load / generate screening results
print("\n--- Generating Screening Results ---")
s1_df = load_s1()
print(f"S1:  {len(s1_df)} hits (cached)")

print("Generating S20 (S1 + GU)...")
s20_df = generate_s20(s1_df)
s20_df.to_csv(SCREENING_DIR / "S20_v1.0_2020-01-06_2026-03-07.csv",
              index=False, encoding="utf-8-sig")
print(f"S20: {len(s20_df)} hits")

print("Generating S21 (S1 + GU upper limit 15%)...")
s21_df = generate_s21(s1_df)
s21_df.to_csv(SCREENING_DIR / "S21_v1.0_2020-01-06_2026-03-07.csv",
              index=False, encoding="utf-8-sig")
print(f"S21: {len(s21_df)} hits")

print("Generating S22 (SURF: 100-999, vol>=200k)...")
s22_df = generate_s22(s1_df)
print(f"S22: {len(s22_df)} hits")

# Run 8 patterns
print("\n--- Running 8 Pattern Backtests ---")
results = []

# Pattern 1: A baseline
print("[1/8] A baseline: S1 x E16 x T6")
results.append(run_pattern("P1_A", "A(Teacher)", "S1", "E16", "T6", s1_df, "Baseline best"))

# Pattern 2: B1 (Gemini interpretation)
print("[2/8] B1: S20 x E20 x T20")
results.append(run_pattern("P2_B1", "B1(Gemini)", "S20", "E20", "T20", s20_df, "GU+5MA強化+5MA動的Exit"))

# Pattern 3: B2a (fixed SL/TP)
print("[3/8] B2a: S1 x E16 x T21")
results.append(run_pattern("P3_B2a", "B2(Gemini独自)", "S1", "E16", "T21", s1_df, "固定SL3.5%/TP9%/TSなし"))

# Pattern 4: B2b (GU upper limit)
print("[4/8] B2b: S21 x E16 x T21")
results.append(run_pattern("P4_B2b", "B2(Gemini独自)", "S21", "E16", "T21", s21_df, "GU+15%ブロック"))

# Pattern 5: B2c (DD lock)
print("[5/8] B2c: S1 x E16 x T22")
results.append(run_pattern("P5_B2c", "B2(Gemini独自)", "S1", "E16", "T22", s1_df, "DD-10%ロック"))

# Pattern 6: B2d (2 position limit)
print("[6/8] B2d: S1 x E16 x T23")
results.append(run_pattern("P6_B2d", "B2(Gemini独自)", "S1", "E16", "T23", s1_df, "2銘柄制限"))

# Pattern 7: B2e (full B2)
print("[7/8] B2e: S21 x E16 x T24")
results.append(run_pattern("P7_B2e", "B2(Gemini独自)", "S21", "E16", "T24", s21_df, "B2フル装備"))

# Pattern 8: C (SURF)
print("[8/8] C: S22 x E21 x T25")
results.append(run_pattern("P8_C", "C(SURF)", "S22", "E21", "T25", s22_df, "SURF総合"))

# Output
df = pd.DataFrame(results)
print(f"\n\n{'=' * 120}")
print("4-SOURCE COMPARATIVE EXPERIMENT RESULTS")
print(f"{'=' * 120}")
print(df[["Pattern", "Source", "S", "E", "T", "Trades", "WR%", "PF",
          "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%", "Extra"]].to_string(index=False))

out_path = RESULTS_DIR / "4source_experiment.csv"
df.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")

# Quick analysis
print(f"\n{'=' * 60}")
print("ANALYSIS")
print(f"{'=' * 60}")
baseline = df[df["Pattern"] == "P1_A"].iloc[0]
print(f"Baseline (A): PF={baseline['PF']}, Return={baseline['Return%']}%, MDD={baseline['MDD%']}%")
for _, r in df.iterrows():
    if r["Pattern"] == "P1_A":
        continue
    ret_diff = r["Return%"] - baseline["Return%"]
    print(f"  {r['Pattern']} ({r['Source']}): Return {r['Return%']:+.1f}% (vs A: {ret_diff:+.1f}%), "
          f"PF={r['PF']}, Trades={r['Trades']}")
