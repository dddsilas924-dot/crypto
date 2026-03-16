"""ハイブリッド実験: SURF改善提案(忠実) + ハイブリッド最強版 + ベースライン比較"""
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
# S30: SURF改善提案スクリーニング
# ═══════════════════════════════════════════════

def generate_s30():
    """S30 = SURF改善: 時価総額100億+、出来高3000万+、250dモメンタム20%+、daily_change10%+、GU3%+"""
    cache_path = SCREENING_DIR / "S30_v1.0_2020-01-06_2026-03-07.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, encoding="utf-8-sig")

    # Load universe
    universe_path = VAULT / "universe" / "full_market_enriched.csv"
    universe = pd.read_csv(universe_path, encoding="utf-8")

    # market_cap >= 100億
    if "market_cap" in universe.columns:
        universe = universe[universe["market_cap"] >= 10e9]

    # ROEフィルター (V1)
    has_roe = "roe" in universe.columns
    if has_roe:
        # ROE >= 10 (NaNは除外しない、後でフィルタ)
        roe_filter = universe["roe"].fillna(0) >= 10.0
        universe_v1 = universe[roe_filter].copy()
        print(f"  V1 ROEフィルター: {len(universe)} → {len(universe_v1)}")
    else:
        universe_v1 = universe.copy()
        print("  V1 ROEフィルター: ROEデータなし、スキップ")

    # セクター除外
    if "sector" in universe_v1.columns:
        before = len(universe_v1)
        universe_v1 = universe_v1[~universe_v1["sector"].str.contains("不動産|銀行", na=False)]
        print(f"  V1 セクター除外: {before} → {len(universe_v1)}")

    # ROE降順ソート、上位20銘柄
    if has_roe and len(universe_v1) > 20:
        universe_v1 = universe_v1.sort_values("roe", ascending=False).head(20)
        print(f"  V1 上位20: {len(universe_v1)}銘柄")

    tickers = universe_v1["ticker"].astype(str).tolist()
    print(f"  S30 候補銘柄: {len(tickers)}")

    results = []
    processed = 0
    for ticker in tickers:
        csv_path = CACHE_DIR / f"{ticker}.csv"
        if not csv_path.exists():
            continue
        try:
            tdf = pd.read_csv(csv_path, parse_dates=["date"], index_col="date", encoding="utf-8")
            tdf.columns = [c.lower() for c in tdf.columns]
            tdf = tdf[["open", "high", "low", "close", "volume"]].sort_index()
            if tdf.index.tz is not None:
                tdf.index = tdf.index.tz_localize(None)
            if len(tdf) < 260:
                continue

            sma_200 = tdf["close"].rolling(200, min_periods=200).mean()
            vol_avg_30 = tdf["volume"].rolling(30, min_periods=1).mean()
            prev_close = tdf["close"].shift(1)
            daily_change = (tdf["close"] - prev_close) / prev_close * 100
            # Gap up: (open - prev_close) / prev_close * 100
            gap_up_pct = (tdf["open"] - prev_close) / prev_close * 100
            # 250日モメンタム: (close / close_250d_ago - 1) * 100
            close_250d = tdf["close"].shift(250)
            momentum_250d = (tdf["close"] / close_250d - 1) * 100

            for i in range(250, len(tdf)):
                dt = tdf.index[i]
                close_val = tdf.iloc[i]["close"]

                # close > sma_200
                if pd.isna(sma_200.iloc[i]) or close_val <= sma_200.iloc[i]:
                    continue
                # momentum_250d >= 20
                if pd.isna(momentum_250d.iloc[i]) or momentum_250d.iloc[i] < 20.0:
                    continue
                # daily_change >= 10%
                if pd.isna(daily_change.iloc[i]) or daily_change.iloc[i] < 10.0:
                    continue
                # gap_up >= 3%
                if pd.isna(gap_up_pct.iloc[i]) or gap_up_pct.iloc[i] < 3.0:
                    continue
                # volume_avg_30d >= 50,000,000 (SURF's strict condition)
                if pd.isna(vol_avg_30.iloc[i]) or vol_avg_30.iloc[i] < 50000000:
                    continue

                results.append({
                    "ticker": ticker,
                    "date": str(dt.date()),
                    "close": round(close_val, 2),
                    "daily_change_pct": round(daily_change.iloc[i], 2),
                    "gap_up_pct": round(gap_up_pct.iloc[i], 2),
                    "momentum_250d": round(momentum_250d.iloc[i], 2),
                    "volume": int(tdf.iloc[i]["volume"]),
                })
            processed += 1
        except Exception:
            continue

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values(["date", "ticker"]).reset_index(drop=True)
    result_df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"  S30: {len(result_df)} hits (scanned {processed} tickers)")
    return result_df


