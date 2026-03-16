"""ペーパートレード追跡 - シグナル記録 → 価格追跡 → TP/SL自動判定"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger("empire")

PAPER_CAPITAL_USDT = 10000  # ペーパートレード仮想資金
ROUND_TRIP_COST_PCT = 0.22  # 往復コスト (taker 0.06% × 2 + slippage 0.05% × 2)


class PaperTracker:
    def __init__(self, db, trade_recorder=None, portfolio_manager=None):
        self.db = db
        self.trade_recorder = trade_recorder
        self.portfolio_manager = portfolio_manager
        self._init_table()

    def _init_table(self):
        conn = self.db._get_conn()
        conn.execute('''CREATE TABLE IF NOT EXISTS paper_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            signal_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            leverage REAL DEFAULT 3.0,
            position_size_pct REAL DEFAULT 20.0,
            take_profit_pct REAL DEFAULT 8.0,
            stop_loss_pct REAL DEFAULT 3.0,
            tp_price REAL,
            sl_price REAL,
            current_price REAL,
            unrealized_pnl_pct REAL DEFAULT 0.0,
            status TEXT DEFAULT 'open',
            exit_price REAL,
            exit_time TEXT,
            exit_reason TEXT,
            realized_pnl_pct REAL,
            notes TEXT
        )''')
        conn.commit()
        conn.close()

    MAX_POSITIONS_PER_BOT_SYMBOL = 1  # 同一BOT×同一銘柄の同時オープン上限

    def count_open_positions_per_bot(self, bot_type: str, symbol: str) -> int:
        """同一BOT×同一銘柄のオープンポジション数を返す"""
        conn = self.db._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM paper_signals WHERE bot_type=? AND symbol=? AND status='open'",
            (bot_type, symbol)
        ).fetchone()[0]
        conn.close()
        return count

    def record_signal(self, bot_type: str, symbol: str, side: str,
                      entry_price: float, leverage: float = 3.0,
                      position_size_pct: float = 20.0,
                      take_profit_pct: float = 8.0,
                      stop_loss_pct: float = 3.0,
                      notes: str = "") -> int:
        """新規シグナル記録（同一BOT×同一銘柄の上限チェック付き）

        制限ポリシー:
          - 同一BOT内での同一銘柄は MAX_POSITIONS_PER_BOT_SYMBOL まで
          - 異なるBOT間では同じ銘柄を保有可能（レバ違いの比較用）
        """
        # 同一BOT×同一銘柄のポジション数チェック
        open_count = self.count_open_positions_per_bot(bot_type, symbol)
        if open_count >= self.MAX_POSITIONS_PER_BOT_SYMBOL:
            return -1  # ブロック: 同一BOTで同一銘柄の上限到達

        is_long = side == 'long'
        tp_price = entry_price * (1 + take_profit_pct / 100) if is_long else entry_price * (1 - take_profit_pct / 100)
        sl_price = entry_price * (1 - stop_loss_pct / 100) if is_long else entry_price * (1 + stop_loss_pct / 100)

        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute(
            '''INSERT INTO paper_signals
               (bot_type, symbol, side, signal_time, entry_price, leverage,
                position_size_pct, take_profit_pct, stop_loss_pct,
                tp_price, sl_price, status, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (bot_type, symbol, side, datetime.now().isoformat(), entry_price,
             leverage, position_size_pct, take_profit_pct, stop_loss_pct,
             tp_price, sl_price, 'open', notes)
        )
        signal_id = c.lastrowid
        conn.commit()
        conn.close()

        # TradeRecorder に統一記録 + シリアル番号取得
        trade_serial = ''
        if self.trade_recorder:
            try:
                portfolio_id = None
                if self.portfolio_manager:
                    portfolio_id = self.portfolio_manager.get_portfolio_for_bot(bot_type)
                notional = PAPER_CAPITAL_USDT * position_size_pct / 100
                amount = notional / entry_price if entry_price > 0 else 0
                self.trade_recorder.record_entry(
                    mode='paper', bot_name=bot_type, symbol=symbol, side=side,
                    entry_price=entry_price, leverage=leverage,
                    amount=amount,
                    tp_price=tp_price, sl_price=sl_price,
                    portfolio_id=portfolio_id,
                )
                trade_serial = self.trade_recorder.serial_generator.get_prefix(bot_type)
                # 直前に生成されたシリアルを取得
                trade_serial = self._get_last_serial(bot_type)
            except Exception:
                pass

        return signal_id, trade_serial

    def _get_last_serial(self, bot_type):
        """直前に記録したトレードのシリアル番号を取得"""
        if not self.trade_recorder:
            return ''
        try:
            conn = self.db._get_conn()
            row = conn.execute(
                "SELECT trade_serial FROM trade_records WHERE bot_name=? ORDER BY id DESC LIMIT 1",
                (bot_type,)
            ).fetchone()
            conn.close()
            return row[0] if row and row[0] else ''
        except Exception:
            return ''

    @staticmethod
    def _normalize_symbol(symbol: str) -> list:
        """シンボルの表記ゆれを吸収して候補キーを返す。
        NAORIS_USDT → [NAORIS_USDT, NAORIS/USDT:USDT]
        NAORIS/USDT:USDT → [NAORIS/USDT:USDT, NAORIS_USDT]
        """
        keys = [symbol]
        if '/' in symbol:
            # ccxt形式 → MEXC形式
            keys.append(symbol.replace('/USDT:USDT', '_USDT').replace(':USDT', '').replace('/', '_'))
        elif '_' in symbol and '/' not in symbol:
            # MEXC形式 → ccxt形式
            base = symbol.replace('_USDT', '')
            keys.append(f'{base}/USDT:USDT')
        return keys

    def update_tracking(self, current_prices: dict) -> List[dict]:
        """オープンシグナルの価格更新 + TP/SL判定

        Returns:
            closed_signals: 今回クローズされたシグナルのリスト
        """
        conn = self.db._get_conn()
        open_signals = conn.execute(
            "SELECT * FROM paper_signals WHERE status='open'"
        ).fetchall()

        columns = [desc[0] for desc in conn.execute("SELECT * FROM paper_signals LIMIT 0").description]
        closed = []
        # TradeRecorder決済を後で一括処理（SQLiteロック回避）
        pending_exits = []

        for row in open_signals:
            sig = dict(zip(columns, row))
            symbol = sig['symbol']
            # シンボル形式の違いを吸収 (MEXC WS: NAORIS_USDT vs ccxt: NAORIS/USDT:USDT)
            price = None
            for key in self._normalize_symbol(symbol):
                price = current_prices.get(key)
                if price is not None:
                    break
            if price is None or price <= 0:
                continue

            is_long = sig['side'] == 'long'
            tp_price = sig['tp_price']
            sl_price = sig['sl_price']
            entry_price = sig['entry_price']
            leverage = sig['leverage']

            # PnL計算
            if is_long:
                raw_pnl = (price - entry_price) / entry_price * 100
            else:
                raw_pnl = (entry_price - price) / entry_price * 100
            pnl_leveraged = raw_pnl * leverage

            # TP/SL判定
            exit_reason = None
            exit_price = None

            if is_long:
                if price >= tp_price:
                    exit_reason = 'TP'
                    exit_price = tp_price
                elif price <= sl_price:
                    exit_reason = 'SL'
                    exit_price = sl_price
            else:
                if price <= tp_price:
                    exit_reason = 'TP'
                    exit_price = tp_price
                elif price >= sl_price:
                    exit_reason = 'SL'
                    exit_price = sl_price

            if exit_reason:
                # 決済PnL計算（コスト0.22%控除）
                if is_long:
                    final_pnl = (exit_price - entry_price) / entry_price * 100
                else:
                    final_pnl = (entry_price - exit_price) / entry_price * 100
                realized_pnl = (final_pnl - ROUND_TRIP_COST_PCT) * leverage

                conn.execute(
                    '''UPDATE paper_signals
                       SET status='closed', exit_price=?, exit_time=?,
                           exit_reason=?, realized_pnl_pct=?, current_price=?
                       WHERE id=?''',
                    (exit_price, datetime.now().isoformat(), exit_reason,
                     round(realized_pnl, 2), price, sig['id'])
                )
                sig['exit_reason'] = exit_reason
                sig['realized_pnl_pct'] = round(realized_pnl, 2)
                sig['exit_price'] = exit_price
                closed.append(sig)

                # 想定ポジションサイズからドル損益・手数料を概算
                notional = PAPER_CAPITAL_USDT * sig['position_size_pct'] / 100
                pnl_amount = round(notional * realized_pnl / 100, 2)
                fee_amount = round(notional * ROUND_TRIP_COST_PCT / 100, 4)

                # 後で処理するためにキューに追加
                pending_exits.append({
                    'bot_type': sig['bot_type'],
                    'symbol': symbol,
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'realized_pnl': round(realized_pnl, 2),
                    'pnl_amount': pnl_amount,
                    'fee_amount': fee_amount,
                })
            else:
                conn.execute(
                    "UPDATE paper_signals SET current_price=?, unrealized_pnl_pct=? WHERE id=?",
                    (price, round(pnl_leveraged, 2), sig['id'])
                )

        conn.commit()
        conn.close()

        # SQLiteロック解放後にTradeRecorder決済を一括処理
        if self.trade_recorder and pending_exits:
            for pe in pending_exits:
                try:
                    tr = self.trade_recorder.get_trades(
                        mode='paper', bot_name=pe['bot_type'],
                        symbol=pe['symbol'], status='open', limit=1)
                    if tr['trades']:
                        self.trade_recorder.record_exit(
                            tr['trades'][0]['id'], pe['exit_price'],
                            exit_reason=pe['exit_reason'], pnl_pct=pe['realized_pnl'],
                            pnl_amount=pe.get('pnl_amount'),
                            fee_amount=pe.get('fee_amount'))
                    else:
                        logger.warning(f"[PaperTracker] TradeRecorder: no open trade for {pe['bot_type']} {pe['symbol']}")
                except Exception as e:
                    logger.error(f"[PaperTracker] TradeRecorder exit error: {e}")

        return closed

    def get_summary(self) -> dict:
        """ペーパートレードサマリー"""
        conn = self.db._get_conn()
        open_count = conn.execute("SELECT COUNT(*) FROM paper_signals WHERE status='open'").fetchone()[0]
        closed_count = conn.execute("SELECT COUNT(*) FROM paper_signals WHERE status='closed'").fetchone()[0]
        total = open_count + closed_count

        # 決済済みの勝敗
        wins = conn.execute("SELECT COUNT(*) FROM paper_signals WHERE status='closed' AND realized_pnl_pct > 0").fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM paper_signals WHERE status='closed' AND realized_pnl_pct <= 0").fetchone()[0]

        # 平均PnL
        avg_pnl_row = conn.execute("SELECT AVG(realized_pnl_pct) FROM paper_signals WHERE status='closed'").fetchone()
        avg_pnl = avg_pnl_row[0] if avg_pnl_row[0] is not None else 0.0

        # オープンの含み損益合計
        unrealized_row = conn.execute("SELECT SUM(unrealized_pnl_pct) FROM paper_signals WHERE status='open'").fetchone()
        unrealized_sum = unrealized_row[0] if unrealized_row[0] is not None else 0.0

        # Bot別集計
        bot_stats = {}
        for row in conn.execute(
            "SELECT bot_type, COUNT(*), SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END) "
            "FROM paper_signals WHERE status='closed' GROUP BY bot_type"
        ).fetchall():
            bot_stats[row[0]] = {'closed': row[1], 'wins': row[2]}

        conn.close()

        return {
            'total_signals': total,
            'open': open_count,
            'closed': closed_count,
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / closed_count * 100, 1) if closed_count > 0 else 0.0,
            'avg_pnl': round(avg_pnl, 2),
            'unrealized_sum': round(unrealized_sum, 2),
            'bot_stats': bot_stats,
        }

    def manual_close(self, signal_id: int, current_price: float) -> Optional[dict]:
        """手動決済（GUI利確/損切り用）

        Returns:
            closed signal dict or None if not found
        """
        conn = self.db._get_conn()
        row = conn.execute(
            "SELECT * FROM paper_signals WHERE id=? AND status='open'", (signal_id,)
        ).fetchone()
        if not row:
            conn.close()
            return None

        columns = [desc[0] for desc in conn.execute("SELECT * FROM paper_signals LIMIT 0").description]
        sig = dict(zip(columns, row))

        entry_price = sig['entry_price']
        leverage = sig['leverage']
        is_long = sig['side'] == 'long'

        if is_long:
            raw_pnl = (current_price - entry_price) / entry_price * 100
        else:
            raw_pnl = (entry_price - current_price) / entry_price * 100
        realized_pnl = round((raw_pnl - ROUND_TRIP_COST_PCT) * leverage, 2)

        conn.execute(
            '''UPDATE paper_signals
               SET status='closed', exit_price=?, exit_time=?,
                   exit_reason='MANUAL', realized_pnl_pct=?, current_price=?
               WHERE id=?''',
            (current_price, datetime.now().isoformat(), realized_pnl,
             current_price, signal_id)
        )
        conn.commit()
        conn.close()

        sig['exit_reason'] = 'MANUAL'
        sig['realized_pnl_pct'] = realized_pnl
        sig['exit_price'] = current_price

        # TradeRecorder 決済記録
        if self.trade_recorder:
            try:
                notional = PAPER_CAPITAL_USDT * sig['position_size_pct'] / 100
                pnl_amount = round(notional * realized_pnl / 100, 2)
                fee_amount = round(notional * ROUND_TRIP_COST_PCT / 100, 4)
                tr = self.trade_recorder.get_trades(
                    mode='paper', bot_name=sig['bot_type'],
                    symbol=sig['symbol'], status='open', limit=1)
                if tr['trades']:
                    self.trade_recorder.record_exit(
                        tr['trades'][0]['id'], current_price,
                        exit_reason='MANUAL', pnl_pct=realized_pnl,
                        pnl_amount=pnl_amount, fee_amount=fee_amount)
            except Exception as e:
                logger.error(f"[PaperTracker] TradeRecorder manual exit error: {e}")

        return sig

    def get_open_signals(self) -> List[dict]:
        """オープンシグナル一覧"""
        conn = self.db._get_conn()
        rows = conn.execute("SELECT * FROM paper_signals WHERE status='open' ORDER BY signal_time DESC").fetchall()
        columns = [desc[0] for desc in conn.execute("SELECT * FROM paper_signals LIMIT 0").description]
        conn.close()
        return [dict(zip(columns, row)) for row in rows]
