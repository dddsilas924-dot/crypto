"""Funding Rate / OI データ収集 — MEXC API実データ + DB蓄積"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger("empire")


class FundingRateCollector:
    """MEXC APIからFR/OI実データを取得・蓄積。
    リアルタイムスキャン（async）とDB読み出し（sync）の両方を提供。
    """

    def __init__(self, exchange, cache=None, db=None):
        self.exchange = exchange  # ccxt async exchange (or None for DB-only)
        self.cache = cache
        self.db = db
        self.cache_ttl = 300  # 5分

    # ========================================
    # リアルタイム取得（async, engine.pyから呼ばれる）
    # ========================================

    async def get_funding_rate(self, symbol: str) -> Optional[dict]:
        """現在のFRを取得（キャッシュ付き）"""
        if self.cache:
            cached = self.cache.get("fr_levburn", symbol)
            if cached is not None:
                return cached

        try:
            funding = await self.exchange.fetch_funding_rate(symbol)
            result = {
                "symbol": symbol,
                "funding_rate": funding.get('fundingRate', 0) or 0,
                "mark_price": funding.get('markPrice', 0) or 0,
                "next_funding_time": funding.get('fundingDatetime'),
                "timestamp": funding.get('datetime') or datetime.now().isoformat(),
            }
            if self.cache:
                self.cache.set("fr_levburn", result, symbol)
            # DBに蓄積
            self._save_fr_to_db(result)
            return result
        except Exception as e:
            err_str = str(e)
            if '510' in err_str or 'too frequent' in err_str.lower():
                await asyncio.sleep(3)
                try:
                    funding = await self.exchange.fetch_funding_rate(symbol)
                    result = {
                        "symbol": symbol,
                        "funding_rate": funding.get('fundingRate', 0) or 0,
                        "mark_price": funding.get('markPrice', 0) or 0,
                        "next_funding_time": funding.get('fundingDatetime'),
                        "timestamp": funding.get('datetime') or datetime.now().isoformat(),
                    }
                    if self.cache:
                        self.cache.set("fr_levburn", result, symbol)
                    self._save_fr_to_db(result)
                    return result
                except Exception:
                    pass
            logger.debug(f"[FR Scan] {symbol}: {e}")
            return None

    async def get_open_interest(self, symbol: str) -> Optional[dict]:
        """OIを取得"""
        if self.cache:
            cached = self.cache.get("oi_levburn", symbol)
            if cached is not None:
                return cached

        try:
            oi_data = await self.exchange.fetch_open_interest(symbol)
            oi_value = oi_data.get('openInterestValue', 0) or 0
            result = {
                "symbol": symbol,
                "open_interest": float(oi_value),
                "oi_change_24h_pct": 0.0,
            }
            if self.cache:
                self.cache.set("oi_levburn", result, symbol)
            return result
        except Exception as e:
            logger.debug(f"[OI Scan] {symbol}: {e}")
            return None

    async def get_futures_spot_ratio(self, symbol: str, futures_volume: float = 0) -> float:
        """先物/現物出来高比率"""
        if futures_volume <= 0:
            return 0.0
        spot_symbol = symbol.replace(':USDT', '')
        try:
            ticker = await self.exchange.fetch_ticker(spot_symbol)
            spot_vol = ticker.get('quoteVolume', 0) or 0
            if spot_vol > 0:
                return futures_volume / spot_vol
            return 0.0
        except Exception:
            return 0.0

    async def scan_symbols(self, symbols: list, tickers: dict = None) -> list:
        """対象銘柄のFR/OIをバッチスキャン（リアルタイム用）"""
        results = []
        for symbol in symbols:
            try:
                fr = await self.get_funding_rate(symbol)
                if fr is None:
                    continue
                await asyncio.sleep(1.5)

                oi = await self.get_open_interest(symbol)
                await asyncio.sleep(1.5)

                futures_vol = 0.0
                if tickers and symbol in tickers:
                    futures_vol = tickers[symbol].get('quoteVolume', 0) or 0

                ratio = await self.get_futures_spot_ratio(symbol, futures_vol)
                await asyncio.sleep(1.0)

                # OIもDBに蓄積（FR行を更新）
                self._update_oi_in_db(fr, oi)

                results.append({
                    "symbol": symbol,
                    "funding_rate": fr["funding_rate"],
                    "open_interest": oi["open_interest"] if oi else 0,
                    "oi_change_24h_pct": oi["oi_change_24h_pct"] if oi else 0,
                    "futures_spot_ratio": ratio,
                    "futures_volume": futures_vol,
                })
            except Exception as e:
                logger.debug(f"[FR Scan] {symbol}: {e}")
        return results

    # ========================================
    # 過去データ一括取得（sync, スクリプトから呼ばれる）
    # ========================================

    def fetch_history(self, symbol: str, since: str = "2024-03-01",
                      until: str = "2026-03-01") -> int:
        """過去FR履歴を全期間取得（ページネーション対応）。
        MEXC: 1回max100件、8hごと（1日3件）。2年分≒730件→8ページ。
        exchange は sync ccxt を想定（スクリプト用）。
        """
        if not self.db or not self.exchange:
            return 0

        since_ts = int(datetime.strptime(since, "%Y-%m-%d").timestamp() * 1000)
        until_ts = int(datetime.strptime(until, "%Y-%m-%d").timestamp() * 1000)

        total_saved = 0
        current_since = since_ts
        max_pages = 20  # 安全上限（2年分なら8ページで十分）
        page = 0

        while current_since < until_ts and page < max_pages:
            try:
                history = self.exchange.fetch_funding_rate_history(
                    symbol, since=current_since, limit=100
                )
                if not history or len(history) == 0:
                    break

                conn = self.db._get_conn()
                for entry in history:
                    # until を超えたら終了
                    if entry.get('timestamp', 0) > until_ts:
                        break
                    fr_val = entry.get('fundingRate', 0)
                    if fr_val is None:
                        fr_val = 0
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO funding_rate_history
                            (symbol, timestamp, funding_rate, mark_price, source)
                            VALUES (?, ?, ?, ?, 'mexc')""",
                            (symbol,
                             entry.get('datetime', ''),
                             float(fr_val),
                             float(entry.get('markPrice', 0) or 0))
                        )
                        total_saved += 1
                    except Exception:
                        pass
                conn.commit()
                conn.close()

                # 次ページ: 最後のエントリのタイムスタンプ + 1ms
                last_ts = history[-1].get('timestamp', 0)
                if last_ts <= current_since:
                    break  # 進んでいなければ無限ループ防止
                current_since = last_ts + 1
                page += 1

                # 100件未満 = 最後のページ
                if len(history) < 100:
                    break

                time.sleep(2.0)

            except Exception as e:
                logger.warning(f"[FR History] {symbol} page {page}: {e}")
                time.sleep(5.0)
                break

        return total_saved

    def fetch_history_batch(self, symbols: list,
                            since: str = "2024-03-01",
                            until: str = "2026-03-01") -> dict:
        """複数銘柄の過去FR一括取得"""
        summary = {}
        for i, symbol in enumerate(symbols):
            count = self.fetch_history(symbol, since, until)
            summary[symbol] = count
            logger.info(f"[FR History] {i+1}/{len(symbols)} {symbol}: {count}件取得")
            time.sleep(2.0)
        return summary

    # ========================================
    # バックテスト用DB読み出し（sync）
    # ========================================

    def get_fr_for_date(self, symbol: str, date: str) -> Optional[dict]:
        """特定日のFRをDBから取得（バックテスト用）"""
        if not self.db:
            return None
        conn = self.db._get_conn()
        row = conn.execute(
            """SELECT funding_rate, mark_price, open_interest
            FROM funding_rate_history
            WHERE symbol = ? AND timestamp LIKE ?
            ORDER BY timestamp DESC LIMIT 1""",
            (symbol, f"{date}%")
        ).fetchone()
        conn.close()

        if row:
            return {
                "funding_rate": row[0],
                "mark_price": row[1],
                "open_interest": row[2],
            }
        return None

    def get_fr_series(self, symbol: str, start: str, end: str) -> list:
        """期間のFR時系列をDBから取得"""
        if not self.db:
            return []
        conn = self.db._get_conn()
        rows = conn.execute(
            """SELECT timestamp, funding_rate, mark_price, open_interest
            FROM funding_rate_history
            WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp""",
            (symbol, start, end)
        ).fetchall()
        conn.close()
        return [
            {"timestamp": r[0], "funding_rate": r[1],
             "mark_price": r[2], "open_interest": r[3]}
            for r in rows
        ]

    def get_fr_count(self, symbol: str = None) -> int:
        """DB内のFR件数"""
        if not self.db:
            return 0
        conn = self.db._get_conn()
        if symbol:
            row = conn.execute(
                "SELECT COUNT(*) FROM funding_rate_history WHERE symbol = ?",
                (symbol,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM funding_rate_history"
            ).fetchone()
        conn.close()
        return row[0] if row else 0

    def get_symbols_with_fr(self) -> list:
        """FR履歴がある銘柄一覧"""
        if not self.db:
            return []
        conn = self.db._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM funding_rate_history ORDER BY symbol"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    # ========================================
    # DB保存ヘルパー
    # ========================================

    def _save_fr_to_db(self, fr: dict):
        """リアルタイムFRデータをDBに蓄積"""
        if not self.db:
            return
        try:
            conn = self.db._get_conn()
            conn.execute(
                """INSERT OR IGNORE INTO funding_rate_history
                (symbol, timestamp, funding_rate, mark_price, source)
                VALUES (?, ?, ?, ?, 'mexc')""",
                (fr["symbol"], fr["timestamp"],
                 fr["funding_rate"], fr.get("mark_price", 0))
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[FR Save] {e}")

    def _update_oi_in_db(self, fr: dict, oi: Optional[dict]):
        """OIデータでFR行を更新"""
        if not self.db or not oi:
            return
        try:
            conn = self.db._get_conn()
            conn.execute(
                """UPDATE funding_rate_history
                SET open_interest = ?
                WHERE symbol = ? AND timestamp = ?""",
                (oi.get("open_interest"), fr["symbol"], fr["timestamp"])
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[OI Update] {e}")