# ═══════════════════════════════════════════════
# S31: ハイブリッドスクリーニング (S1 UNION S15 + GU15%ブロック)
# ═══════════════════════════════════════════════

def generate_s31():
    """S31 = S1 UNION S15 + GU+15%ブロック"""
    cache_path = SCREENING_DIR / "S31_v1.0_2020-01-06_2026-03-07.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, encoding="utf-8-sig")

    # Load S1 and S15
    s1_path = SCREENING_DIR / "S1_v1.1_2020-01-06_2026-03-07.csv"
    s15_path = SCREENING_DIR / "S15_v1.0_2020-01-06_2026-03-07.csv"

    s1_df = pd.read_csv(s1_path, encoding="utf-8-sig")
    s15_df = pd.read_csv(s15_path, encoding="utf-8-sig")

    print(f"  S1: {len(s1_df)} hits, S15: {len(s15_df)} hits")

    # UNION (和集合) - ticker+dateで重複除去
    # 共通カラムのみで結合
    common_cols = list(set(s1_df.columns) & set(s15_df.columns))
    union_df = pd.concat([s1_df[common_cols], s15_df[common_cols]], ignore_index=True)
    union_df = union_df.drop_duplicates(subset=["ticker", "date"], keep="first")
    print(f"  UNION: {len(union_df)} hits (重複除去済)")

    # GU+15%ブロック: エントリー日(翌営業日)のopen <= スクリーニング日のclose * 1.15
    results = []
    for _, row in union_df.iterrows():
        ticker = str(row["ticker"])
        trigger_date = pd.Timestamp(row["date"])
        csv_path = CACHE_DIR / f"{ticker}.csv"
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
            future = tdf.iloc[idx + 1:]
            if len(future) < 1:
                continue
            next_open = future.iloc[0]["open"]
            screen_close = tdf.iloc[idx]["close"]
            # GU+15%ブロック
            if next_open > screen_close * 1.15:
                continue
            results.append(row)
        except Exception:
            continue

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values(["date", "ticker"]).reset_index(drop=True)
    result_df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"  S31: {len(result_df)} hits (UNION + GU15%ブロック)")
    return result_df


