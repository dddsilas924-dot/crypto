"""WebSocket リアルタイムデータフィード — Multi-Exchange対応

MEXC: ネイティブJSON (wss://contract.mexc.com/edge)
BitMart/Binance/Bybit/OKX: ccxt-pro watchTicker/watchTrades/watchOrderBook

Ticker / Trade / FR / Orderbook をリアルタイム受信し、
1秒足構築とデータキャッシュを提供する基盤モジュール。
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from threading import Thread, Lock

import websockets

logger = logging.getLogger("empire")


# ========================================
# シンボル変換ユーティリティ
# ========================================

def to_futures_symbol(symbol: str) -> str:
    """内部形式 → Futures WS形式
    BTC/USDT:USDT → BTC_USDT
    BTCUSDT → BTC_USDT
    BTC_USDT → BTC_USDT (idempotent)
    """
    if "_" in symbol and ":" not in symbol and "/" not in symbol:
        return symbol  # already futures format
    # CCXT形式: BTC/USDT:USDT
    s = symbol.replace(":USDT", "").replace("/", "_")
    # Spot結合形式: BTCUSDT → BTC_USDT (末尾USDTを分離)
    if "_" not in s and s.endswith("USDT"):
        s = s[:-4] + "_USDT"
    return s


def to_spot_symbol(symbol: str) -> str:
    """内部形式 → Spot WS形式
    BTC/USDT:USDT → BTCUSDT
    BTC_USDT → BTCUSDT

    Spot WS有効化時に使用予定
    """
    s = symbol.replace(":USDT", "").replace("/", "").replace("_", "")
    return s


class MEXCWebSocketFeed:
    """
    MEXC WebSocket 2接続アーキテクチャ
    - Futures WS (JSON): ticker(FR+OI含む), deal, depth, funding.rate
    - Spot WS (Protobuf): 将来用 (disabled by default)
    """

    FUTURES_URL = "wss://contract.mexc.com/edge"
    SPOT_URL = "wss://wbs-api.mexc.com/ws"

    def __init__(self, symbols: list = None, callbacks: dict = None,
                 config: dict = None):
        self.symbols = list(symbols or [])
        self.callbacks = callbacks or {}
        self._config = config or {}
        self._futures_ws = None
        self._spot_ws = None
        self._running = False
        self._thread = None
        self._loop = None
        self._lock = Lock()

        # 設定 (新形式対応 + 後方互換)
        futures_cfg = self._config.get("futures", {})
        self._futures_endpoint = futures_cfg.get("endpoint", self.FUTURES_URL)
        self._futures_ping_interval = futures_cfg.get("ping_interval_sec", 15)
        self._reconnect_delay = futures_cfg.get(
            "reconnect_delay_sec",
            self._config.get("reconnect_delay", 5),
        )
        self._max_reconnect_attempts = futures_cfg.get("max_reconnect_attempts", 10)
        self._max_symbols = self._config.get("max_symbols", 20)
        self._candle_history = self._config.get("candle_history", 3600)
        self._trade_history = self._config.get("trade_history", 1000)

        # Spot (将来用)
        spot_cfg = self._config.get("spot", {})
        self._spot_enabled = spot_cfg.get("enabled", False)

        # データストア
        self._tickers = {}                    # symbol → latest ticker
        self._trades = defaultdict(list)      # symbol → [trade, ...]
        self._orderbooks = {}                 # symbol → orderbook
        self._candles_1s = defaultdict(list)  # symbol → [1s candle, ...]
        self._funding_rates = {}              # symbol → FR data

        # ホットリスト (FR閾値超え銘柄)
        self._hot_symbols = {}  # symbol → {"fr": val, "added_at": ts, "fr_level": str}
        self._fr_threshold = 0.0005   # fr_min default (raw decimal)
        self._fr_strong = 0.0015
        self._fr_extreme = 0.003
        self._hot_timeout = 1800      # 30分タイムアウト
        self._on_hot_add = None       # callback(symbol, info)
        self._on_hot_remove = None    # callback(symbol)

        # 統計
        self._stats = {
            "connected_at": None,
            "messages_received": 0,
            "reconnects": 0,
            "errors": 0,
            "last_message_at": None,
        }

    # ========================================
    # ライフサイクル
    # ========================================

    def start(self):
        """WebSocket接続をバックグラウンドスレッドで開始"""
        if self._running:
            return
        self._running = True
        self._thread = Thread(
            target=self._run_async_loop,
            name="mexc-ws-feed",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[WebSocket] Started for {len(self.symbols)} symbols")

    def stop(self):
        """接続を閉じる"""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("[WebSocket] Stopped")

    @property
    def is_connected(self) -> bool:
        return self._running and self._futures_ws is not None

    # ========================================
    # 銘柄管理
    # ========================================

    def add_symbol(self, symbol: str):
        """動的に銘柄を追加"""
        if symbol in self.symbols:
            return
        if len(self.symbols) >= self._max_symbols:
            logger.warning(f"[WebSocket] Max symbols ({self._max_symbols}) reached, ignoring {symbol}")
            return
        self.symbols.append(symbol)
        if self._running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._subscribe_futures([symbol]), self._loop
            )

    def remove_symbol(self, symbol: str):
        """動的に銘柄を削除"""
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            mexc_sym = to_futures_symbol(symbol)
            # データクリア (両方の形式で試行)
            with self._lock:
                for key in [symbol, mexc_sym]:
                    self._tickers.pop(key, None)
                    self._funding_rates.pop(key, None)
                    self._orderbooks.pop(key, None)
                    self._trades.pop(key, None)
                    self._candles_1s.pop(key, None)

    def subscribe_deal(self, symbol: str):
        """dealストリームを動的に追加購読"""
        mexc_sym = to_futures_symbol(symbol)
        if self._running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._send_sub("sub.deal", mexc_sym), self._loop
            )

    def unsubscribe_deal(self, symbol: str):
        """dealストリームを購読解除"""
        mexc_sym = to_futures_symbol(symbol)
        if self._running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._send_sub("unsub.deal", mexc_sym), self._loop
            )
        # 1秒足・約定キャッシュをクリア
        with self._lock:
            self._trades.pop(mexc_sym, None)
            self._candles_1s.pop(mexc_sym, None)

    async def _send_sub(self, method: str, mexc_symbol: str):
        """汎用subscription送信"""
        if not self._futures_ws:
            return
        try:
            await self._futures_ws.send(json.dumps({
                "method": method,
                "param": {"symbol": mexc_symbol},
            }))
        except Exception as e:
            logger.debug(f"[WebSocket] {method} error for {mexc_symbol}: {e}")

    # ========================================
    # データ取得API
    # ========================================

    def get_ticker(self, symbol: str) -> dict:
        """最新ティッカー"""
        with self._lock:
            t = self._tickers.get(symbol)
            return dict(t) if t else None

    def get_price(self, symbol: str) -> float:
        """最新価格（簡易版）"""
        with self._lock:
            ticker = self._tickers.get(symbol)
            return ticker["last"] if ticker else None

    def get_all_tickers(self) -> dict:
        """全ティッカー"""
        with self._lock:
            return {k: dict(v) for k, v in self._tickers.items()}

    def get_1s_candles(self, symbol: str, count: int = 60) -> list:
        """直近N秒の1秒足"""
        with self._lock:
            return list(self._candles_1s[symbol][-count:])

    def get_recent_trades(self, symbol: str, count: int = 100) -> list:
        """直近N件の約定"""
        with self._lock:
            return list(self._trades[symbol][-count:])

    def get_orderbook(self, symbol: str) -> dict:
        """最新板情報"""
        with self._lock:
            ob = self._orderbooks.get(symbol)
            return dict(ob) if ob else None

    def get_funding_rate(self, symbol: str) -> dict:
        """最新Funding Rate"""
        with self._lock:
            fr = self._funding_rates.get(symbol)
            return dict(fr) if fr else None

    def get_stats(self) -> dict:
        """接続統計"""
        return {
            **self._stats,
            "is_connected": self.is_connected,
            "symbols_count": len(self.symbols),
            "tickers_cached": len(self._tickers),
            "hot_symbols": len(self._hot_symbols),
            "connection_type": "futures_json",
        }

    # ========================================
    # ホットリスト (FR閾値超え銘柄管理)
    # ========================================

    def configure_hot_list(self, fr_min=0.0005, fr_strong=0.0015,
                           fr_extreme=0.003, timeout=1800,
                           on_add=None, on_remove=None):
        """ホットリストのFR閾値・コールバック設定"""
        self._fr_threshold = fr_min
        self._fr_strong = fr_strong
        self._fr_extreme = fr_extreme
        self._hot_timeout = timeout
        self._on_hot_add = on_add
        self._on_hot_remove = on_remove

    def get_hot_symbols(self) -> dict:
        """現在のホットリスト（コピー）"""
        with self._lock:
            return dict(self._hot_symbols)

    def _check_fr_hot(self, symbol: str, fr_val: float):
        """ticker受信時にFR閾値をチェック → ホットリスト追加/削除"""
        abs_fr = abs(fr_val)

        if abs_fr >= self._fr_threshold and fr_val != 0:
            # FR閾値超え → ホットリストに追加
            if abs_fr >= self._fr_extreme:
                level = "extreme"
            elif abs_fr >= self._fr_strong:
                level = "strong"
            else:
                level = "min"

            with self._lock:
                is_new = symbol not in self._hot_symbols
                self._hot_symbols[symbol] = {
                    "fr": fr_val,
                    "added_at": time.time(),
                    "fr_level": level,
                }

            if is_new and self._on_hot_add:
                try:
                    self._on_hot_add(symbol, self._hot_symbols[symbol])
                except Exception:
                    pass
        else:
            # FR正常化 → ホットリストから削除
            with self._lock:
                was_hot = symbol in self._hot_symbols
                self._hot_symbols.pop(symbol, None)

            if was_hot and self._on_hot_remove:
                try:
                    self._on_hot_remove(symbol)
                except Exception:
                    pass

    def cleanup_hot_timeout(self):
        """タイムアウトしたホットリスト銘柄を削除"""
        now = time.time()
        expired = []
        with self._lock:
            for sym, info in list(self._hot_symbols.items()):
                if now - info["added_at"] > self._hot_timeout:
                    expired.append(sym)
                    del self._hot_symbols[sym]

        for sym in expired:
            if self._on_hot_remove:
                try:
                    self._on_hot_remove(sym)
                except Exception:
                    pass
        return expired

    # ========================================
    # Futures WebSocket (JSON) — メイン
    # ========================================

    def _run_async_loop(self):
        """スレッド内でasyncioループを実行"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._futures_connect_loop())
        except Exception:
            pass
        finally:
            self._loop.close()

    async def _futures_connect_loop(self):
        """Futures WS 自動再接続ループ"""
        attempt = 0

        while self._running:
            try:
                async with websockets.connect(
                    self._futures_endpoint,
                    ping_interval=None,  # 手動ping管理
                    ping_timeout=None,
                    close_timeout=5,
                ) as ws:
                    self._futures_ws = ws
                    self._stats["connected_at"] = datetime.now().isoformat()
                    attempt = 0  # reset on successful connect
                    logger.info(f"[WebSocket] Futures connected: {self._futures_endpoint}")

                    # サブスクリプション
                    await self._subscribe_futures(self.symbols)

                    # Pingタスク + 受信ループを並行実行
                    ping_task = asyncio.ensure_future(self._futures_ping_loop(ws))
                    try:
                        async for message in ws:
                            if not self._running:
                                break
                            self._process_message(message)
                    finally:
                        ping_task.cancel()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                self._stats["reconnects"] += 1
                self._futures_ws = None
                attempt += 1

                if attempt >= self._max_reconnect_attempts:
                    logger.error(f"[WebSocket] Max reconnect attempts ({self._max_reconnect_attempts}) reached")
                    attempt = 0  # reset and keep trying

                if not self._running:
                    break

                delay = min(self._reconnect_delay * (1.5 ** min(attempt, 6)), 60)
                logger.warning(f"[WebSocket] Disconnected: {e}, reconnecting in {delay:.0f}s (attempt {attempt})")
                await asyncio.sleep(delay)

    async def _futures_ping_loop(self, ws):
        """Futures WS ping送信ループ (10-20秒間隔)"""
        try:
            while self._running:
                await asyncio.sleep(self._futures_ping_interval)
                try:
                    await ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _subscribe_futures(self, symbols: list):
        """Futures チャンネル登録: ticker + deal + depth + funding.rate"""
        if not self._futures_ws or not symbols:
            return

        for symbol in symbols:
            mexc_symbol = to_futures_symbol(symbol)

            try:
                # Ticker (lastPrice, FR, OI, bid/ask 含む)
                await self._futures_ws.send(json.dumps({
                    "method": "sub.ticker",
                    "param": {"symbol": mexc_symbol},
                }))

                # Trade（約定 → 1秒足構築）
                await self._futures_ws.send(json.dumps({
                    "method": "sub.deal",
                    "param": {"symbol": mexc_symbol},
                }))

                # Funding Rate 変更通知
                await self._futures_ws.send(json.dumps({
                    "method": "sub.funding.rate",
                    "param": {"symbol": mexc_symbol},
                }))

                # Orderbook（板）
                await self._futures_ws.send(json.dumps({
                    "method": "sub.depth",
                    "param": {"symbol": mexc_symbol},
                }))

                await asyncio.sleep(0.1)
            except Exception as e:
                logger.debug(f"[WebSocket] Subscribe error for {symbol}: {e}")

    # ========================================
    # メッセージ処理
    # ========================================

    def _process_message(self, raw: str):
        """受信メッセージの振り分け"""
        self._stats["messages_received"] += 1
        self._stats["last_message_at"] = datetime.now().isoformat()

        try:
            data = json.loads(raw)

            # Pong応答はスキップ
            if data.get("channel") == "pong" or data.get("data") == "pong":
                return

            channel = data.get("channel", "")

            if "ticker" in channel:
                self._handle_ticker(data)
            elif "deal" in channel:
                self._handle_trade(data)
            elif "depth" in channel:
                self._handle_orderbook(data)
            elif "funding.rate" in channel:
                self._handle_funding_rate(data)

        except Exception as e:
            logger.debug(f"[WebSocket] Parse error: {e}")

    def _handle_ticker(self, data):
        """Futures ティッカー更新 (FR, OI 含む)"""
        d = data.get("data", {})
        symbol = data.get("symbol", "")

        ticker = {
            "symbol": symbol,
            "last": float(d.get("lastPrice", 0)),
            "bid": float(d.get("bid1", 0)),
            "ask": float(d.get("ask1", 0)),
            "volume_24h": float(d.get("volume24", 0)),
            "change_24h": float(d.get("riseFallRate", 0)),
            "funding_rate": float(d.get("fundingRate", 0)),
            "open_interest": float(d.get("holdVol", 0)),
            "fair_price": float(d.get("fairPrice", 0)),
            "index_price": float(d.get("indexPrice", 0)),
            "timestamp": d.get("timestamp", int(time.time() * 1000)),
        }

        with self._lock:
            self._tickers[symbol] = ticker

            # FR も同時更新（tickerにFR含まれる）
            fr_val = ticker["funding_rate"]
            if fr_val != 0:
                self._funding_rates[symbol] = {
                    "funding_rate": fr_val,
                    "timestamp": ticker["timestamp"],
                }

        # FRホットリスト判定（追加負荷ほぼ0）
        self._check_fr_hot(symbol, ticker["funding_rate"])

        if "on_ticker" in self.callbacks:
            try:
                self.callbacks["on_ticker"](symbol, ticker)
            except Exception:
                pass

    def _handle_trade(self, data):
        """約定データ → 1秒足構築

        MEXC Futures sends: {"data":[{"p":price,"v":vol,"T":side,"t":ts},...]}
        Backward compat: dict format also accepted (for tests).
        """
        raw = data.get("data", {})
        symbol = data.get("symbol", "")

        # Normalize to list (MEXC sends array, tests may send dict)
        if isinstance(raw, dict):
            items = [raw]
        elif isinstance(raw, list):
            items = raw
        else:
            return

        for d in items:
            ts_ms = d.get("t", 0)
            trade = {
                "price": float(d.get("p", 0)),
                "amount": float(d.get("v", 0)),
                "side": "buy" if d.get("T", 1) == 1 else "sell",
                "timestamp": ts_ms / 1000 if ts_ms > 1e12 else time.time(),
            }

            if trade["price"] <= 0:
                continue

            with self._lock:
                self._trades[symbol].append(trade)
                if len(self._trades[symbol]) > self._trade_history:
                    self._trades[symbol] = self._trades[symbol][-self._trade_history:]

                self._build_1s_candle(symbol, trade)

            if "on_trade" in self.callbacks:
                try:
                    self.callbacks["on_trade"](symbol, trade)
                except Exception:
                    pass

    def _build_1s_candle(self, symbol: str, trade: dict):
        """約定データから1秒足を構築"""
        current_second = int(trade["timestamp"])
        candles = self._candles_1s[symbol]

        if candles and candles[-1]["timestamp"] == current_second:
            c = candles[-1]
            c["high"] = max(c["high"], trade["price"])
            c["low"] = min(c["low"], trade["price"])
            c["close"] = trade["price"]
            c["volume"] += trade["amount"]
            c["trade_count"] += 1
        else:
            candles.append({
                "timestamp": current_second,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": trade["amount"],
                "trade_count": 1,
            })
            if len(candles) > self._candle_history:
                self._candles_1s[symbol] = candles[-self._candle_history:]

    def _handle_orderbook(self, data):
        """板情報更新"""
        d = data.get("data", {})
        symbol = data.get("symbol", "")
        with self._lock:
            self._orderbooks[symbol] = {
                "bids": d.get("bids", []),
                "asks": d.get("asks", []),
                "timestamp": time.time(),
            }

    def _handle_funding_rate(self, data):
        """Funding Rate 変更通知"""
        d = data.get("data", {})
        symbol = data.get("symbol", "")

        fr_entry = {
            "funding_rate": float(d.get("fundingRate", 0)),
            "next_settle_time": d.get("nextSettleTime", 0),
            "timestamp": d.get("timestamp", int(time.time() * 1000)),
        }
        with self._lock:
            self._funding_rates[symbol] = fr_entry

        if "on_funding_rate" in self.callbacks:
            try:
                self.callbacks["on_funding_rate"](symbol, fr_entry)
            except Exception:
                pass


