"""
fetch_all_prices.py — full_market_enriched.csv の全銘柄株価を一括取得

vault/data_cache/price/{ticker}.csv に保存。
既にCSVがある銘柄はスキップ（新規のみ取得）。

Usage:
    python scripts/fetch_all_prices.py
    python scripts/fetch_all_prices.py --start 2022-01-01
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = PROJECT_ROOT / "vault"
CACHE_DIR = VAULT_ROOT / "data_cache" / "price"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_all(start: str = "2022-01-01") -> None:
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance 未インストール: pip install yfinance")
        sys.exit(1)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ユニバース読込
    csv_path = VAULT_ROOT / "universe" / "full_market_enriched.csv"
    if not csv_path.exists():
        csv_path = VAULT_ROOT / "universe" / "all_stocks.csv"
    if not csv_path.exists():
        logger.error(f"銘柄CSV が見つかりません: {csv_path}")
        sys.exit(1)

    universe = pd.read_csv(csv_path, encoding="utf-8")
    tickers = universe["ticker"].astype(str).tolist()
    logger.info(f"ユニバース: {len(tickers)}銘柄 ({csv_path.name})")

    # 既存キャッシュをスキップ
    existing = {p.stem for p in CACHE_DIR.glob("*.csv")}
    to_fetch = [t for t in tickers if t not in existing]
    logger.info(f"既存キャッシュ: {len(existing)}銘柄 / 新規取得対象: {len(to_fetch)}銘柄")

    if not to_fetch:
        logger.info("全銘柄キャッシュ済み。終了。")
        return

    success = 0
    fail = 0
    for i, ticker in enumerate(to_fetch, 1):
        yf_ticker = ticker if "." in ticker else f"{ticker}.T"
        try:
            t = yf.Ticker(yf_ticker)
            df = t.history(start=start, interval="1d")
            if df.empty:
                logger.warning(f"[{i}/{len(to_fetch)}] {ticker}: データなし")
                fail += 1
                continue

            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]]
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df.index.name = "date"

            out_path = CACHE_DIR / f"{ticker}.csv"
            df.to_csv(out_path, encoding="utf-8-sig")
            success += 1

            if i % 50 == 0:
                logger.info(f"[{i}/{len(to_fetch)}] 進捗: 成功={success}, 失敗={fail}")
                time.sleep(1)  # rate limit 回避

        except Exception as e:
            logger.warning(f"[{i}/{len(to_fetch)}] {ticker}: 取得失敗 — {e}")
            fail += 1

    logger.info(f"完了: 成功={success}, 失敗={fail}, 合計={success + fail}/{len(to_fetch)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全銘柄株価一括取得")
    parser.add_argument("--start", default="2022-01-01", help="取得開始日 (default: 2022-01-01)")
    args = parser.parse_args()
    fetch_all(start=args.start)
