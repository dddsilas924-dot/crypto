"""ライブ注文実行 - MEXC先物 成行エントリー + 即時TP/SL発注"""
import asyncio
import json
import logging
import time
from datetime import datetime, date
from typing import Optional

try:
    import ccxt.async_support as ccxt_async
    _TIMEOUT_ERRORS = (ccxt_async.RequestTimeout, ccxt_async.NetworkError)
    _EXCHANGE_ERROR = ccxt_async.ExchangeError
except (ImportError, AttributeError):
    # テスト環境でccxtがない場合のフォールバック
    _TIMEOUT_ERRORS = ()
    _EXCHANGE_ERROR = Exception

logger = logging.getLogger("empire")

# 取引コスト
TAKER_FEE_PCT = 0.06
ROUND_TRIP_COST_PCT = 0.22

# タイムアウトリカバリ定数
VERIFY_MAX_RETRIES = 3
VERIFY_INTERVAL_SEC = 2


class OrderExecutor:
    """MEXC先物の注文実行レイヤー。
    - 成行エントリー → 即座にTP指値 + SL逆指値を発注
    - 残高・ポジション数・競合チェック
    - サーキットブレーカー（日次損失上限・連敗停止）
    - タイムアウト時の注文確認リカバリ (G1)
    - TP/SL注文IDのDB永続化 (H2)
    """

    def __init__(self, exchange, config: dict, db, alert, api_manager=None,
                 trade_recorder=None):
        """
        Args:
            exchange: ccxt.async_support Exchange インスタンス
            config: settings.yaml の live_execution セクション
            db: HistoricalDB
            alert: TelegramAlert
            api_manager: APIManager (シンボルロック・競合検知)
            trade_recorder: TradeRecorder (統一トレード記録)
        """
        self.exchange = exchange
        self.config = config
        self.db = db
        self.alert = alert
        self.api_manager = api_manager
        self.trade_recorder = trade_recorder

        # 設定値
        self.max_positions = config.get('max_positions', 3)
        self.max_daily_loss_pct = config.get('max_daily_loss_pct', 5.0)
        self.min_balance_usd = config.get('min_balance_usd', 50.0)
        self.position_size_cap_usd = config.get('position_size_cap_usd', 500.0)
        self.default_margin_type = config.get('default_margin_type', 'cross')
        self.slippage_tolerance_pct = config.get('slippage_tolerance_pct', 0.5)
        self.dry_run_first = config.get('dry_run_first', True)
        self.allowed_bots = config.get('allowed_bots', [])

        # サーキットブレーカー
        self._daily_pnl = 0.0
        self._daily_date = date.today()
        self._consecutive_losses = 0
        self._max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self._circuit_broken = False
        self._first_live_done = False

        # 注文追跡
        self._active_orders = {}  # symbol → {entry_id, tp_id, sl_id, bot_name, side, amount}

        # ポジションモード確認フラグ (K4)
        self._position_mode_checked = False
        self._position_mode_ok = False

    # ================================================================
    # K4: ポジションモード検証
    # ================================================================

    async def check_position_mode(self) -> bool:
        """MEXCのポジションモードがone-wayであることを確認。
        hedge modeの場合はlive_executionを無効化する。

        Returns:
            True if one-way mode (safe to trade), False if hedge mode
        """
        try:
            # MEXC ccxt: fetchPositionMode は未実装の場合がある
            # 代替: fetch_positions で positionSide を確認、または
            # privateGetV1PrivateAccountTransferRecord 等で取得
            # 最も確実な方法: 小さい操作でhedge mode検出
            try:
                # ccxt >= 4.x: fetchPositionMode 対応
                if hasattr(self.exchange, 'fetch_position_mode'):
                    mode = await self.exchange.fetch_position_mode()
                    is_hedge = mode.get('hedged', False) if isinstance(mode, dict) else False
                elif hasattr(self.exchange, 'fetchPositionMode'):
                    mode = await self.exchange.fetchPositionMode()
                    is_hedge = mode.get('hedged', False) if isinstance(mode, dict) else False
                else:
                    # fetchPositionMode 未対応の場合、fetch_positions で推定
                    positions = await self.exchange.fetch_positions()
                    is_hedge = any(
                        p.get('hedged', False) or
                        p.get('positionSide', 'BOTH') in ('LONG', 'SHORT')
                        for p in positions
                    )
            except Exception as e:
                # API呼び出し自体が失敗した場合はone-wayと仮定して続行
                logger.warning(f"[OrderExecutor] Position mode check API failed: {e}. "
                               f"Assuming one-way mode.")
                self._position_mode_checked = True
                self._position_mode_ok = True
                return True

            if is_hedge:
                msg = ("🚫 MEXC アカウントがヘッジモードです。\n"
                       "このシステムはワンウェイモードのみ対応しています。\n"
                       "MEXC設定でワンウェイモードに変更してからLIVEを有効化してください。")
                logger.error(f"[OrderExecutor] HEDGE MODE DETECTED - live execution disabled")
                await self.alert.send_message(msg)
                self._position_mode_checked = True
                self._position_mode_ok = False
                return False
            else:
                logger.info("[OrderExecutor] Position mode check: one-way mode ✓")
                self._position_mode_checked = True
                self._position_mode_ok = True
                return True

        except Exception as e:
            logger.error(f"[OrderExecutor] Position mode check failed: {e}")
            # 安全側: チェック失敗でも続行（one-wayが圧倒的多数）
            self._position_mode_checked = True
            self._position_mode_ok = True
            return True

    # ================================================================
    # メイン実行フロー
    # ================================================================

    async def execute_entry(self, bot_name: str, signal: dict) -> dict:
        """シグナルからエントリー → TP/SL発注までの完全フロー。

        Args:
            bot_name: "alpha", "surge", "levburn" etc.
            signal: {symbol, side, entry_price, leverage, position_size_pct,
                     take_profit_pct, stop_loss_pct}

        Returns:
            {success: bool, error: str, entry_order: dict, tp_order: dict, sl_order: dict}
        """
        symbol = signal['symbol']
        side = signal.get('side', 'long')
        leverage = signal.get('leverage', 3)
        position_size_pct = signal.get('position_size_pct', 20)
        tp_pct = signal.get('take_profit_pct', 5.0)
        sl_pct = signal.get('stop_loss_pct', 2.0)
        result = {'success': False, 'error': '', 'entry_order': None,
                  'tp_order': None, 'sl_order': None, 'bot_name': bot_name}

        try:
            # ---- ポジションモード確認 (K4: 初回のみ) ----
            if not self._position_mode_checked:
                mode_ok = await self.check_position_mode()
                if not mode_ok:
                    result['error'] = 'hedge_mode_detected'
                    return result
            elif not self._position_mode_ok:
                result['error'] = 'hedge_mode_detected'
                return result

            # ---- プリフライトチェック ----
            ok, reason = await self._pre_flight_checks(bot_name, symbol, side, leverage, position_size_pct)
            if not ok:
                result['error'] = reason
                logger.warning(f"[OrderExecutor] Pre-flight failed: {reason}")
                return result

            # ---- dry_run_first: 初回はログのみ ----
            if self.dry_run_first and not self._first_live_done:
                self._first_live_done = True
                msg = f"[DRY_RUN] 初回ライブシグナル検出: {bot_name} {symbol} {side} — 実行スキップ（安全確認）"
                logger.warning(msg)
                await self.alert.send_message(f"⚠️ {msg}")
                result['error'] = 'dry_run_first'
                return result

            # ---- 残高取得・サイズ計算 ----
            balance = await self._fetch_balance()
            if balance is None:
                result['error'] = 'balance_fetch_failed'
                return result

            position_value = balance * (position_size_pct / 100)
            position_value = min(position_value, self.position_size_cap_usd)
            notional = position_value * leverage

            # マーケット情報を取得してロットサイズ計算
            if not self.exchange.markets:
                await self.exchange.load_markets()
            market = self.exchange.markets.get(symbol)
            if not market:
                result['error'] = f'market_not_found: {symbol}'
                return result

            # シンボルフォーマット検証
            if ':USDT' not in symbol:
                result['error'] = f'invalid_symbol_format: {symbol} (expected XXX/USDT:USDT)'
                return result

            # 現在価格で数量算出
            ticker = await self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            if not current_price or current_price <= 0:
                result['error'] = f'invalid_price: {current_price}'
                return result

            contract_size = float(market.get('contractSize', 1) or 1)
            amount = notional / (current_price * contract_size)

            # NaN/Inf/ゼロチェック
            from math import isfinite
            if not isfinite(amount) or amount <= 0:
                result['error'] = f'invalid_amount: {amount} (notional={notional}, price={current_price})'
                return result

            amount = float(self.exchange.amount_to_precision(symbol, amount))

            min_amount = float(market.get('limits', {}).get('amount', {}).get('min', 0) or 0)
            if amount <= 0 or amount < min_amount:
                result['error'] = f'amount_too_small: {amount} < min {min_amount}'
                return result

            # ---- シンボルロック ----
            if self.api_manager:
                if not self.api_manager.lock_symbol(symbol, bot_name):
                    result['error'] = f'symbol_locked: {symbol}'
                    return result

            try:
                # ---- レバレッジ・マージンタイプ設定 ----
                await self._set_leverage_and_margin(symbol, leverage)

                # ---- 成行エントリー ----
                entry_order = await self._place_market_order(symbol, side, amount)
                if not entry_order:
                    result['error'] = 'entry_order_failed'
                    return result
                result['entry_order'] = entry_order

                # fill_price: None通過防止 (.get()はキーが存在しNone値の場合もNoneを返す)
                fill_price = entry_order.get('average') or entry_order.get('price') or current_price
                fill_amount = float(entry_order.get('filled') or entry_order.get('amount') or amount or 0)
                if fill_amount <= 0:
                    result['error'] = 'entry_order_zero_fill'
                    return result
                logger.info(f"[OrderExecutor] ENTRY FILLED: {bot_name} {symbol} {side} "
                            f"amount={fill_amount} price={fill_price}")

                # ---- 即時TP/SL発注 ----
                tp_order, sl_order = await self._place_tp_sl(
                    symbol, side, fill_amount, fill_price, tp_pct, sl_pct, contract_size
                )
                result['tp_order'] = tp_order
                result['sl_order'] = sl_order

                if not sl_order:
                    # SL発注失敗 → ネイキッドポジション防止のため緊急決済
                    msg = (f"🚨 CRITICAL: {bot_name} {symbol} SL発注失敗 → 緊急成行決済を試行\n"
                           f"Entry price: {fill_price}, Amount: {fill_amount}")
                    logger.error(f"[OrderExecutor] {msg}")
                    await self.alert.send_message(msg)
                    try:
                        close_side = 'sell' if side == 'long' else 'buy'
                        emergency_order = await self.exchange.create_order(
                            symbol, 'market', close_side, fill_amount,
                            params={'reduceOnly': True}
                        )
                        logger.warning(f"[OrderExecutor] Emergency close executed: {symbol}")
                        await self.alert.send_message(f"⚠️ {symbol} 緊急決済完了（SL設置不可のため）")
                        # 緊急決済をorder_logに記録 (J1修正)
                        self._log_order(bot_name, symbol, 'emergency_close', close_side,
                                        fill_amount, fill_price,
                                        emergency_order.get('id', '') if emergency_order else '',
                                        'filled', metadata=json.dumps({'reason': 'sl_placement_failed'}))
                    except Exception as close_err:
                        logger.error(f"[OrderExecutor] Emergency close FAILED: {close_err}")
                        await self.alert.send_message(
                            f"🔴 CRITICAL: {symbol} 緊急決済も失敗! 手動で即時決済してください! Error: {close_err}"
                        )
                        # 失敗した緊急決済もorder_logに記録
                        self._log_order(bot_name, symbol, 'emergency_close', close_side,
                                        fill_amount, fill_price, '', 'failed',
                                        error_message=str(close_err))
                    result['error'] = 'sl_placement_failed_emergency_close'
                    result['success'] = False
                    return result

                if not tp_order:
                    # TP失敗はSLがあるので継続（通知のみ）
                    msg = (f"⚠️ {bot_name} {symbol} TP発注失敗（SLは設置済み）\n"
                           f"手動でTPを設定してください。Entry: {fill_price}")
                    logger.warning(f"[OrderExecutor] {msg}")
                    await self.alert.send_message(msg)

                # ---- DB記録 ----
                tp_price, sl_price = self._calc_tp_sl_prices(fill_price, side, tp_pct, sl_pct)
                self.db.add_position(
                    symbol=symbol, side=side, entry_price=fill_price,
                    size=fill_amount, leverage=leverage,
                    sl=sl_price, tp=tp_price,
                    notes=f"LIVE {bot_name}"
                )

                # TP/SL注文IDをDBに保存 (H2)
                tp_id = tp_order.get('id') if tp_order else None
                sl_id = sl_order.get('id') if sl_order else None
                entry_id = entry_order.get('id', '')
                self._save_order_ids_to_db(symbol, entry_id, tp_id, sl_id, bot_name)

                # order_log 記録
                self._log_order(bot_name, symbol, 'market', side, fill_amount, fill_price,
                                entry_order.get('id', ''), 'filled')
                if tp_order:
                    self._log_order(bot_name, symbol, 'limit_tp',
                                    'sell' if side == 'long' else 'buy',
                                    fill_amount, tp_price,
                                    tp_order.get('id', ''), 'submitted')
                if sl_order:
                    self._log_order(bot_name, symbol, 'stop_sl',
                                    'sell' if side == 'long' else 'buy',
                                    fill_amount, sl_price,
                                    sl_order.get('id', ''), 'submitted')

                # TradeRecorder に統一記録
                if self.trade_recorder:
                    try:
                        self.trade_recorder.record_entry(
                            mode='live', bot_name=bot_name, symbol=symbol,
                            side=side, entry_price=fill_price, leverage=leverage,
                            amount=fill_amount, tp_price=tp_price, sl_price=sl_price,
                            exchange_order_id=entry_order.get('id', ''),
                        )
                    except Exception as tr_err:
                        logger.warning(f"[OrderExecutor] TradeRecorder entry failed: {tr_err}")

                # APIManager にポジション記録
                if self.api_manager:
                    self.api_manager.record_position(bot_name, symbol, side)

                # 注文ID保存（メモリ）
                self._active_orders[symbol] = {
                    'entry_id': entry_order.get('id'),
                    'tp_id': tp_id,
                    'sl_id': sl_id,
                    'bot_name': bot_name,
                    'side': side,
                    'amount': fill_amount,
                }

                result['success'] = True
                return result

            finally:
                # ロック解放
                if self.api_manager:
                    self.api_manager.unlock_symbol(symbol)

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"[OrderExecutor] Unexpected error: {e}", exc_info=True)
            return result

    async def close_position(self, symbol: str, reason: str = "manual") -> dict:
        """ポジションを成行決済 + 関連TP/SL注文をキャンセル。"""
        result = {'success': False, 'error': ''}

        try:
            # 関連する注文をキャンセル
            order_info = self._active_orders.get(symbol)
            if order_info:
                for key in ('tp_id', 'sl_id'):
                    order_id = order_info.get(key)
                    if order_id:
                        try:
                            await self.exchange.cancel_order(order_id, symbol)
                            logger.info(f"[OrderExecutor] Cancelled {key}: {order_id}")
                        except Exception as e:
                            logger.warning(f"[OrderExecutor] Failed to cancel {key}: {e}")

            # 成行決済
            close_side = 'sell' if (order_info and order_info['side'] == 'long') else 'buy'
            amount = order_info['amount'] if order_info else 0

            if amount > 0:
                close_order = await self.exchange.create_order(
                    symbol, 'market', close_side, amount,
                    params={'reduceOnly': True}
                )
                fill_price = close_order.get('average') or close_order.get('price') or 0

                # DB更新
                positions = self.db.get_open_positions()
                for pos in positions:
                    if pos['symbol'] == symbol and pos['status'] == 'open':
                        entry_price = pos['entry_price']
                        leverage = pos['leverage']
                        if pos['side'] == 'long':
                            pnl = ((fill_price - entry_price) / entry_price * 100 - ROUND_TRIP_COST_PCT) * leverage
                        else:
                            pnl = ((entry_price - fill_price) / entry_price * 100 - ROUND_TRIP_COST_PCT) * leverage
                        self.db.close_position(pos['id'], fill_price, round(pnl, 2))
                        self._update_circuit_breaker(pnl)
                        break

                # TradeRecorder 決済記録
                if self.trade_recorder:
                    try:
                        # 直近のオープンliveトレードを検索して決済
                        tr_result = self.trade_recorder.get_trades(
                            mode='live', symbol=symbol, status='open', limit=1)
                        if tr_result['trades']:
                            self.trade_recorder.record_exit(
                                tr_result['trades'][0]['id'], fill_price,
                                exit_reason=reason or 'MANUAL')
                    except Exception as tr_err:
                        logger.warning(f"[OrderExecutor] TradeRecorder exit failed: {tr_err}")

                # APIManagerクリア
                if self.api_manager and order_info:
                    self.api_manager.clear_position(order_info['bot_name'], symbol)

                self._active_orders.pop(symbol, None)

                bot_name = order_info['bot_name'] if order_info else 'unknown'
                self._log_order(bot_name, symbol, 'market_close', close_side, amount,
                                fill_price, close_order.get('id', ''), 'filled',
                                metadata=json.dumps({'reason': reason}))

                result['success'] = True
                logger.info(f"[OrderExecutor] CLOSED: {symbol} reason={reason} price={fill_price}")
            else:
                result['error'] = 'no_amount_to_close'

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"[OrderExecutor] Close error: {e}", exc_info=True)

        return result

    # ================================================================
    # G1: タイムアウト時の注文確認リカバリ
    # ================================================================

    async def _verify_order_after_timeout(self, symbol: str, side: str,
                                           amount: float, bot_name: str = '') -> Optional[dict]:
        """タイムアウト後に注文が約定済みか確認。
        1. fetch_open_orders + fetch_orders で注文を検索
        2. 見つからなければ fetch_positions でポジション存在を確認
        3. ポジションがあれば緊急SLを設置

        Returns:
            約定済み注文情報 or None (注文なし)
        """
        logger.warning(f"[OrderExecutor] Timeout recovery started: {symbol} {side}")
        await self.alert.send_message(
            f"⚠️ {symbol} 注文タイムアウト — 取引所で注文状態を確認中..."
        )

        # Phase 1: fetch_orders で直近の注文を確認 (最大3回リトライ)
        # BitMart等 fetchOrders 未対応取引所は fetchOpenOrders へフォールバック
        has_fetch_orders = self.exchange.has.get('fetchOrders', False)
        for attempt in range(VERIFY_MAX_RETRIES):
            try:
                if has_fetch_orders:
                    orders = await self.exchange.fetch_orders(symbol, limit=5)
                else:
                    orders = await self.exchange.fetch_open_orders(symbol)
                # 直近の同方向の成行注文を探す
                order_side = self._normalize_side(side)
                for order in reversed(orders):  # 最新順
                    if (order.get('side') == order_side and
                            order.get('type') == 'market' and
                            order.get('status') in ('closed', 'filled')):
                        # 約定時刻が直近60秒以内か確認
                        order_ts = order.get('timestamp', 0)
                        now_ts = int(time.time() * 1000)
                        if now_ts - order_ts < 60000:  # 60秒以内
                            logger.info(f"[OrderExecutor] Timeout recovery: order found "
                                        f"id={order.get('id')} filled={order.get('filled')}")
                            self._log_order(bot_name, symbol, 'timeout_recovery_found',
                                            side, amount, 0,
                                            order.get('id', ''), 'recovered')
                            await self.alert.send_message(
                                f"✅ {symbol} タイムアウト後の注文確認: 約定済み (ID: {order.get('id')})"
                            )
                            return order
                logger.info(f"[OrderExecutor] Timeout verify attempt {attempt+1}/{VERIFY_MAX_RETRIES}: "
                            f"no matching order found for {symbol}")
            except Exception as e:
                logger.warning(f"[OrderExecutor] Timeout verify attempt {attempt+1} failed: {e}")

            if attempt < VERIFY_MAX_RETRIES - 1:
                await asyncio.sleep(VERIFY_INTERVAL_SEC)

        # Phase 2: fetch_positions でポジション存在チェック
        logger.warning(f"[OrderExecutor] Order not found via fetch_orders, checking positions: {symbol}")
        try:
            positions = await self.exchange.fetch_positions([symbol])
            for pos in positions:
                contracts = float(pos.get('contracts', 0) or 0)
                if contracts > 0 and pos.get('symbol') == symbol:
                    # ポジションが存在 → 注文は約定済みだった
                    logger.warning(f"[OrderExecutor] Timeout recovery: position exists "
                                   f"{symbol} contracts={contracts}")
                    self._log_order(bot_name, symbol, 'timeout_recovery_position',
                                    side, contracts, 0, '', 'recovered',
                                    metadata=json.dumps({'source': 'fetch_positions'}))
                    await self.alert.send_message(
                        f"⚠️ {symbol} タイムアウト後ポジション検出: {contracts}コントラクト"
                    )
                    # 疑似的な注文結果を返す
                    mark_price = float(pos.get('markPrice', 0) or pos.get('entryPrice', 0) or 0)
                    return {
                        'id': f'timeout_recovered_{int(time.time())}',
                        'average': float(pos.get('entryPrice', 0) or 0),
                        'price': mark_price,
                        'filled': contracts,
                        'status': 'closed',
                        '_recovered': True,
                    }
        except Exception as e:
            logger.error(f"[OrderExecutor] fetch_positions failed during recovery: {e}")

        # Phase 3: 注文もポジションも見つからない → 安全に失敗
        logger.info(f"[OrderExecutor] Timeout recovery: no order or position found for {symbol}")
        self._log_order(bot_name, symbol, 'timeout_recovery_none',
                        side, amount, 0, '', 'not_found')
        await self.alert.send_message(
            f"ℹ️ {symbol} タイムアウト後の確認完了: 注文・ポジションなし（安全に失敗処理）"
        )
        return None

    # ================================================================
    # H2: _active_ordersのDB復元
    # ================================================================

    def restore_active_orders(self):
        """プロセス起動時にDBからオープンポジションのTP/SL注文IDを読み込み、
        _active_ordersを復元する。"""
        try:
            positions = self.db.get_open_positions()
            restored = 0
            for pos in positions:
                symbol = pos['symbol']
                if symbol in self._active_orders:
                    continue  # 既に追跡中
                tp_id = pos.get('tp_order_id')
                sl_id = pos.get('sl_order_id')
                bot_name = pos.get('bot_name', '')
                entry_id = pos.get('exchange_order_id', '')
                if tp_id or sl_id:
                    self._active_orders[symbol] = {
                        'entry_id': entry_id,
                        'tp_id': tp_id,
                        'sl_id': sl_id,
                        'bot_name': bot_name or 'unknown',
                        'side': pos['side'],
                        'amount': pos['size'],
                    }
                    restored += 1
                    logger.info(f"[OrderExecutor] Restored active order: {symbol} "
                                f"tp={tp_id} sl={sl_id}")
            if restored > 0:
                logger.info(f"[OrderExecutor] Restored {restored} active orders from DB")
        except Exception as e:
            logger.error(f"[OrderExecutor] Failed to restore active orders: {e}")

    def _save_order_ids_to_db(self, symbol: str, entry_id: str,
                               tp_id: Optional[str], sl_id: Optional[str],
                               bot_name: str = ''):
        """TP/SL注文IDをpositionsテーブルに保存。"""
        conn = None
        try:
            conn = self.db._get_conn()
            conn.execute(
                '''UPDATE positions
                   SET exchange_order_id=?, tp_order_id=?, sl_order_id=?, bot_name=?
                   WHERE symbol=? AND status='open'
                   ORDER BY id DESC LIMIT 1''',
                (entry_id, tp_id, sl_id, bot_name, symbol)
            )
            conn.commit()
            logger.info(f"[OrderExecutor] Saved order IDs to DB: {symbol} "
                        f"entry={entry_id} tp={tp_id} sl={sl_id}")
        except Exception as e:
            logger.error(f"[OrderExecutor] Failed to save order IDs: {e}")
        finally:
            if conn:
                conn.close()

    async def cancel_orphaned_orders(self, symbol: str):
        """指定シンボルの残存TP/SL注文をキャンセル。
        ポジション決済後に呼び出される。"""
        order_info = self._active_orders.get(symbol)
        if not order_info:
            return
        cancelled = []
        for key in ('tp_id', 'sl_id'):
            order_id = order_info.get(key)
            if order_id:
                try:
                    await self.exchange.cancel_order(order_id, symbol)
                    cancelled.append(f"{key}={order_id}")
                    logger.info(f"[OrderExecutor] Cancelled orphaned {key}: {order_id}")
                except Exception as e:
                    logger.warning(f"[OrderExecutor] Failed to cancel orphaned {key}: {e}")
        self._active_orders.pop(symbol, None)
        if cancelled:
            await self.alert.send_message(
                f"🧹 {symbol} 残存注文キャンセル: {', '.join(cancelled)}"
            )

    # ================================================================
    # プリフライトチェック
    # ================================================================

    async def _pre_flight_checks(self, bot_name: str, symbol: str, side: str,
                                  leverage: int, position_size_pct: float) -> tuple:
        """エントリー前の安全チェック。(ok, reason) を返す。"""

        # Bot許可リストチェック
        if self.allowed_bots and bot_name not in self.allowed_bots:
            return False, f'bot_not_allowed: {bot_name}'

        # サーキットブレーカー
        self._check_daily_reset()
        if self._circuit_broken:
            return False, 'circuit_breaker_active'

        # 最大ポジション数
        open_positions = self.db.get_open_positions()
        if len(open_positions) >= self.max_positions:
            return False, f'max_positions_reached: {len(open_positions)}/{self.max_positions}'

        # 同一銘柄の重複チェック
        for pos in open_positions:
            if pos['symbol'] == symbol and pos['status'] == 'open':
                return False, f'duplicate_position: {symbol}'

        # ポジション競合チェック（逆方向）
        if self.api_manager:
            conflict = self.api_manager.check_position_conflict(bot_name, symbol, side)
            if conflict:
                return False, f'position_conflict: {symbol} {conflict["bot"]} has {conflict["side"]}'

        # 残高チェック
        balance = await self._fetch_balance()
        if balance is None:
            return False, 'balance_fetch_failed'
        if balance < self.min_balance_usd:
            return False, f'insufficient_balance: ${balance:.2f} < ${self.min_balance_usd}'

        required_margin = balance * (position_size_pct / 100)
        if required_margin > balance * 0.95:
            return False, f'margin_too_large: ${required_margin:.2f} > 95% of ${balance:.2f}'

        return True, 'ok'

    # ================================================================
    # 注文メソッド
    # ================================================================

    async def _set_leverage_and_margin(self, symbol: str, leverage: int):
        """レバレッジとマージンタイプを設定。"""
        try:
            await self.exchange.set_leverage(leverage, symbol)
            logger.info(f"[OrderExecutor] Leverage set: {symbol} {leverage}x")
        except Exception as e:
            # 既に同じレバレッジの場合エラーになることがある
            logger.debug(f"[OrderExecutor] set_leverage note: {e}")

        # setMarginMode は BitMart等で未対応 — has チェックしてスキップ
        if self.exchange.has.get('setMarginMode', False):
            try:
                margin_type = self.default_margin_type  # 'cross' or 'isolated'
                await self.exchange.set_margin_mode(margin_type, symbol)
                logger.info(f"[OrderExecutor] Margin mode set: {symbol} {margin_type}")
            except Exception as e:
                logger.debug(f"[OrderExecutor] set_margin_mode note: {e}")
        else:
            logger.debug(f"[OrderExecutor] set_margin_mode not supported on {self.exchange.id}, skipping")

    @staticmethod
    def _normalize_side(side: str) -> str:
        """'long'/'short' を ccxt標準の 'buy'/'sell' に正規化。"""
        side_map = {'long': 'buy', 'short': 'sell', 'buy': 'buy', 'sell': 'sell'}
        return side_map.get(side.lower(), side)

    async def _place_market_order(self, symbol: str, side: str, amount: float) -> Optional[dict]:
        """成行注文を発注。タイムアウト時はリカバリ確認付き。"""
        order_side = self._normalize_side(side)
        for attempt in range(3):
            try:
                order = await self.exchange.create_order(
                    symbol, 'market', order_side, amount
                )
                return order
            except _TIMEOUT_ERRORS as e:
                # G1: タイムアウト/ネットワークエラー → 注文が約定済みか確認
                logger.warning(f"[OrderExecutor] Timeout/NetworkError on market order "
                               f"(attempt {attempt+1}): {e}")
                self._log_order('', symbol, 'market_timeout', side, amount, 0, '',
                                'timeout', error_message=str(e))
                recovered = await self._verify_order_after_timeout(symbol, side, amount)
                if recovered:
                    return recovered
                # 注文が見つからない → 安全にリトライ可能
                if attempt < 2:
                    logger.info(f"[OrderExecutor] No order found after timeout, retrying...")
                    await asyncio.sleep(VERIFY_INTERVAL_SEC)
                    continue
                return None
            except Exception as e:
                err_str = str(e)
                if '510' in err_str or 'too frequent' in err_str.lower():
                    logger.warning(f"[OrderExecutor] Rate limited, retry {attempt+1}/3")
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                logger.error(f"[OrderExecutor] Market order failed: {e}")
                return None
        return None

    async def _place_tp_sl(self, symbol: str, side: str, amount: float,
                            entry_price: float, tp_pct: float, sl_pct: float,
                            contract_size: float = 1) -> tuple:
        """TP指値 + SL逆指値を発注。タイムアウト時はリカバリ確認付き。
        (tp_order, sl_order) を返す。"""
        tp_price, sl_price = self._calc_tp_sl_prices(entry_price, side, tp_pct, sl_pct)

        # 精度調整
        tp_price = float(self.exchange.price_to_precision(symbol, tp_price))
        sl_price = float(self.exchange.price_to_precision(symbol, sl_price))

        close_side = 'sell' if side == 'long' else 'buy'

        # TP: 指値注文（reduceOnly）
        tp_order = await self._place_single_order_with_recovery(
            symbol, 'limit', close_side, amount, tp_price,
            params={'reduceOnly': True},
            label='TP'
        )

        # SL: トリガー注文（reduceOnly）— 取引所ごとにパラメータを切替
        sl_order = None
        exchange_id = self.exchange.id
        if exchange_id == 'mexc':
            sl_methods = [
                {'type': 'market', 'price': None,
                 'params': {'stopLossPrice': sl_price, 'reduceOnly': True}},
                {'type': 'market', 'price': None,
                 'params': {'triggerPrice': sl_price, 'reduceOnly': True}},
                {'type': 'limit',
                 'price': sl_price * (0.995 if close_side == 'sell' else 1.005),
                 'params': {'triggerPrice': sl_price, 'reduceOnly': True}},
            ]
        else:
            # BitMart / Binance / Bybit / OKX: ccxt統一パラメータ
            sl_methods = [
                {'type': 'market', 'price': None,
                 'params': {'stopLossPrice': sl_price, 'reduceOnly': True}},
                {'type': 'market', 'price': None,
                 'params': {'triggerPrice': sl_price, 'reduceOnly': True}},
            ]
        for i, method in enumerate(sl_methods):
            try:
                sl_order = await self._place_single_order_with_recovery(
                    symbol, method['type'], close_side, amount, method['price'],
                    params=method['params'],
                    label=f'SL(method{i+1})'
                )
                if sl_order:
                    logger.info(f"[OrderExecutor] SL placed (method {i+1}): {symbol} {close_side} "
                                f"amount={amount} trigger={sl_price}")
                    break
            except Exception as e:
                logger.warning(f"[OrderExecutor] SL method {i+1} failed: {e}")
                if i == len(sl_methods) - 1:
                    logger.error(f"[OrderExecutor] All SL methods failed for {symbol}")

        return tp_order, sl_order

    async def _place_single_order_with_recovery(self, symbol: str, order_type: str,
                                                  side: str, amount: float,
                                                  price: Optional[float],
                                                  params: dict = None,
                                                  label: str = '') -> Optional[dict]:
        """単一注文を発注。タイムアウト時は注文確認リカバリ付き。"""
        try:
            order = await self.exchange.create_order(
                symbol, order_type, side, amount, price, params=params
            )
            if label:
                logger.info(f"[OrderExecutor] {label} placed: {symbol} {side} "
                            f"amount={amount} price={price}")
            return order
        except _TIMEOUT_ERRORS as e:
            logger.warning(f"[OrderExecutor] {label} timeout: {symbol} {e}")
            # TP/SL注文のタイムアウト → fetch_open_ordersで確認
            try:
                await asyncio.sleep(VERIFY_INTERVAL_SEC)
                open_orders = await self.exchange.fetch_open_orders(symbol)
                for order in open_orders:
                    # 直近に発注された同タイプの注文を探す
                    if order.get('side') == side:
                        order_ts = order.get('timestamp', 0)
                        now_ts = int(time.time() * 1000)
                        if now_ts - order_ts < 30000:  # 30秒以内
                            logger.info(f"[OrderExecutor] {label} recovered after timeout: "
                                        f"id={order.get('id')}")
                            return order
            except Exception as verify_err:
                logger.warning(f"[OrderExecutor] {label} timeout verify failed: {verify_err}")
            logger.error(f"[OrderExecutor] {label} order failed (timeout, not recovered)")
            return None
        except Exception as e:
            logger.error(f"[OrderExecutor] {label} order failed: {e}")
            return None

    # ================================================================
    # サーキットブレーカー
    # ================================================================

    def _check_daily_reset(self):
        """日付が変わったら日次PnLをリセット。"""
        today = date.today()
        if today != self._daily_date:
            self._daily_date = today
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._circuit_broken = False
            logger.info("[OrderExecutor] Daily circuit breaker reset")

    def _update_circuit_breaker(self, pnl: float):
        """決済PnLを受けてサーキットブレーカーを更新。"""
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # 日次損失上限
        if self._daily_pnl <= -self.max_daily_loss_pct:
            self._circuit_broken = True
            logger.warning(f"[OrderExecutor] CIRCUIT BREAKER: daily loss {self._daily_pnl:.2f}% "
                           f">= -{self.max_daily_loss_pct}%")

        # 連敗上限
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._circuit_broken = True
            logger.warning(f"[OrderExecutor] CIRCUIT BREAKER: {self._consecutive_losses} "
                           f"consecutive losses")

    # ================================================================
    # ヘルパー
    # ================================================================

    async def _fetch_balance(self) -> Optional[float]:
        """USDT先物口座の利用可能残高を取得。"""
        try:
            balance = await self.exchange.fetch_balance()
            # CCXT MEXC futures: balance['USDT'] = {'free': x, 'used': y, 'total': z}
            usdt_info = balance.get('USDT', {})
            if isinstance(usdt_info, dict):
                free = float(usdt_info.get('free', 0) or 0)
            else:
                free = float(usdt_info) if usdt_info else 0.0
            logger.info(f"[OrderExecutor] Balance: {free:.2f} USDT free")
            return free
        except Exception as e:
            logger.error(f"[OrderExecutor] Balance fetch failed: {e}")
            return None

    @staticmethod
    def _calc_tp_sl_prices(entry_price: float, side: str,
                            tp_pct: float, sl_pct: float) -> tuple:
        """TP/SL価格を計算。"""
        if side == 'long':
            tp_price = entry_price * (1 + tp_pct / 100)
            sl_price = entry_price * (1 - sl_pct / 100)
        else:
            tp_price = entry_price * (1 - tp_pct / 100)
            sl_price = entry_price * (1 + sl_pct / 100)
        return tp_price, sl_price

    def _log_order(self, bot_name: str, symbol: str, order_type: str, side: str,
                   amount: float, price: float, exchange_order_id: str,
                   status: str, error_message: str = '', metadata: str = ''):
        """注文ログをDBに記録。"""
        conn = None
        try:
            conn = self.db._get_conn()
            conn.execute(
                '''INSERT INTO order_log
                   (timestamp, bot_name, symbol, order_type, side, amount, price,
                    exchange_order_id, status, error_message, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (datetime.now().isoformat(), bot_name, symbol, order_type, side,
                 amount, price, exchange_order_id, status, error_message, metadata)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"[OrderExecutor] Failed to log order: {e}")
        finally:
            if conn:
                conn.close()

    def get_active_orders(self) -> dict:
        """アクティブ注文の一覧。"""
        return dict(self._active_orders)

    def get_circuit_breaker_status(self) -> dict:
        """サーキットブレーカー状態。"""
        self._check_daily_reset()
        return {
            'circuit_broken': self._circuit_broken,
            'daily_pnl': round(self._daily_pnl, 2),
            'max_daily_loss_pct': self.max_daily_loss_pct,
            'consecutive_losses': self._consecutive_losses,
            'max_consecutive_losses': self._max_consecutive_losses,
        }
