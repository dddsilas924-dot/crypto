"""SQLiteによるヒストリカルデータ管理"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import asyncio

DB_PATH = Path("data/empire_monitor.db")

class HistoricalDB:
    def __init__(self, db_path: str = str(DB_PATH)):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_tables(self):
        conn = self._get_conn()
        c = conn.cursor()

        # OHLCV テーブル（1時間足・日足共通）
        c.execute('''CREATE TABLE IF NOT EXISTS ohlcv (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, timeframe, timestamp)
        )''')

        # 聖域価格マスタ
        c.execute('''CREATE TABLE IF NOT EXISTS sanctuary (
            symbol TEXT PRIMARY KEY,
            sanctuary_price REAL NOT NULL,
            sanctuary_date TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            is_new_listing INTEGER DEFAULT 0,
            updated_at TEXT
        )''')

        # セクター分類マスタ（Messari 11セクター対応）
        c.execute('''CREATE TABLE IF NOT EXISTS sector (
            symbol TEXT PRIMARY KEY,
            coingecko_id TEXT,
            categories TEXT,
            primary_sector TEXT,
            chain TEXT DEFAULT 'Other',
            subsector TEXT DEFAULT '',
            market_cap_rank INTEGER,
            updated_at TEXT
        )''')

        # アラートログ（フィードバック用）
        c.execute('''CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_time TEXT NOT NULL,
            alert_price REAL NOT NULL,
            tier1_score REAL, tier2_score REAL,
            regime TEXT,
            fear_greed INTEGER,
            price_1h_later REAL,
            price_24h_later REAL,
            price_48h_later REAL,
            pnl_1h_pct REAL,
            pnl_24h_pct REAL,
            pnl_48h_pct REAL,
            feedback_updated INTEGER DEFAULT 0
        )''')

        # ポジション管理
        c.execute('''CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TEXT NOT NULL,
            size REAL NOT NULL,
            leverage REAL DEFAULT 3.0,
            stop_loss REAL,
            take_profit REAL,
            current_price REAL,
            unrealized_pnl_pct REAL,
            status TEXT DEFAULT 'open',
            exit_price REAL,
            exit_time TEXT,
            realized_pnl_pct REAL,
            notes TEXT
        )''')

        # ウォッチリスト
        c.execute('''CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            added_at TEXT NOT NULL,
            reason TEXT,
            priority INTEGER DEFAULT 0
        )''')

        # デイリーサマリー
        c.execute('''CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            total_alerts INTEGER,
            tier1_passed INTEGER,
            tier2_passed INTEGER,
            regime_pattern TEXT,
            fear_greed_avg INTEGER,
            top_symbols TEXT,
            report_sent INTEGER DEFAULT 0
        )''')

        # インデックス
        c.execute('CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf ON ohlcv(symbol, timeframe)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ohlcv_ts ON ohlcv(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_alert_time ON alert_log(alert_time)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)')

        # マイグレーション: is_crypto カラム追加
        try:
            c.execute("ALTER TABLE sector ADD COLUMN is_crypto INTEGER DEFAULT 1")
        except Exception:
            pass  # 既に存在

        # マイグレーション: positions テーブルにライブ実行カラム追加
        for col, typ in [
            ("exchange_order_id", "TEXT"),
            ("tp_order_id", "TEXT"),
            ("sl_order_id", "TEXT"),
            ("margin_used", "REAL"),
            ("bot_name", "TEXT"),
        ]:
            try:
                c.execute(f"ALTER TABLE positions ADD COLUMN {col} {typ}")
            except Exception:
                pass  # 既に存在

        # 注文ログテーブル（ライブ実行の監査証跡）
        c.execute('''CREATE TABLE IF NOT EXISTS order_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            order_type TEXT NOT NULL,
            side TEXT NOT NULL,
            amount REAL NOT NULL,
            price REAL,
            exchange_order_id TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            metadata TEXT
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_order_log_time ON order_log(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_order_log_symbol ON order_log(symbol)')

        # Fear & Greed ヒストリカルテーブル
        c.execute('''CREATE TABLE IF NOT EXISTS fear_greed_history (
            date TEXT PRIMARY KEY,
            value INTEGER NOT NULL,
            classification TEXT
        )''')

        # Funding Rate 履歴テーブル
        c.execute('''CREATE TABLE IF NOT EXISTS funding_rate_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            funding_rate REAL NOT NULL,
            mark_price REAL,
            open_interest REAL,
            volume_24h REAL,
            source TEXT DEFAULT 'mexc',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, timestamp, source)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_fr_symbol_time ON funding_rate_history(symbol, timestamp)')

        # ── PNL管理: シミュレーション枠 ──
        c.execute('''CREATE TABLE IF NOT EXISTS simulation_portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            initial_capital REAL NOT NULL DEFAULT 10000.0,
            description TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS portfolio_bots (
            portfolio_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            PRIMARY KEY (portfolio_id, bot_name)
        )''')

        # ── PNL管理: 統一トレード記録 ──
        c.execute('''CREATE TABLE IF NOT EXISTS trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER,
            mode TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            leverage REAL DEFAULT 3.0,
            amount REAL,
            entry_price REAL,
            entry_time TEXT,
            exit_price REAL,
            exit_time TEXT,
            tp_price REAL,
            sl_price REAL,
            funding_rate REAL,
            status TEXT DEFAULT 'open',
            exit_reason TEXT,
            pnl_pct REAL,
            pnl_amount REAL,
            fee_amount REAL,
            exchange_order_id TEXT,
            metadata TEXT,
            trade_serial TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trade_records_mode ON trade_records(mode)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trade_records_bot ON trade_records(bot_name)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trade_records_status ON trade_records(status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trade_records_portfolio ON trade_records(portfolio_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trade_records_time ON trade_records(entry_time)')
        # trade_serial カラム追加（既存DB互換）
        try:
            c.execute('ALTER TABLE trade_records ADD COLUMN trade_serial TEXT')
        except Exception:
            pass

        # ── PNL管理: リスクイベント ──
        c.execute('''CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER,
            event_type TEXT NOT NULL,
            trigger_value REAL,
            limit_value REAL,
            action_taken TEXT,
            bot_name TEXT,
            timestamp TEXT NOT NULL
        )''')

        # ── PNL管理: 日次PNL集計 ──
        c.execute('''CREATE TABLE IF NOT EXISTS daily_pnl (
            date TEXT NOT NULL,
            portfolio_id INTEGER,
            mode TEXT NOT NULL,
            pnl_amount REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            trade_count INTEGER DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            cumulative_pnl REAL DEFAULT 0,
            PRIMARY KEY (date, portfolio_id, mode)
        )''')

        # マイグレーション: paper_signals に portfolio_id 追加
        try:
            c.execute("ALTER TABLE paper_signals ADD COLUMN portfolio_id INTEGER")
        except Exception:
            pass

        # マイグレーション: simulation_portfolios に mode, api_key, api_secret, portfolio_type, api_memo 追加
        for col, default in [('mode', "'paper'"), ('api_key', "''"), ('api_secret', "''"),
                             ('portfolio_type', "'paper'"), ('api_memo', "''")]:
            try:
                c.execute(f"ALTER TABLE simulation_portfolios ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass

        # Bot個別API管理テーブル（live_perbot用）
        c.execute('''CREATE TABLE IF NOT EXISTS portfolio_bot_api (
            portfolio_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            api_key TEXT DEFAULT '',
            api_secret TEXT DEFAULT '',
            api_memo TEXT DEFAULT '',
            exchange TEXT DEFAULT '',
            PRIMARY KEY (portfolio_id, bot_name)
        )''')

        conn.commit()
        conn.close()

    def upsert_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        """OHLCVデータをupsert"""
        if df is None or len(df) == 0:
            return 0
        conn = self._get_conn()
        count = 0
        for _, row in df.iterrows():
            ts = int(row.name.timestamp() * 1000) if hasattr(row.name, 'timestamp') else int(row['timestamp'])
            try:
                conn.execute(
                    'INSERT OR REPLACE INTO ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?,?)',
                    (symbol, timeframe, ts, row['open'], row['high'], row['low'], row['close'], row['volume'])
                )
                count += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return count

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> Optional[pd.DataFrame]:
        """OHLCVデータ取得"""
        conn = self._get_conn()
        df = pd.read_sql_query(
            'SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY timestamp DESC LIMIT ?',
            conn, params=(symbol, timeframe, limit)
        )
        conn.close()
        if len(df) == 0:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()
        return df

    def get_ohlcv_count(self, symbol: str, timeframe: str) -> int:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM ohlcv WHERE symbol=? AND timeframe=?', (symbol, timeframe))
        count = c.fetchone()[0]
        conn.close()
        return count

    def set_sanctuary(self, symbol: str, price: float, date: str, source: str = 'auto', is_new_listing: bool = False):
        conn = self._get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO sanctuary (symbol, sanctuary_price, sanctuary_date, source, is_new_listing, updated_at) VALUES (?,?,?,?,?,?)',
            (symbol, price, date, source, int(is_new_listing), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_sanctuary(self, symbol: str) -> Optional[float]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT sanctuary_price FROM sanctuary WHERE symbol=?', (symbol,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def is_new_listing(self, symbol: str) -> bool:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT is_new_listing FROM sanctuary WHERE symbol=?', (symbol,))
        row = c.fetchone()
        conn.close()
        return bool(row[0]) if row else False

    def set_sector(self, symbol: str, coingecko_id: str, categories: str,
                   primary_sector: str, rank: int, chain: str = 'Other', subsector: str = ''):
        conn = self._get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO sector (symbol, coingecko_id, categories, primary_sector, chain, subsector, market_cap_rank, updated_at) VALUES (?,?,?,?,?,?,?,?)',
            (symbol, coingecko_id, categories, primary_sector, chain, subsector, rank, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_sector(self, symbol: str) -> Optional[str]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT primary_sector FROM sector WHERE symbol=?', (symbol,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def get_sector_detail(self, symbol: str) -> Optional[dict]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT primary_sector, chain, subsector, market_cap_rank FROM sector WHERE symbol=?', (symbol,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'sector': row[0], 'chain': row[1], 'subsector': row[2], 'rank': row[3]}
        return None

    def get_symbols_by_sector(self, sector: str) -> List[str]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT symbol FROM sector WHERE primary_sector=?', (sector,))
        symbols = [r[0] for r in c.fetchall()]
        conn.close()
        return symbols

    def log_alert(self, symbol: str, price: float, t1_score: float, t2_score: float, regime: str, fg: int):
        conn = self._get_conn()
        conn.execute(
            'INSERT INTO alert_log (symbol, alert_time, alert_price, tier1_score, tier2_score, regime, fear_greed) VALUES (?,?,?,?,?,?,?)',
            (symbol, datetime.now().isoformat(), price, t1_score, t2_score, regime, fg)
        )
        conn.commit()
        conn.close()

    def add_position(self, symbol: str, side: str, entry_price: float, size: float, leverage: float, sl: float, tp: float, notes: str = ""):
        conn = self._get_conn()
        conn.execute(
            'INSERT INTO positions (symbol, side, entry_price, entry_time, size, leverage, stop_loss, take_profit, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (symbol, side, entry_price, datetime.now().isoformat(), size, leverage, sl, tp, 'open', notes)
        )
        conn.commit()
        conn.close()

    def get_open_positions(self) -> List[dict]:
        conn = self._get_conn()
        df = pd.read_sql_query("SELECT * FROM positions WHERE status='open'", conn)
        conn.close()
        return df.to_dict('records')

    def update_position_price(self, position_id: int, current_price: float, pnl_pct: float):
        conn = self._get_conn()
        conn.execute(
            'UPDATE positions SET current_price=?, unrealized_pnl_pct=? WHERE id=?',
            (current_price, pnl_pct, position_id)
        )
        conn.commit()
        conn.close()

    def close_position(self, position_id: int, exit_price: float, realized_pnl_pct: float):
        conn = self._get_conn()
        conn.execute(
            'UPDATE positions SET status=?, exit_price=?, exit_time=?, realized_pnl_pct=? WHERE id=?',
            ('closed', exit_price, datetime.now().isoformat(), realized_pnl_pct, position_id)
        )
        conn.commit()
        conn.close()

    def add_watchlist(self, symbol: str, reason: str = "", priority: int = 0):
        conn = self._get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO watchlist (symbol, added_at, reason, priority) VALUES (?,?,?,?)',
            (symbol, datetime.now().isoformat(), reason, priority)
        )
        conn.commit()
        conn.close()

    def get_watchlist(self) -> List[str]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT symbol FROM watchlist ORDER BY priority DESC')
        symbols = [r[0] for r in c.fetchall()]
        conn.close()
        return symbols

    def remove_watchlist(self, symbol: str):
        conn = self._get_conn()
        conn.execute('DELETE FROM watchlist WHERE symbol=?', (symbol,))
        conn.commit()
        conn.close()

    def get_unfeedback_alerts(self, hours_ago: int = 24) -> List[dict]:
        """フィードバック未処理のアラートを取得"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
        df = pd.read_sql_query(
            "SELECT * FROM alert_log WHERE feedback_updated=0 AND alert_time < ?",
            conn, params=(cutoff,)
        )
        conn.close()
        return df.to_dict('records')

    def update_alert_feedback(self, alert_id: int, price_1h: float, price_24h: float, price_48h: float, alert_price: float):
        pnl_1h = (price_1h - alert_price) / alert_price * 100 if price_1h else None
        pnl_24h = (price_24h - alert_price) / alert_price * 100 if price_24h else None
        pnl_48h = (price_48h - alert_price) / alert_price * 100 if price_48h else None
        conn = self._get_conn()
        conn.execute(
            'UPDATE alert_log SET price_1h_later=?, price_24h_later=?, price_48h_later=?, pnl_1h_pct=?, pnl_24h_pct=?, pnl_48h_pct=?, feedback_updated=1 WHERE id=?',
            (price_1h, price_24h, price_48h, pnl_1h, pnl_24h, pnl_48h, alert_id)
        )
        conn.commit()
        conn.close()

    def save_daily_summary(self, date: str, total_alerts: int, t1: int, t2: int, regime: str, fg: int, top_symbols: str):
        conn = self._get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO daily_summary (date, total_alerts, tier1_passed, tier2_passed, regime_pattern, fear_greed_avg, top_symbols) VALUES (?,?,?,?,?,?,?)',
            (date, total_alerts, t1, t2, regime, fg, top_symbols)
        )
        conn.commit()
        conn.close()