# ═══════════════════════════════════════════════
# Backtest runner helper
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

        if trades:
            trades_df = pd.DataFrame([{
                "ticker": t.ticker, "entry_date": t.entry_date,
                "entry_price": t.entry_price, "exit_date": t.exit_date,
                "exit_price": t.exit_price, "exit_reason": t.exit_reason,
                "pnl_pct": t.pnl_pct, "holding_days": t.holding_days,
            } for t in trades])
            trades_df.to_csv(
                RESULTS_DIR / f"trades_hybrid_{name}.csv",
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
print("HYBRID EXPERIMENT")
print("Pattern 1: SURF改善提案(忠実) / Pattern 2: ハイブリッド最強版")
print("=" * 80)

# Generate screening results
print("\n--- Generating Screening Results ---")

print("S30 (SURF改善提案)...")
s30_df = generate_s30()
print(f"S30: {len(s30_df)} hits")

print("S31 (ハイブリッド: S1∪S15 + GU15%ブロック)...")
s31_df = generate_s31()
print(f"S31: {len(s31_df)} hits")

# Load existing screening results for baseline
s1_df = pd.read_csv(SCREENING_DIR / "S1_v1.1_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")
s20_df = pd.read_csv(SCREENING_DIR / "S20_v1.0_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")
s21_df = pd.read_csv(SCREENING_DIR / "S21_v1.0_2020-01-06_2026-03-07.csv", encoding="utf-8-sig")

print(f"S1:  {len(s1_df)} hits (cached)")
print(f"S20: {len(s20_df)} hits (cached)")
print(f"S21: {len(s21_df)} hits (cached)")

# Run 7 patterns
print("\n--- Running 7 Pattern Backtests ---")
results = []

# Pattern 1: SURFv2
print("[1/7] SURFv2: S30 x E30 x T30")
results.append(run_pattern("P1_SURFv2", "SURF改善", "S30", "E30", "T30", s30_df, "SURF改善提案を忠実実装"))

# Pattern 2: ハイブリッド標準
print("[2/7] Hybrid標準: S31 x E31 x T31")
results.append(run_pattern("P2_Hybrid", "Hybrid", "S31", "E31", "T31", s31_df, "有効要素全部載せ pos20%"))

# Pattern 3: ハイブリッド安全
print("[3/7] Hybrid安全: S31 x E31 x T32")
results.append(run_pattern("P3_HybSafe", "Hybrid安全", "S31", "E31", "T32", s31_df, "pos15% MDD3%狙い"))

# Pattern 4: ハイブリッド攻撃
print("[4/7] Hybrid攻撃: S31 x E31 x T33")
results.append(run_pattern("P4_HybAggr", "Hybrid攻撃", "S31", "E31", "T33", s31_df, "pos50% リターン最大化"))

# Pattern 5: ベースライン
print("[5/7] Baseline: S1 x E16 x T6")
results.append(run_pattern("P5_Base", "Baseline", "S1", "E16", "T6", s1_df, "既存最良(MDD<3%)"))

# Pattern 6: B1ベスト
print("[6/7] B1ベスト: S20 x E20 x T20")
results.append(run_pattern("P6_B1best", "B1best", "S20", "E20", "T20", s20_df, "Return最高だった"))

# Pattern 7: B2bベスト
print("[7/7] B2bベスト: S21 x E16 x T21")
results.append(run_pattern("P7_B2best", "B2best", "S21", "E16", "T21", s21_df, "PF最高だった"))

# Output
df = pd.DataFrame(results)
print(f"\n\n{'=' * 130}")
print("HYBRID EXPERIMENT RESULTS")
print(f"{'=' * 130}")
print(df[["Pattern", "Source", "S", "E", "T", "Trades", "WR%", "PF",
          "Return%", "MDD%", "MaxSingleDD%", "AvgPnL%", "Extra"]].to_string(index=False))

out_path = RESULTS_DIR / "hybrid_experiment.csv"
df.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nSaved: {out_path}")

# Analysis
print(f"\n{'=' * 60}")
print("ANALYSIS")
print(f"{'=' * 60}")
baseline = df[df["Pattern"] == "P5_Base"].iloc[0]
print(f"Baseline (S1×E16×T6): PF={baseline['PF']}, Return={baseline['Return%']}%, MDD={baseline['MDD%']}%")
for _, r in df.iterrows():
    if r["Pattern"] == "P5_Base":
        continue
    ret_diff = r["Return%"] - baseline["Return%"]
    pf_diff = r["PF"] - baseline["PF"]
    print(f"  {r['Pattern']} ({r['Source']}): Return {r['Return%']:+.1f}% (vs Base: {ret_diff:+.1f}%), "
          f"PF={r['PF']} ({pf_diff:+.2f}), Trades={r['Trades']}, MDD={r['MDD%']}%")

# Hybrid comparison
print(f"\n{'=' * 60}")
print("HYBRID VARIANTS COMPARISON")
print(f"{'=' * 60}")
hybrids = df[df["Source"].str.contains("Hybrid")]
if not hybrids.empty:
    for _, r in hybrids.iterrows():
        print(f"  {r['Pattern']}: Return={r['Return%']}%, PF={r['PF']}, MDD={r['MDD%']}%, "
              f"MaxSingleDD={r['MaxSingleDD%']}%")