# ========================================
# ccxt-pro WebSocket Feed (BitMart / Binance / Bybit / OKX)
# ========================================

class CcxtProWebSocketFeed:
    """ccxt-pro ベースの汎用 WebSocket フィード。
    MEXCWebSocketFeed と同じ公開APIを提供し、取引所を意識せず使える。
    """

    def __init__(self, symbols: list = None, callbacks: dict = None,
                 config: dict = None, exchange_name: str = 'bitmart'):
        self.symbols = list(symbols or [])
        self.callbacks = callbacks or {}
        self._config = config or {}
        self._exchange_name = exchange_name
        self._running = False
        self._thread = None
        self._loop = None
        self._lock = Lock()
        self._ccxt_ws = None  # ccxt.pro exchange instance

        self._max_symbols = self._config.get("max_symbols", 20)
        self._candle_history = self._config.get("candle_history", 3600)
        self._trade_history = self._config.get("trade_history", 1000)
        self._reconnect_delay = self._config.get("reconnect_delay", 5)

        # データストア (MEXCWebSocketFeed互換)
        self._tickers = {}
        self._trades = defaultdict(list)
        self._orderbooks = {}
        self._candles_1s = defaultdict(list)
        self._funding_rates = {}

        # ホットリスト
        self._hot_symbols = {}
        self._fr_threshold = 0.0005
        self._fr_strong = 0.0015
        self._fr_extreme = 0.003
        self._hot_timeout = 1800
        self._on_hot_add = None
        self._on_hot_remove = None

        # 統計
        self._stats = {
            "connected_at": None,
            "messages_received": 0,
            "reconnects": 0,
            "errors": 0,
            "last_message_at": None,
        }

    # ── ライフサイクル ──

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = Thread(
            target=self._run_async_loop,
            name=f"{self._exchange_name}-ws-feed",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[WebSocket] CcxtPro started for {self._exchange_name} ({len(self.symbols)} symbols)")

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        # Close ccxt ws exchange
        if self._ccxt_ws:
            try:
                asyncio.run_coroutine_threadsafe(self._ccxt_ws.close(), self._loop)
            except Exception:
                pass
        logger.info(f"[WebSocket] CcxtPro {self._exchange_name} stopped")

    @property
    def is_connected(self) -> bool:
        return self._running and self._stats.get("connected_at") is not None

    # ── 銘柄管理 ──

    def add_symbol(self, symbol: str):
        if symbol in self.symbols:
            return
        if len(self.symbols) >= self._max_symbols:
            return
        self.symbols.append(symbol)

    def remove_symbol(self, symbol: str):
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            with self._lock:
                for store in [self._tickers, self._funding_rates, self._orderbooks,
                              self._trades, self._candles_1s]:
                    if isinstance(store, dict):
                        store.pop(symbol, None)

    def subscribe_deal(self, symbol: str):
        pass  # ccxt-pro handles subscriptions automatically

    def unsubscribe_deal(self, symbol: str):
        with self._lock:
            self._trades.pop(symbol, None)
            self._candles_1s.pop(symbol, None)

    # ── データ取得API (MEXCWebSocketFeed互換) ──

    def get_ticker(self, symbol: str) -> dict:
        with self._lock:
            t = self._tickers.get(symbol)
            return dict(t) if t else None

    def get_price(self, symbol: str) -> float:
        with self._lock:
            ticker = self._tickers.get(symbol)
            return ticker["last"] if ticker else None

    def get_all_tickers(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._tickers.items()}

    def get_1s_candles(self, symbol: str, count: int = 60) -> list:
        with self._lock:
            return list(self._candles_1s[symbol][-count:])

    def get_recent_trades(self, symbol: str, count: int = 100) -> list:
        with self._lock:
            return list(self._trades[symbol][-count:])

    def get_orderbook(self, symbol: str) -> dict:
        with self._lock:
            ob = self._orderbooks.get(symbol)
            return dict(ob) if ob else None

    def get_funding_rate(self, symbol: str) -> dict:
        with self._lock:
            fr = self._funding_rates.get(symbol)
            return dict(fr) if fr else None

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "is_connected": self.is_connected,
            "symbols_count": len(self.symbols),
            "tickers_cached": len(self._tickers),
            "hot_symbols": len(self._hot_symbols),
            "connection_type": f"ccxt_pro_{self._exchange_name}",
        }

    # ── ホットリスト ──

    def configure_hot_list(self, fr_min=0.0005, fr_strong=0.0015,
                           fr_extreme=0.003, timeout=1800,
                           on_add=None, on_remove=None):
        self._fr_threshold = fr_min
        self._fr_strong = fr_strong
        self._fr_extreme = fr_extreme
        self._hot_timeout = timeout
        self._on_hot_add = on_add
        self._on_hot_remove = on_remove

    def get_hot_symbols(self) -> dict:
        with self._lock:
            return dict(self._hot_symbols)

    def cleanup_hot_timeout(self):
        now = time.time()
        expired = []
        with self._lock:
            for sym, info in list(self._hot_symbols.items()):
                if now - info["added_at"] > self._hot_timeout:
                    expired.append(sym)
                    del self._hot_symbols[sym]
        for sym in expired:
            if self._on_hot_remove:
                try:
                    self._on_hot_remove(sym)
                except Exception:
                    pass
        return expired

    def _check_fr_hot(self, symbol: str, fr_val: float):
        abs_fr = abs(fr_val)
        if abs_fr >= self._fr_threshold and fr_val != 0:
            level = "extreme" if abs_fr >= self._fr_extreme else (
                "strong" if abs_fr >= self._fr_strong else "min")
            with self._lock:
                is_new = symbol not in self._hot_symbols
                self._hot_symbols[symbol] = {
                    "fr": fr_val, "added_at": time.time(), "fr_level": level,
                }
            if is_new and self._on_hot_add:
                try:
                    self._on_hot_add(symbol, self._hot_symbols[symbol])
                except Exception:
                    pass
        else:
            with self._lock:
                was_hot = symbol in self._hot_symbols
                self._hot_symbols.pop(symbol, None)
            if was_hot and self._on_hot_remove:
                try:
                    self._on_hot_remove(symbol)
                except Exception:
                    pass

    # ── 内部: ccxt-pro接続ループ ──

    def _run_async_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._watch_loop())
        except Exception:
            pass
        finally:
            self._loop.close()

    async def _watch_loop(self):
        """ccxt-pro の watchTicker/watchTrades を並行実行"""
        try:
            import ccxt.pro as ccxt_pro
        except ImportError:
            logger.error("[WebSocket] ccxt.pro not installed. Run: pip install ccxt[pro]")
            return

        exchange_class = getattr(ccxt_pro, self._exchange_name, None)
        if not exchange_class:
            logger.error(f"[WebSocket] ccxt.pro does not support: {self._exchange_name}")
            return

        self._ccxt_ws = exchange_class({
            'options': {'defaultType': 'swap'},
            'enableRateLimit': True,
        })

        self._stats["connected_at"] = datetime.now().isoformat()
        logger.info(f"[WebSocket] CcxtPro {self._exchange_name} watch loop started")

        # 各シンボルの watchTicker を並行実行
        tasks = []
        for symbol in self.symbols:
            tasks.append(asyncio.ensure_future(self._watch_ticker(symbol)))
            tasks.append(asyncio.ensure_future(self._watch_trades(symbol)))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WebSocket] CcxtPro watch loop error: {e}")
            self._stats["errors"] += 1
        finally:
            try:
                await self._ccxt_ws.close()
            except Exception:
                pass

    async def _watch_ticker(self, symbol: str):
        """単一シンボルの watchTicker ループ"""
        while self._running:
            try:
                ticker = await self._ccxt_ws.watch_ticker(symbol)
                self._stats["messages_received"] += 1
                self._stats["last_message_at"] = datetime.now().isoformat()

                # ccxt unified ticker → 内部形式に変換
                internal = {
                    "symbol": symbol,
                    "last": float(ticker.get("last", 0) or 0),
                    "bid": float(ticker.get("bid", 0) or 0),
                    "ask": float(ticker.get("ask", 0) or 0),
                    "volume_24h": float(ticker.get("quoteVolume", 0) or 0),
                    "change_24h": float(ticker.get("percentage", 0) or 0) / 100,
                    "funding_rate": 0,  # FR is not in ccxt ticker
                    "open_interest": 0,
                    "fair_price": 0,
                    "index_price": 0,
                    "timestamp": ticker.get("timestamp", int(time.time() * 1000)),
                }

                with self._lock:
                    self._tickers[symbol] = internal

                if "on_ticker" in self.callbacks:
                    try:
                        self.callbacks["on_ticker"](symbol, internal)
                    except Exception:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.debug(f"[WebSocket] watchTicker error {symbol}: {e}")
                await asyncio.sleep(self._reconnect_delay)

    async def _watch_trades(self, symbol: str):
        """単一シンボルの watchTrades ループ → 1秒足構築"""
        while self._running:
            try:
                trades = await self._ccxt_ws.watch_trades(symbol)
                self._stats["messages_received"] += 1
                self._stats["last_message_at"] = datetime.now().isoformat()

                for t in trades:
                    trade = {
                        "price": float(t.get("price", 0)),
                        "amount": float(t.get("amount", 0)),
                        "side": t.get("side", "buy"),
                        "timestamp": (t.get("timestamp", 0) or 0) / 1000,
                    }
                    if trade["price"] <= 0:
                        continue

                    with self._lock:
                        self._trades[symbol].append(trade)
                        if len(self._trades[symbol]) > self._trade_history:
                            self._trades[symbol] = self._trades[symbol][-self._trade_history:]
                        self._build_1s_candle(symbol, trade)

                    if "on_trade" in self.callbacks:
                        try:
                            self.callbacks["on_trade"](symbol, trade)
                        except Exception:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.debug(f"[WebSocket] watchTrades error {symbol}: {e}")
                await asyncio.sleep(self._reconnect_delay)

    def _build_1s_candle(self, symbol: str, trade: dict):
        """約定データから1秒足を構築 (MEXCWebSocketFeed互換)"""
        current_second = int(trade["timestamp"])
        candles = self._candles_1s[symbol]

        if candles and candles[-1]["timestamp"] == current_second:
            c = candles[-1]
            c["high"] = max(c["high"], trade["price"])
            c["low"] = min(c["low"], trade["price"])
            c["close"] = trade["price"]
            c["volume"] += trade["amount"]
            c["trade_count"] += 1
        else:
            candles.append({
                "timestamp": current_second,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": trade["amount"],
                "trade_count": 1,
            })
            if len(candles) > self._candle_history:
                self._candles_1s[symbol] = candles[-self._candle_history:]


# ========================================
# WebSocket Feed ファクトリ
# ========================================

def create_ws_feed(symbols: list = None, callbacks: dict = None,
                   config: dict = None, exchange_name: str = 'mexc'):
    """取引所名に応じて適切な WebSocket Feed を生成。

    Args:
        exchange_name: 'mexc' → MEXCWebSocketFeed, その他 → CcxtProWebSocketFeed
    """
    if exchange_name == 'mexc':
        return MEXCWebSocketFeed(symbols=symbols, callbacks=callbacks, config=config)
    else:
        return CcxtProWebSocketFeed(
            symbols=symbols, callbacks=callbacks, config=config,
            exchange_name=exchange_name,
        )
