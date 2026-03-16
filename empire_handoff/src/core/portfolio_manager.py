"""ポートフォリオ管理 — Paper: シミュレーション / Live: ライブ実績閲覧
Paper: Bot組み合わせを自由に選択してペーパートレードをシミュレーション
Live: 設定画面でライブ稼働中のBotの実績を自動集計（読み取り専用、1つ固定）
"""
import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger("empire")

ROUND_TRIP_COST_PCT = 0.22
VALID_TYPES = ('paper', 'live')


class PortfolioManager:
    def __init__(self, db):
        self.db = db

    def create(self, name: str, initial_capital: float = 10000.0,
               description: str = "", portfolio_type: str = "paper",
               **kwargs) -> dict:
        if portfolio_type not in VALID_TYPES:
            portfolio_type = 'paper'
        mode = 'paper' if portfolio_type == 'paper' else 'live'
        conn = self.db._get_conn()
        try:
            conn.execute(
                '''INSERT INTO simulation_portfolios
                   (name, initial_capital, description, status, mode,
                    portfolio_type, created_at)
                   VALUES (?,?,?,?,?,?,?)''',
                (name, initial_capital, description, 'active', mode,
                 portfolio_type, datetime.now().isoformat())
            )
            conn.commit()
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return {'id': pid, 'name': name, 'initial_capital': initial_capital,
                    'mode': mode, 'portfolio_type': portfolio_type}
        except Exception as e:
            if 'UNIQUE' in str(e):
                raise ValueError(f"Portfolio '{name}' already exists")
            raise
        finally:
            conn.close()

    def get(self, portfolio_id: int) -> Optional[dict]:
        conn = self.db._get_conn()
        row = conn.execute(
            "SELECT * FROM simulation_portfolios WHERE id=?", (portfolio_id,)
        ).fetchone()
        if not row:
            conn.close()
            return None
        cols = [d[0] for d in conn.execute("SELECT * FROM simulation_portfolios LIMIT 0").description]
        conn.close()
        return dict(zip(cols, row))

    def list_all(self, include_archived: bool = False) -> List[dict]:
        conn = self.db._get_conn()
        if include_archived:
            rows = conn.execute("SELECT * FROM simulation_portfolios ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM simulation_portfolios WHERE status='active' ORDER BY created_at DESC"
            ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM simulation_portfolios LIMIT 0").description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]

    def update(self, portfolio_id: int, **kwargs) -> bool:
        conn = self.db._get_conn()
        allowed = {'name', 'initial_capital', 'description'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            conn.close()
            return False
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE simulation_portfolios SET {set_clause} WHERE id=?",
            list(updates.values()) + [portfolio_id]
        )
        conn.commit()
        conn.close()
        return True

    def archive(self, portfolio_id: int) -> bool:
        conn = self.db._get_conn()
        conn.execute(
            "UPDATE simulation_portfolios SET status='archived', updated_at=? WHERE id=?",
            (datetime.now().isoformat(), portfolio_id)
        )
        conn.commit()
        conn.close()
        return True

    def delete(self, portfolio_id: int) -> bool:
        """ポートフォリオ + 関連データを完全削除"""
        conn = self.db._get_conn()
        conn.execute("DELETE FROM trade_records WHERE portfolio_id=?", (portfolio_id,))
        conn.execute("DELETE FROM daily_pnl WHERE portfolio_id=?", (portfolio_id,))
        conn.execute("DELETE FROM risk_events WHERE portfolio_id=?", (portfolio_id,))
        conn.execute("DELETE FROM portfolio_bots WHERE portfolio_id=?", (portfolio_id,))
        try:
            conn.execute("DELETE FROM portfolio_bot_api WHERE portfolio_id=?", (portfolio_id,))
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM paper_signals WHERE portfolio_id=?", (portfolio_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM simulation_portfolios WHERE id=?", (portfolio_id,))
        conn.commit()
        conn.close()
        logger.info(f"[PortfolioManager] Portfolio {portfolio_id} deleted")
        return True

    def reset(self, portfolio_id: int) -> bool:
        """全トレード履歴削除 + 原資リセット"""
        conn = self.db._get_conn()
        conn.execute("DELETE FROM trade_records WHERE portfolio_id=?", (portfolio_id,))
        conn.execute("DELETE FROM daily_pnl WHERE portfolio_id=?", (portfolio_id,))
        conn.execute("DELETE FROM risk_events WHERE portfolio_id=?", (portfolio_id,))
        try:
            conn.execute(
                "DELETE FROM paper_signals WHERE portfolio_id=?", (portfolio_id,)
            )
        except Exception:
            pass  # paper_signals テーブルが未作成の場合
        conn.execute(
            "UPDATE simulation_portfolios SET updated_at=? WHERE id=?",
            (datetime.now().isoformat(), portfolio_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"[PortfolioManager] Portfolio {portfolio_id} reset")
        return True

    # ── BOTアサイン ──

    def assign_bots(self, portfolio_id: int, bot_names: List[str]):
        conn = self.db._get_conn()
        conn.execute("DELETE FROM portfolio_bots WHERE portfolio_id=?", (portfolio_id,))
        for bot in bot_names:
            conn.execute(
                "INSERT INTO portfolio_bots (portfolio_id, bot_name) VALUES (?,?)",
                (portfolio_id, bot)
            )
        conn.commit()
        conn.close()

    def get_bots(self, portfolio_id: int) -> List[str]:
        conn = self.db._get_conn()
        rows = conn.execute(
            "SELECT bot_name FROM portfolio_bots WHERE portfolio_id=?", (portfolio_id,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_portfolio_for_bot(self, bot_name: str) -> Optional[int]:
        """BOTが所属するアクティブポートフォリオIDを取得"""
        conn = self.db._get_conn()
        row = conn.execute(
            '''SELECT pb.portfolio_id FROM portfolio_bots pb
               JOIN simulation_portfolios sp ON pb.portfolio_id = sp.id
               WHERE pb.bot_name=? AND sp.status='active'
               ORDER BY sp.id DESC LIMIT 1''',
            (bot_name,)
        ).fetchone()
        conn.close()
        return row[0] if row else None

    # ── 残高・PNL計算 ──

    def get_balance(self, portfolio_id: int) -> dict:
        """ポートフォリオの現在残高・PNL計算"""
        portfolio = self.get(portfolio_id)
        if not portfolio:
            return {'error': 'not found'}

        conn = self.db._get_conn()
        initial = portfolio['initial_capital']

        # 確定PNL合計
        row = conn.execute(
            '''SELECT COALESCE(SUM(pnl_amount), 0), COALESCE(SUM(fee_amount), 0),
                      COUNT(*), SUM(CASE WHEN pnl_amount > 0 THEN 1 ELSE 0 END)
               FROM trade_records
               WHERE portfolio_id=? AND status='closed' ''',
            (portfolio_id,)
        ).fetchone()
        realized_pnl = row[0]
        total_fees = row[1]
        closed_count = row[2]
        win_count = row[3] or 0

        # 含み損益
        urow = conn.execute(
            '''SELECT COALESCE(SUM(
                   CASE WHEN side='long'
                        THEN (COALESCE(exit_price, entry_price) - entry_price) / entry_price * leverage * amount
                        ELSE (entry_price - COALESCE(exit_price, entry_price)) / entry_price * leverage * amount
                   END
               ), 0)
               FROM trade_records
               WHERE portfolio_id=? AND status='open' ''',
            (portfolio_id,)
        ).fetchone()
        unrealized_pnl = urow[0]

        conn.close()

        current_balance = initial + realized_pnl - total_fees
        total_pnl = realized_pnl - total_fees
        pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0

        return {
            'portfolio_id': portfolio_id,
            'name': portfolio['name'],
            'mode': portfolio.get('mode', 'paper'),
            'portfolio_type': portfolio.get('portfolio_type', 'paper'),
            'initial_capital': initial,
            'current_balance': round(current_balance, 2),
            'realized_pnl': round(realized_pnl, 2),
            'unrealized_pnl': round(unrealized_pnl, 2),
            'total_fees': round(total_fees, 2),
            'total_pnl': round(total_pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'closed_trades': closed_count,
            'win_count': win_count,
            'win_rate': round(win_count / closed_count * 100, 1) if closed_count > 0 else 0,
        }

    def get_daily_pnl_series(self, portfolio_id: int, mode: str = None) -> List[dict]:
        """日次PNL推移データ"""
        conn = self.db._get_conn()
        if mode:
            rows = conn.execute(
                "SELECT * FROM daily_pnl WHERE portfolio_id=? AND mode=? ORDER BY date",
                (portfolio_id, mode)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM daily_pnl WHERE portfolio_id=? ORDER BY date",
                (portfolio_id,)
            ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM daily_pnl LIMIT 0").description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
