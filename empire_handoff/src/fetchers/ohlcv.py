"""CCXT経由のOHLCV・市場データ取得（キャッシュ統合）"""
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from typing import Optional, List
import asyncio
import aiohttp
import os
import yaml
from dotenv import load_dotenv
from src.exchange.exchange_factory import create_exchange

load_dotenv()

class MEXCFetcher:
    def __init__(self, cache=None, exchange_config: dict = None):
        if exchange_config:
            self.exchange = create_exchange(exchange_config)
        else:
            # 後方互換: exchange_config未指定時はsettings.yamlから読み込み
            try:
                with open('config/settings.yaml', 'r') as f:
                    cfg = yaml.safe_load(f)
                self.exchange = create_exchange(cfg.get('exchange', {'name': 'mexc'}))
            except Exception:
                # フォールバック: 従来のMEXC直接初期化
                self.exchange = ccxt.mexc({
                    'apiKey': os.getenv('MEXC_API_KEY'),
                    'secret': os.getenv('MEXC_API_SECRET'),
                    'options': {'defaultType': 'swap'},
                    'enableRateLimit': True,
                    'aiohttp_trust_env': True,
                })
                self.exchange.session = aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(resolver=aiohttp.resolver.ThreadedResolver())
                )
        self.cache = cache

    async def close(self):
        await self.exchange.close()

    async def fetch_futures_symbols(self) -> List[str]:
        # ファイルキャッシュチェック
        if self.cache:
            cached = self.cache.file_get("mexc_futures")
            if cached:
                return cached

        markets = await self.exchange.load_markets()
        symbols = [
            s for s, m in markets.items()
            if m.get('swap') and m.get('active') and ':USDT' in s
        ]
        result = sorted(symbols)

        if self.cache:
            self.cache.file_set("mexc_futures", result)

        return result

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 200) -> Optional[pd.DataFrame]:
        try:
            data = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data:
                return None
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            print(f"[OHLCV Error] {symbol}: {e}")
            return None

    async def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        # メモリキャッシュチェック
        if self.cache:
            cached = self.cache.get("funding_rate", symbol)
            if cached is not None:
                return cached

        try:
            funding = await self.exchange.fetch_funding_rate(symbol)
            rate = funding.get('fundingRate')
            if self.cache and rate is not None:
                self.cache.set("funding_rate", rate, symbol)
            return rate
        except Exception:
            return None

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Optional[dict]:
        import logging
        logger = logging.getLogger("empire")

        # メモリキャッシュチェック（TTL=1時間）
        if self.cache:
            cached = self.cache.get("orderbook", symbol)
            if cached is not None:
                return cached

        for attempt in range(2):  # 初回 + 1リトライ
            try:
                ob = await self.exchange.fetch_order_book(symbol, limit)
                bids = ob.get('bids', [])
                asks = ob.get('asks', [])
                if not bids or not asks:
                    return None
                bid_depth = sum(entry[0] * entry[1] for entry in bids[:limit])
                ask_depth = sum(entry[0] * entry[1] for entry in asks[:limit])
                result = {
                    'bid_depth_usd': bid_depth,
                    'ask_depth_usd': ask_depth,
                    'total_depth_usd': bid_depth + ask_depth,
                    'spread_pct': ((asks[0][0] - bids[0][0]) / bids[0][0] * 100) if bids[0][0] > 0 else None
                }
                if self.cache:
                    self.cache.set("orderbook", result, symbol)
                return result
            except Exception as e:
                err_str = str(e)
                if '510' in err_str or 'too frequent' in err_str.lower():
                    if attempt == 0:
                        await asyncio.sleep(3)  # 510: 3秒待ってリトライ
                        continue
                    logger.debug(f"[Orderbook] {symbol}: rate limited, skip")
                    return None
                logger.debug(f"[Orderbook] {symbol}: {e}")
                return None

    async def fetch_ticker(self, symbol: str) -> Optional[dict]:
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception:
            return None

    async def fetch_all_tickers(self) -> dict:
        # メモリキャッシュチェック
        if self.cache:
            cached = self.cache.get("tickers")
            if cached is not None:
                return cached

        try:
            tickers = await self.exchange.fetch_tickers()
            result = {s: t for s, t in tickers.items() if ':USDT' in s}
            if self.cache:
                self.cache.set("tickers", result)
            return result
        except Exception:
            return {}
