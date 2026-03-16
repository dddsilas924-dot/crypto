"""ライブポジション管理 - 取引所APIとのポジション同期・ヘルスチェック"""
import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger("empire")

ROUND_TRIP_COST_PCT = 0.22


class LivePositionManager:
    """取引所の実ポジションとDB状態を同期し、ヘルスチェックを行う。"""

    def __init__(self, exchange, db, alert, config: dict, order_executor=None):
        """
        Args:
            exchange: ccxt.async_support.mexc インスタンス
            db: HistoricalDB
            alert: TelegramAlert
            config: settings.yaml の live_execution セクション
            order_executor: OrderExecutor (残存注文キャンセル用)
        """
        self.exchange = exchange
        self.db = db
        self.alert = alert
        self.config = config
        self.order_executor = order_executor

        self._last_sync = None
        self._last_health_check = None
        self._sync_interval = config.get('sync_interval_seconds', 60)
        self._health_check_interval = config.get('health_check_interval_seconds', 300)

    async def sync_positions(self) -> List[dict]:
        """取引所のオープンポジションとDBを同期。
        ポジション決済検出時に残存TP/SL注文をキャンセルする。

        Returns:
            exchange_positions: 取引所の全オープンポジション
        """
        try:
            exchange_positions = await self.exchange.fetch_positions()
            # 数量がある（オープン）ポジションだけ
            open_exchange = []
            for p in exchange_positions:
                try:
                    contracts = float(p.get('contracts', 0) or 0)
                    if contracts > 0:
                        open_exchange.append(p)
                except (TypeError, ValueError):
                    continue

            db_positions = self.db.get_open_positions()
            db_symbols = {p['symbol'] for p in db_positions}
            exchange_symbols = {p['symbol'] for p in open_exchange}

            # 取引所にあるがDBにないポジション（孤児）
            orphaned = exchange_symbols - db_symbols
            for sym in orphaned:
                logger.warning(f"[LivePosMgr] Orphaned position on exchange: {sym} (not in DB)")

            # DBにあるが取引所にないポジション（決済済み）
            stale = db_symbols - exchange_symbols
            for sym in stale:
                for pos in db_positions:
                    if pos['symbol'] == sym and pos['status'] == 'open':
                        logger.info(f"[LivePosMgr] Position closed on exchange: {sym}, updating DB")
                        # 残存TP/SL注文をキャンセル (H2)
                        await self._cancel_stale_orders(pos)
                        # 取引所で決済されたので最終価格を取得して閉じる
                        try:
                            ticker = await self.exchange.fetch_ticker(sym)
                            last_price = ticker.get('last', pos['entry_price'])
                            entry_price = pos['entry_price']
                            leverage = pos['leverage']
                            if pos['side'] == 'long':
                                pnl = ((last_price - entry_price) / entry_price * 100 - ROUND_TRIP_COST_PCT) * leverage
                            else:
                                pnl = ((entry_price - last_price) / entry_price * 100 - ROUND_TRIP_COST_PCT) * leverage
                            self.db.close_position(pos['id'], last_price, round(pnl, 2))
                            # H1: circuit breaker にPnLを反映
                            if self.order_executor:
                                self.order_executor._update_circuit_breaker(round(pnl, 2))
                                logger.info(f"[LivePosMgr] Circuit breaker updated: {sym} pnl={pnl:.2f}%")
                        except Exception as e:
                            logger.error(f"[LivePosMgr] Failed to close stale position {sym}: {e}")
                            self.db.close_position(pos['id'], pos['entry_price'], 0.0)

            # 既存ポジションの価格更新
            for ex_pos in open_exchange:
                sym = ex_pos['symbol']
                for db_pos in db_positions:
                    if db_pos['symbol'] == sym and db_pos['status'] == 'open':
                        mark_price = float(ex_pos.get('markPrice', 0) or 0)
                        if mark_price > 0:
                            entry_price = db_pos['entry_price']
                            leverage = db_pos['leverage']
                            if db_pos['side'] == 'long':
                                pnl = (mark_price - entry_price) / entry_price * 100 * leverage
                            else:
                                pnl = (entry_price - mark_price) / entry_price * 100 * leverage
                            self.db.update_position_price(db_pos['id'], mark_price, round(pnl, 2))

            self._last_sync = datetime.now()
            return open_exchange

        except Exception as e:
            logger.error(f"[LivePosMgr] sync_positions failed: {e}")
            return []

    async def _cancel_stale_orders(self, pos: dict):
        """決済済みポジションの残存TP/SL注文をキャンセル。"""
        symbol = pos['symbol']

        # 方法1: OrderExecutor経由 (メモリ上の_active_orders)
        if self.order_executor:
            try:
                await self.order_executor.cancel_orphaned_orders(symbol)
                return
            except Exception as e:
                logger.warning(f"[LivePosMgr] cancel_orphaned_orders failed for {symbol}: {e}")

        # 方法2: DB上のorder_idで直接キャンセル
        tp_id = pos.get('tp_order_id')
        sl_id = pos.get('sl_order_id')
        cancelled = []
        for label, order_id in [('TP', tp_id), ('SL', sl_id)]:
            if order_id:
                try:
                    await self.exchange.cancel_order(order_id, symbol)
                    cancelled.append(f"{label}={order_id}")
                    logger.info(f"[LivePosMgr] Cancelled stale {label}: {order_id} for {symbol}")
                except Exception as e:
                    logger.warning(f"[LivePosMgr] Failed to cancel stale {label} {order_id}: {e}")
        if cancelled:
            await self.alert.send_message(
                f"🧹 {symbol} 決済済みポジションの残存注文キャンセル: {', '.join(cancelled)}"
            )

    async def check_tp_sl_health(self) -> List[dict]:
        """TP/SL注文がアクティブかチェック。欠落していれば通知。"""
        issues = []
        try:
            open_orders = await self.exchange.fetch_open_orders()
            db_positions = self.db.get_open_positions()

            for pos in db_positions:
                if pos['status'] != 'open':
                    continue
                sym = pos['symbol']

                # この銘柄のオープン注文を確認
                sym_orders = [o for o in open_orders if o['symbol'] == sym]

                # DB上の注文IDで直接チェック
                tp_id = pos.get('tp_order_id')
                sl_id = pos.get('sl_order_id')
                order_ids_on_exchange = {o.get('id') for o in sym_orders}

                has_tp = tp_id in order_ids_on_exchange if tp_id else any(
                    o.get('type') in ('limit',) and o.get('reduceOnly', False)
                    for o in sym_orders
                )
                has_sl = sl_id in order_ids_on_exchange if sl_id else any(
                    o.get('type') in ('stop', 'stop_market', 'stop-limit')
                    or o.get('stopPrice')
                    for o in sym_orders
                )

                if not has_tp:
                    issues.append({'symbol': sym, 'issue': 'missing_tp', 'position_id': pos['id']})
                if not has_sl:
                    issues.append({'symbol': sym, 'issue': 'missing_sl', 'position_id': pos['id']})

            if issues:
                for issue in issues:
                    msg = f"⚠️ {issue['symbol']}: {issue['issue']} — TP/SL注文が取引所にありません!"
                    logger.warning(f"[LivePosMgr] {msg}")
                    await self.alert.send_message(msg)

            self._last_health_check = datetime.now()

        except Exception as e:
            logger.error(f"[LivePosMgr] check_tp_sl_health failed: {e}")

        return issues

    async def get_open_count(self) -> int:
        """取引所のオープンポジション数。"""
        try:
            positions = await self.exchange.fetch_positions()
            return sum(1 for p in positions if p.get('contracts', 0) > 0)
        except Exception as e:
            logger.error(f"[LivePosMgr] get_open_count failed: {e}")
            # fallback to DB
            return len(self.db.get_open_positions())

    async def get_account_summary(self) -> dict:
        """アカウント概要（残高、使用中マージン、未実現PnL）。"""
        try:
            balance = await self.exchange.fetch_balance()
            positions = await self.exchange.fetch_positions()

            usdt_info = balance.get('USDT', {})
            if isinstance(usdt_info, dict):
                free = float(usdt_info.get('free', 0))
                used = float(usdt_info.get('used', 0))
                total = float(usdt_info.get('total', 0))
            else:
                free = float(usdt_info) if usdt_info else 0
                used = 0
                total = free

            total_unrealized = 0.0
            open_count = 0
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    open_count += 1
                    unrealized = float(p.get('unrealizedPnl', 0) or 0)
                    total_unrealized += unrealized

            return {
                'balance_total': round(total, 2),
                'balance_free': round(free, 2),
                'balance_used': round(used, 2),
                'unrealized_pnl': round(total_unrealized, 2),
                'open_positions': open_count,
                'last_sync': self._last_sync.isoformat() if self._last_sync else None,
            }

        except Exception as e:
            logger.error(f"[LivePosMgr] get_account_summary failed: {e}")
            return {
                'balance_total': 0, 'balance_free': 0, 'balance_used': 0,
                'unrealized_pnl': 0, 'open_positions': 0, 'last_sync': None,
                'error': str(e),
            }

    def should_sync(self) -> bool:
        """同期タイミングか判定。"""
        if self._last_sync is None:
            return True
        elapsed = (datetime.now() - self._last_sync).total_seconds()
        return elapsed >= self._sync_interval

    def should_health_check(self) -> bool:
        """TP/SLヘルスチェックタイミングか判定。"""
        if self._last_health_check is None:
            return True
        elapsed = (datetime.now() - self._last_health_check).total_seconds()
        return elapsed >= self._health_check_interval
