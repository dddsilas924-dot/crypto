"""
generate_universe.py — JPX上場銘柄リスト + yfinance で enriched CSV を生成

1. JPXから全上場銘柄リスト取得 (内国株式のみ)
2. yfinance バッチで価格/出来高を取得
3. 個別に .info からファンダメンタルを取得 (rate limit対策あり)
4. vault/universe/full_market_enriched.csv に保存
"""
import sys
import os
import time
import logging
from pathlib import Path

import pandas as pd
import numpy as np

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "vault" / "universe" / "full_market_enriched.csv"
CHECKPOINT_PATH = PROJECT_ROOT / "vault" / "universe" / "_enriched_checkpoint.csv"


def get_jpx_stock_list() -> pd.DataFrame:
    """JPXから内国株式の銘柄リストを取得"""
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    df = pd.read_excel(url)

    stock_markets = [
        "プライム（内国株式）",
        "スタンダード（内国株式）",
        "グロース（内国株式）",
    ]
    stocks = df[df["市場・商品区分"].isin(stock_markets)].copy()
    stocks["ticker"] = stocks["コード"].astype(str)
    stocks["yf_ticker"] = stocks["ticker"] + ".T"
    stocks["name"] = stocks["銘柄名"]
    stocks["sector"] = stocks["33業種区分"]
    stocks["market"] = stocks["市場・商品区分"].str.replace("（内国株式）", "", regex=False)

    return stocks[["ticker", "yf_ticker", "name", "sector", "market"]]


def batch_fetch_prices(tickers: list, batch_size=200) -> pd.DataFrame:
    """yf.download バッチで直近価格・出来高を取得"""
    import yfinance as yf

    all_rows = []

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        logger.info(f"Price batch {i+1}-{i+len(batch)}/{len(tickers)}...")

        old_stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            data = yf.download(batch, period="5d", progress=False, threads=True)
        finally:
            sys.stderr.close()
            sys.stderr = old_stderr

        if data.empty:
            continue

        if isinstance(data.columns, pd.MultiIndex):
            for t in batch:
                try:
                    close = data["Close"][t].dropna()
                    volume = data["Volume"][t].dropna()
                    if close.empty:
                        continue
                    all_rows.append({
                        "yf_ticker": t,
                        "price": close.iloc[-1],
                        "volume": volume.iloc[-1] if not volume.empty else 0,
                    })
                except (KeyError, IndexError):
                    continue
        else:
            # Single ticker
            close = data["Close"].dropna()
            volume = data["Volume"].dropna()
            if not close.empty:
                all_rows.append({
                    "yf_ticker": batch[0],
                    "price": close.iloc[-1],
                    "volume": volume.iloc[-1] if not volume.empty else 0,
                })

        time.sleep(0.5)

    return pd.DataFrame(all_rows)


def fetch_fundamentals_batch(tickers: list, existing_df: pd.DataFrame = None) -> pd.DataFrame:
    """個別に .info からファンダメンタルを取得（チェックポイント対応）"""
    import yfinance as yf

    already_done = set()
    rows = []
    if existing_df is not None and not existing_df.empty:
        already_done = set(existing_df["yf_ticker"].tolist())
        rows = existing_df.to_dict("records")

    remaining = [t for t in tickers if t not in already_done]
    total = len(remaining)
    logger.info(f"Fundamentals to fetch: {total} (already done: {len(already_done)})")

    failed = 0
    for i, ticker_str in enumerate(remaining):
        if (i + 1) % 100 == 0:
            logger.info(f"  Progress: {i+1}/{total} (ok={len(rows)}, fail={failed})")
            # Checkpoint save every 100
            pd.DataFrame(rows).to_csv(CHECKPOINT_PATH, index=False, encoding="utf-8-sig")

        try:
            t = yf.Ticker(ticker_str)
            info = t.info

            if not info:
                failed += 1
                continue

            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if current_price is None or current_price == 0:
                failed += 1
                continue

            row = {
                "yf_ticker": ticker_str,
                "market_cap": info.get("marketCap", 0) or 0,
                "price_info": current_price,
                "sma_200": info.get("twoHundredDayAverage", 0) or 0,
                "volume_info": info.get("volume", 0) or 0,
                "volume_avg_30d": info.get("averageVolume", 0) or 0,
                "per": info.get("trailingPE", 0) or 0,
                "pbr": info.get("priceToBook", 0) or 0,
                "roe": (info.get("returnOnEquity", 0) or 0) * 100,
                "roa": (info.get("returnOnAssets", 0) or 0) * 100,
                "dividend_yield": (info.get("dividendYield", 0) or 0) * 100,
                "revenue_growth_yoy": (info.get("revenueGrowth", 0) or 0) * 100,
                "profit_growth_yoy": (info.get("earningsGrowth", 0) or 0) * 100,
                "debt_equity_ratio": (info.get("debtToEquity", 0) or 0) / 100,
            }
            rows.append(row)
        except Exception as e:
            err_msg = str(e)
            if "Rate" in err_msg or "429" in err_msg or "Too Many" in err_msg:
                logger.warning(f"  Rate limited at {i+1}. Sleeping 60s...")
                # Save checkpoint
                pd.DataFrame(rows).to_csv(CHECKPOINT_PATH, index=False, encoding="utf-8-sig")
                time.sleep(60)
                # Retry
                try:
                    t = yf.Ticker(ticker_str)
                    info = t.info
                    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
                    if current_price:
                        row = {
                            "yf_ticker": ticker_str,
                            "market_cap": info.get("marketCap", 0) or 0,
                            "price_info": current_price,
                            "sma_200": info.get("twoHundredDayAverage", 0) or 0,
                            "volume_info": info.get("volume", 0) or 0,
                            "volume_avg_30d": info.get("averageVolume", 0) or 0,
                            "per": info.get("trailingPE", 0) or 0,
                            "pbr": info.get("priceToBook", 0) or 0,
                            "roe": (info.get("returnOnEquity", 0) or 0) * 100,
                            "roa": (info.get("returnOnAssets", 0) or 0) * 100,
                            "dividend_yield": (info.get("dividendYield", 0) or 0) * 100,
                            "revenue_growth_yoy": (info.get("revenueGrowth", 0) or 0) * 100,
                            "profit_growth_yoy": (info.get("earningsGrowth", 0) or 0) * 100,
                            "debt_equity_ratio": (info.get("debtToEquity", 0) or 0) / 100,
                        }
                        rows.append(row)
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
            continue

        # Small delay to avoid rate limit
        if (i + 1) % 10 == 0:
            time.sleep(0.3)

    return pd.DataFrame(rows)


