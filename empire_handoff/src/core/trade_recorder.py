"""統一トレード記録 — paper/live両方のBOT注文を trade_records に記録、日次集計、CSV出力"""
import csv
import json
import logging
from datetime import datetime, date
from typing import List, Optional

logger = logging.getLogger("empire")

ROUND_TRIP_COST_PCT = 0.22


class TradeRecorder:
    def __init__(self, db):
        self.db = db
        from src.core.trade_serial import TradeSerialGenerator
        self._serial_gen = TradeSerialGenerator(db)

    def record_entry(self, mode: str, bot_name: str, symbol: str, side: str,
                     entry_price: float, leverage: float = 3.0,
                     amount: float = 0, tp_price: float = None,
                     sl_price: float = None, funding_rate: float = None,
                     exchange_order_id: str = '', portfolio_id: int = None,
                     metadata: dict = None) -> int:
        """新規エントリー記録。trade_records IDを返す。"""
        serial = self._serial_gen.next_serial(bot_name)
        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute(
            '''INSERT INTO trade_records
               (portfolio_id, mode, bot_name, symbol, side, leverage, amount,
                entry_price, entry_time, tp_price, sl_price, funding_rate,
                status, exchange_order_id, metadata, trade_serial)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (portfolio_id, mode, bot_name, symbol, side, leverage, amount,
             entry_price, datetime.now().isoformat(),
             tp_price, sl_price, funding_rate,
             'open', exchange_order_id,
             json.dumps(metadata) if metadata else None,
             serial)
        )
        trade_id = c.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"[TradeRecorder] Entry: [{serial}] {mode} {bot_name} {symbol} {side} "
                     f"@{entry_price} lev={leverage} id={trade_id}")
        return trade_id

    @property
    def serial_generator(self):
        return self._serial_gen

    def record_exit(self, trade_id: int, exit_price: float,
                    exit_reason: str = '', pnl_pct: float = None,
                    pnl_amount: float = None, fee_amount: float = None) -> dict:
        """決済記録。PNL未指定時は自動計算。"""
        conn = self.db._get_conn()
        row = conn.execute(
            "SELECT * FROM trade_records WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            conn.close()
            return {'error': 'trade not found'}

        cols = [d[0] for d in conn.execute("SELECT * FROM trade_records LIMIT 0").description]
        trade = dict(zip(cols, row))

        entry_price = trade['entry_price']
        leverage = trade['leverage']
        amount = trade['amount'] or 0
        side = trade['side']

        # PNL自動計算
        if pnl_pct is None:
            if side == 'long':
                raw_pct = (exit_price - entry_price) / entry_price * 100
            else:
                raw_pct = (entry_price - exit_price) / entry_price * 100
            pnl_pct = round((raw_pct - ROUND_TRIP_COST_PCT) * leverage, 2)

        if pnl_amount is None and amount > 0 and entry_price > 0:
            notional = amount * entry_price
            pnl_amount = round(notional * pnl_pct / 100, 2)

        if fee_amount is None and amount > 0 and entry_price > 0:
            notional = amount * entry_price
            fee_amount = round(notional * ROUND_TRIP_COST_PCT / 100, 4)

        conn.execute(
            '''UPDATE trade_records
               SET exit_price=?, exit_time=?, exit_reason=?,
                   pnl_pct=?, pnl_amount=?, fee_amount=?, status='closed'
               WHERE id=?''',
            (exit_price, datetime.now().isoformat(), exit_reason,
             pnl_pct, pnl_amount, fee_amount, trade_id)
        )
        conn.commit()
        conn.close()

        # 日次PNL更新
        self._update_daily_pnl(trade['portfolio_id'], trade['mode'], date.today().isoformat(),
                               pnl_amount or 0, pnl_pct,
                               trade_count_delta=1,
                               win_delta=1 if (pnl_pct or 0) > 0 else 0)

        serial = trade.get('trade_serial', f'#{trade_id}')
        logger.info(f"[TradeRecorder] Exit: [{serial}] {exit_reason} "
                     f"pnl={pnl_pct}% amount={pnl_amount}")
        return {'trade_id': trade_id, 'trade_serial': serial, 'pnl_pct': pnl_pct, 'pnl_amount': pnl_amount}

    def record_cancel(self, trade_id: int):
        """キャンセル記録"""
        conn = self.db._get_conn()
        conn.execute(
            "UPDATE trade_records SET status='cancelled', exit_time=? WHERE id=?",
            (datetime.now().isoformat(), trade_id)
        )
        conn.commit()
        conn.close()

    # ── 照会 ──

    def get_trades(self, mode: str = None, bot_name: str = None,
                   symbol: str = None, portfolio_id: int = None,
                   status: str = None, date_from: str = None, date_to: str = None,
                   limit: int = 100, offset: int = 0,
                   sort_by: str = 'entry_time', sort_dir: str = 'DESC') -> dict:
        """フィルター付きトレード取得。ページネーション対応。"""
        conditions = []
        params = []

        if mode:
            conditions.append("mode=?")
            params.append(mode)
        if bot_name:
            conditions.append("bot_name=?")
            params.append(bot_name)
        if symbol:
            conditions.append("symbol LIKE ?")
            params.append(f"%{symbol}%")
        if portfolio_id is not None:
            conditions.append("portfolio_id=?")
            params.append(portfolio_id)
        if status:
            conditions.append("status=?")
            params.append(status)
        if date_from:
            conditions.append("entry_time >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("entry_time <= ?")
            params.append(date_to + 'T23:59:59')

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Validate sort
        allowed_sorts = {'entry_time', 'exit_time', 'pnl_pct', 'pnl_amount', 'symbol', 'bot_name'}
        if sort_by not in allowed_sorts:
            sort_by = 'entry_time'
        if sort_dir.upper() not in ('ASC', 'DESC'):
            sort_dir = 'DESC'

        conn = self.db._get_conn()

        # Count
        total = conn.execute(f"SELECT COUNT(*) FROM trade_records {where}", params).fetchone()[0]

        # Data
        rows = conn.execute(
            f"SELECT * FROM trade_records {where} ORDER BY {sort_by} {sort_dir} LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM trade_records LIMIT 0").description]
        conn.close()

        trades = []
        for r in rows:
            t = dict(zip(cols, r))
            # position_size_pct算出: amount * entry_price = notional, notional / 10000 * 100 = pct
            if t.get('amount') and t.get('entry_price') and t['amount'] > 0 and t['entry_price'] > 0:
                notional = t['amount'] * t['entry_price']
                t['position_size_pct'] = round(notional / 100, 2)  # 10000ベースで%換算
            else:
                t['position_size_pct'] = None
            trades.append(t)

        return {
            'trades': trades,
            'total': total,
            'limit': limit,
            'offset': offset,
        }

    def get_performance_stats(self, mode: str = None, bot_name: str = None,
                              portfolio_id: int = None,
                              date_from: str = None, date_to: str = None) -> dict:
        """パフォーマンス統計: 勝率、平均利益/損失、MDD、PF、トレード数"""
        conditions = ["status='closed'"]
        params = []
        if mode:
            conditions.append("mode=?")
            params.append(mode)
        if bot_name:
            conditions.append("bot_name=?")
            params.append(bot_name)
        if portfolio_id is not None:
            conditions.append("portfolio_id=?")
            params.append(portfolio_id)
        if date_from:
            conditions.append("exit_time >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("exit_time <= ?")
            params.append(date_to + 'T23:59:59')

        where = "WHERE " + " AND ".join(conditions)
        conn = self.db._get_conn()
        rows = conn.execute(
            f"SELECT pnl_pct, pnl_amount FROM trade_records {where} ORDER BY exit_time",
            params
        ).fetchall()
        conn.close()

        if not rows:
            return {
                'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'avg_win_pct': 0, 'avg_loss_pct': 0, 'profit_factor': 0,
                'max_drawdown_pct': 0, 'total_pnl_pct': 0, 'total_pnl_amount': 0,
            }

        pnls = [r[0] or 0 for r in rows]
        amounts = [r[1] or 0 for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        for p in pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        return {
            'total_trades': len(pnls),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            'avg_win_pct': round(sum(wins) / len(wins), 2) if wins else 0,
            'avg_loss_pct': round(sum(losses) / len(losses), 2) if losses else 0,
            'profit_factor': round(pf, 2),
            'max_drawdown_pct': round(max_dd, 2),
            'total_pnl_pct': round(sum(pnls), 2),
            'total_pnl_amount': round(sum(amounts), 2),
        }

    # ── 日次PNL ──

    def _update_daily_pnl(self, portfolio_id, mode, date_str,
                          pnl_amount, pnl_pct, trade_count_delta=0, win_delta=0):
        conn = self.db._get_conn()
        existing = conn.execute(
            "SELECT * FROM daily_pnl WHERE date=? AND portfolio_id=? AND mode=?",
            (date_str, portfolio_id, mode)
        ).fetchone()

        if existing:
            conn.execute(
                '''UPDATE daily_pnl SET
                   pnl_amount = pnl_amount + ?,
                   pnl_pct = pnl_pct + ?,
                   trade_count = trade_count + ?,
                   win_count = win_count + ?,
                   cumulative_pnl = cumulative_pnl + ?
                   WHERE date=? AND portfolio_id=? AND mode=?''',
                (pnl_amount or 0, pnl_pct or 0, trade_count_delta, win_delta,
                 pnl_amount or 0, date_str, portfolio_id, mode)
            )
        else:
            conn.execute(
                '''INSERT INTO daily_pnl (date, portfolio_id, mode, pnl_amount, pnl_pct,
                   trade_count, win_count, cumulative_pnl)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (date_str, portfolio_id, mode, pnl_amount or 0, pnl_pct or 0,
                 trade_count_delta, win_delta, pnl_amount or 0)
            )
        conn.commit()
        conn.close()

    def get_daily_pnl(self, portfolio_id: int = None, mode: str = None,
                      date_from: str = None, date_to: str = None) -> List[dict]:
        conditions = []
        params = []
        if portfolio_id is not None:
            conditions.append("portfolio_id=?")
            params.append(portfolio_id)
        if mode:
            conditions.append("mode=?")
            params.append(mode)
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        conn = self.db._get_conn()
        rows = conn.execute(
            f"SELECT * FROM daily_pnl {where} ORDER BY date", params
        ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM daily_pnl LIMIT 0").description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]

    # ── CSV出力 ──

    def export_trades_csv(self, filepath: str, **filters) -> int:
        """トレード履歴CSV出力"""
        from pathlib import Path
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        result = self.get_trades(limit=999999, **filters)
        trades = result['trades']
        if not trades:
            return 0

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=trades[0].keys())
            w.writeheader()
            w.writerows(trades)
        return len(trades)

    def export_daily_pnl_csv(self, filepath: str, **filters) -> int:
        """日次PNL CSV出力"""
        from pathlib import Path
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        data = self.get_daily_pnl(**filters)
        if not data:
            return 0

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=data[0].keys())
            w.writeheader()
            w.writerows(data)
        return len(data)
