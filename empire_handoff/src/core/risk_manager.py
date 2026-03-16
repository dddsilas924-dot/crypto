"""リスク管理 — 日次/累積損失リミット判定、自動停止、イベント記録"""
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("empire")


class RiskManager:
    def __init__(self, db, config: dict = None):
        self.db = db
        cfg = config or {}
        self.daily_loss_limit_pct = cfg.get('daily_loss_limit_pct', 5.0)
        self.cumulative_loss_limit_pct = cfg.get('cumulative_loss_limit_pct', 20.0)
        self.limit_action = cfg.get('limit_action', 'order_stop')  # 'order_stop' or 'bot_stop'
        self._order_stopped = False
        self._bot_stopped = False

    def reload_config(self, config: dict):
        self.daily_loss_limit_pct = config.get('daily_loss_limit_pct', 5.0)
        self.cumulative_loss_limit_pct = config.get('cumulative_loss_limit_pct', 20.0)
        self.limit_action = config.get('limit_action', 'order_stop')

    @property
    def is_order_stopped(self) -> bool:
        return self._order_stopped

    @property
    def is_bot_stopped(self) -> bool:
        return self._bot_stopped

    def reset_daily(self):
        """日次リセット（毎日0時に呼出）"""
        self._order_stopped = False
        self._bot_stopped = False

    def check_limits(self, portfolio_id: int, initial_capital: float) -> dict:
        """リミットチェック。違反時はイベント記録+停止フラグセット。

        Returns:
            {
                'daily_ok': bool,
                'cumulative_ok': bool,
                'daily_pnl_pct': float,
                'cumulative_pnl_pct': float,
                'action': str or None,
            }
        """
        if initial_capital <= 0:
            return {'daily_ok': True, 'cumulative_ok': True,
                    'daily_pnl_pct': 0, 'cumulative_pnl_pct': 0, 'action': None}

        conn = self.db._get_conn()
        today = date.today().isoformat()

        # 日次PNL
        drow = conn.execute(
            "SELECT COALESCE(SUM(pnl_amount), 0) FROM trade_records "
            "WHERE portfolio_id=? AND status='closed' AND exit_time LIKE ?",
            (portfolio_id, today + '%')
        ).fetchone()
        daily_pnl = drow[0]
        daily_pnl_pct = daily_pnl / initial_capital * 100

        # 累積PNL
        crow = conn.execute(
            "SELECT COALESCE(SUM(pnl_amount), 0) FROM trade_records "
            "WHERE portfolio_id=? AND status='closed'",
            (portfolio_id,)
        ).fetchone()
        cumulative_pnl = crow[0]
        cumulative_pnl_pct = cumulative_pnl / initial_capital * 100

        conn.close()

        result = {
            'daily_ok': True,
            'cumulative_ok': True,
            'daily_pnl_pct': round(daily_pnl_pct, 2),
            'cumulative_pnl_pct': round(cumulative_pnl_pct, 2),
            'action': None,
        }

        # 日次リミット
        if daily_pnl_pct <= -self.daily_loss_limit_pct:
            result['daily_ok'] = False
            result['action'] = self.limit_action
            self._record_event(portfolio_id, 'daily_limit',
                               daily_pnl_pct, -self.daily_loss_limit_pct,
                               self.limit_action)
            self._apply_action()
            logger.warning(f"[RiskManager] DAILY LIMIT BREACHED: {daily_pnl_pct:.2f}% "
                           f"(limit: -{self.daily_loss_limit_pct}%)")

        # 累積リミット
        if cumulative_pnl_pct <= -self.cumulative_loss_limit_pct:
            result['cumulative_ok'] = False
            result['action'] = self.limit_action
            self._record_event(portfolio_id, 'cumulative_limit',
                               cumulative_pnl_pct, -self.cumulative_loss_limit_pct,
                               self.limit_action)
            self._apply_action()
            logger.warning(f"[RiskManager] CUMULATIVE LIMIT BREACHED: {cumulative_pnl_pct:.2f}% "
                           f"(limit: -{self.cumulative_loss_limit_pct}%)")

        return result

    def _apply_action(self):
        if self.limit_action == 'bot_stop':
            self._bot_stopped = True
            self._order_stopped = True
        else:
            self._order_stopped = True

    def _record_event(self, portfolio_id: int, event_type: str,
                      trigger_value: float, limit_value: float,
                      action_taken: str, bot_name: str = ''):
        conn = self.db._get_conn()
        conn.execute(
            '''INSERT INTO risk_events
               (portfolio_id, event_type, trigger_value, limit_value,
                action_taken, bot_name, timestamp)
               VALUES (?,?,?,?,?,?,?)''',
            (portfolio_id, event_type, trigger_value, limit_value,
             action_taken, bot_name, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_events(self, portfolio_id: int = None, limit: int = 50) -> list:
        conn = self.db._get_conn()
        if portfolio_id is not None:
            rows = conn.execute(
                "SELECT * FROM risk_events WHERE portfolio_id=? ORDER BY timestamp DESC LIMIT ?",
                (portfolio_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM risk_events ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM risk_events LIMIT 0").description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]

    def get_status(self) -> dict:
        return {
            'order_stopped': self._order_stopped,
            'bot_stopped': self._bot_stopped,
            'daily_loss_limit_pct': self.daily_loss_limit_pct,
            'cumulative_loss_limit_pct': self.cumulative_loss_limit_pct,
            'limit_action': self.limit_action,
        }