def main():
    # ── Step 1: JPX銘柄リスト取得 ──
    logger.info("=== Step 1: JPX stock list ===")
    jpx_df = get_jpx_stock_list()
    logger.info(f"JPX stocks: {len(jpx_df)}")

    # ── Step 2: バッチ価格取得（有効銘柄フィルタ） ──
    logger.info("=== Step 2: Batch price fetch ===")
    yf_tickers = jpx_df["yf_ticker"].tolist()
    price_df = batch_fetch_prices(yf_tickers)
    logger.info(f"Valid stocks with price: {len(price_df)}")

    # ── Step 3: ファンダメンタル取得 ──
    logger.info("=== Step 3: Fetching fundamentals ===")
    valid_tickers = price_df["yf_ticker"].tolist()

    # チェックポイントがあれば読込
    existing = None
    if CHECKPOINT_PATH.exists():
        existing = pd.read_csv(CHECKPOINT_PATH, encoding="utf-8-sig")
        logger.info(f"Checkpoint loaded: {len(existing)} records")

    fund_df = fetch_fundamentals_batch(valid_tickers, existing)
    logger.info(f"Fundamentals: {len(fund_df)} stocks")

    # ── Step 4: マージ & 保存 ──
    logger.info("=== Step 4: Merge & save ===")
    merged = jpx_df.merge(price_df, on="yf_ticker", how="inner")

    if not fund_df.empty:
        merged = merged.merge(fund_df, on="yf_ticker", how="left")
        # price_info があればそれを使う（より正確）
        if "price_info" in merged.columns:
            merged["price"] = merged["price_info"].fillna(merged["price"])
            merged.drop(columns=["price_info"], inplace=True)
        if "volume_info" in merged.columns:
            merged["volume"] = merged["volume_info"].fillna(merged["volume"])
            merged.drop(columns=["volume_info"], inplace=True)
    else:
        # ファンダメンタルなし→デフォルト値
        for col in ["market_cap", "sma_200", "volume_avg_30d", "per", "pbr",
                     "roe", "roa", "dividend_yield", "revenue_growth_yoy",
                     "profit_growth_yoy", "debt_equity_ratio"]:
            merged[col] = 0

    # 不要列削除
    merged.drop(columns=["yf_ticker", "market"], inplace=True, errors="ignore")

    # industry列がない場合は空文字
    if "industry" not in merged.columns:
        merged["industry"] = ""

    # カラム順序を all_stocks.csv と揃える
    desired_cols = [
        "ticker", "name", "sector", "industry", "market_cap", "price",
        "sma_200", "volume", "volume_avg_30d", "per", "pbr", "roe", "roa",
        "dividend_yield", "revenue_growth_yoy", "profit_growth_yoy", "debt_equity_ratio",
    ]
    for col in desired_cols:
        if col not in merged.columns:
            merged[col] = 0
    merged = merged[desired_cols].fillna(0)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n{'='*60}")
    print(f"Generated: {OUTPUT_PATH}")
    print(f"Total stocks: {len(merged)}")
    if len(merged) > 0:
        print(f"Price 100-999: {((merged['price'] >= 100) & (merged['price'] <= 999)).sum()}")
        print(f"Revenue growth > 10%: {(merged['revenue_growth_yoy'] > 10).sum()}")
        print(f"Volume avg > 200k: {(merged['volume_avg_30d'] >= 200000).sum()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
