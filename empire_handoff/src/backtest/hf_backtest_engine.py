"""高頻度Bot用バックテストエンジン - 1h足ベース

既存のBacktestEngine(日足)を変更せず、1h足専用エンジンを新規作成。
- 1h足OHLCVでTP/SL判定
- max_holding_hours による保有時間制限
- 1時間ごとのシグナル判定（1日複数エントリー可能）
- equity_curveは日次集計（表示用）
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from src.data.database import HistoricalDB


class HFBacktestEngine:
    """1h足ベースの高頻度バックテストエンジン"""

    TAKER_FEE_PCT = 0.06
    SLIPPAGE_PCT = 0.05
    COST_PER_SIDE_PCT = TAKER_FEE_PCT + SLIPPAGE_PCT
    ROUND_TRIP_COST_PCT = COST_PER_SIDE_PCT * 2  # 0.22%

    def __init__(self, bot_type: str, config: dict, db: HistoricalDB):
        self.bot_type = bot_type
        self.config = config
        self.db = db
        self.initial_capital = 1_000_000
        self.trades: List[dict] = []
        self.equity_curve: List[dict] = []

    def run(self, start_date: str, end_date: str) -> dict:
        """1h足バックテスト実行"""
        conn = self.db._get_conn()

        # Fear & Greed (日次 - 1h足内では同日のFGを使用)
        fg_rows = conn.execute(
            "SELECT date, value FROM fear_greed_history WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        fg_map = {r[0]: r[1] for r in fg_rows}

        # BTC 1h足
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000) + 86400000
        btc_1h = self._get_hourly_df(conn, 'BTC/USDT:USDT', start_ts, end_ts)
        if btc_1h is None or len(btc_1h) < 24:
            conn.close()
            return {"error": "BTC 1h data insufficient", "total_trades": 0}

        # BTC 日足 (シグナル用)
        btc_1d = self._get_daily_df(conn, 'BTC/USDT:USDT', start_date, end_date)

        # 全銘柄
        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM sector WHERE is_crypto=1"
        ).fetchall()]

        capital = float(self.initial_capital)
        self.trades = []
        self.equity_curve = []
        open_trades = []
        self.skipped_count = 0
        self.max_simultaneous = 0

        max_total = self.config.get('max_total_positions', 20)
        min_position_value = 10000
        max_holding_hours = self.config.get('max_holding_hours', 24)

        # 1h足のタイムスタンプを日付順にイテレート
        btc_timestamps = sorted(btc_1h.index)
        daily_equity = {}

        for ts in btc_timestamps:
            date_str = ts.strftime('%Y-%m-%d')
            hour_str = ts.strftime('%Y-%m-%d %H:%M')
            fg = fg_map.get(date_str, 50)

            # BTC 1h データ
            btc_close = float(btc_1h.loc[ts, 'close'])
            btc_prev_idx = btc_1h.index[btc_1h.index < ts]
            if len(btc_prev_idx) == 0:
                continue
            btc_prev_close = float(btc_1h.loc[btc_prev_idx[-1], 'close'])
            btc_return_1h = (btc_close - btc_prev_close) / btc_prev_close * 100

            # オープントレードのTP/SLチェック
            still_open = []
            for trade in open_trades:
                result = self._check_exit_hourly(conn, trade, ts)
                if result:
                    trade.update(result)
                    capital += trade['pnl_amount']
                    self.trades.append(trade)
                else:
                    still_open.append(trade)
            open_trades = still_open
            self.max_simultaneous = max(self.max_simultaneous, len(open_trades))

            # ポジション上限チェック
            if len(open_trades) >= max_total:
                daily_equity[date_str] = capital + self._calc_unrealized_hourly(conn, open_trades, ts)
                continue

            # シグナル判定（外部モジュール）
            import importlib
            try:
                module = importlib.import_module(f'src.signals.bot_{self.bot_type}')
                signal = module.check_signal_hf(
                    conn, fg, btc_return_1h, btc_1h, ts, symbols, self.config
                )
            except (ImportError, AttributeError):
                signal = None

            if signal:
                sym = signal['symbol']
                # 同一銘柄チェック
                sym_open = sum(1 for t in open_trades if t['symbol'] == sym)
                if sym_open >= 1:
                    self.skipped_count += 1
                else:
                    margin_in_use = sum(t['position_value'] for t in open_trades)
                    available = capital - margin_in_use
                    if available < min_position_value:
                        self.skipped_count += 1
                    else:
                        # 次の1h足の始値でエントリー
                        next_ts_idx = btc_timestamps.index(ts) + 1 if ts in btc_timestamps else None
                        if next_ts_idx and next_ts_idx < len(btc_timestamps):
                            next_ts = btc_timestamps[next_ts_idx]
                            entry_price = self._get_hourly_open(conn, sym, next_ts)
                            if entry_price:
                                signal['entry_price'] = entry_price
                                trade = self._simulate_entry(signal, available, next_ts)
                                if trade:
                                    open_trades.append(trade)

            # 日次equity記録
            eq = capital + self._calc_unrealized_hourly(conn, open_trades, ts)
            daily_equity[date_str] = eq

        # 残りを強制決済
        for trade in open_trades:
            last_ts = btc_timestamps[-1] if btc_timestamps else datetime.strptime(end_date, '%Y-%m-%d')
            result = self._force_exit_hourly(conn, trade, last_ts)
            if result:
                trade.update(result)
                capital += trade['pnl_amount']
                self.trades.append(trade)

        conn.close()

        # equity_curveを日次で構築
        for date_str in sorted(daily_equity.keys()):
            fg = fg_map.get(date_str, 50)
            self.equity_curve.append({
                'date': date_str,
                'capital': daily_equity[date_str],
                'fg': fg,
            })

        return self._calculate_metrics()

    def _get_hourly_df(self, conn, symbol: str, start_ts: int, end_ts: int) -> Optional[pd.DataFrame]:
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1h' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) == 0:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def _get_daily_df(self, conn, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000) + 86400000
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) == 0:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def _get_hourly_open(self, conn, symbol: str, ts: pd.Timestamp) -> Optional[float]:
        """指定時刻の1h足始値"""
        ts_ms = int(ts.timestamp() * 1000)
        row = conn.execute(
            "SELECT open FROM ohlcv WHERE symbol=? AND timeframe='1h' AND timestamp=?",
            (symbol, ts_ms)
        ).fetchone()
        return float(row[0]) if row else None

    def _simulate_entry(self, signal: dict, capital: float, entry_ts: pd.Timestamp) -> Optional[dict]:
        leverage = signal.get('adaptive_leverage', self.config.get('leverage', 5))
        position_pct = self.config.get('position_size_pct', 3)
        tp_pct = self.config.get('take_profit_pct', 2.0)
        sl_pct = self.config.get('stop_loss_pct', 1.0)
        max_hold_hours = self.config.get('max_holding_hours', 6)

        max_position_value = self.initial_capital * self.config.get('max_position_pct', 50) / 100
        position_value = min(capital * (position_pct / 100), max_position_value)

        return {
            'symbol': signal['symbol'],
            'entry_ts': entry_ts,
            'entry_date': entry_ts.strftime('%Y-%m-%d'),
            'entry_hour': entry_ts.strftime('%H:%M'),
            'entry_price': signal['entry_price'],
            'side': signal.get('side', 'long'),
            'leverage': leverage,
            'position_value': position_value,
            'tp_pct': tp_pct,
            'sl_pct': sl_pct,
            'max_holding_hours': max_hold_hours,
        }

    def _check_exit_hourly(self, conn, trade: dict, current_ts: pd.Timestamp) -> Optional[dict]:
        entry_ts = trade['entry_ts']
        holding_hours = (current_ts - entry_ts).total_seconds() / 3600

        if holding_hours < 0:
            return None

        # 現在の1h足のhigh/low/close
        ts_ms = int(current_ts.timestamp() * 1000)
        row = conn.execute(
            "SELECT high, low, close FROM ohlcv WHERE symbol=? AND timeframe='1h' AND timestamp=?",
            (trade['symbol'], ts_ms)
        ).fetchone()

        if not row:
            if holding_hours >= trade['max_holding_hours']:
                return self._force_exit_hourly(conn, trade, current_ts)
            return None

        high, low, close = float(row[0]), float(row[1]), float(row[2])
        entry = trade['entry_price']
        is_long = trade['side'] == 'long'

        tp_price = entry * (1 + trade['tp_pct'] / 100) if is_long else entry * (1 - trade['tp_pct'] / 100)
        sl_price = entry * (1 - trade['sl_pct'] / 100) if is_long else entry * (1 + trade['sl_pct'] / 100)

        if is_long:
            if high >= tp_price:
                return self._make_exit(trade, tp_price, current_ts, holding_hours, 'TP')
            if low <= sl_price:
                return self._make_exit(trade, sl_price, current_ts, holding_hours, 'SL')
        else:
            if low <= tp_price:
                return self._make_exit(trade, tp_price, current_ts, holding_hours, 'TP')
            if high >= sl_price:
                return self._make_exit(trade, sl_price, current_ts, holding_hours, 'SL')

        if holding_hours >= trade['max_holding_hours']:
            return self._make_exit(trade, close, current_ts, holding_hours, 'TIMEOUT')

        return None

    def _make_exit(self, trade: dict, exit_price: float, exit_ts: pd.Timestamp,
                   holding_hours: float, reason: str) -> dict:
        entry = trade['entry_price']
        is_long = trade['side'] == 'long'

        if is_long:
            raw_pnl_pct = (exit_price - entry) / entry * 100
        else:
            raw_pnl_pct = (entry - exit_price) / entry * 100

        net_pnl_pct = raw_pnl_pct - self.ROUND_TRIP_COST_PCT
        pnl_leveraged = net_pnl_pct * trade['leverage']
        pnl_amount = trade['position_value'] * (pnl_leveraged / 100)

        return {
            'exit_ts': exit_ts,
            'exit_date': exit_ts.strftime('%Y-%m-%d'),
            'exit_hour': exit_ts.strftime('%H:%M'),
            'exit_price': exit_price,
            'exit_reason': reason,
            'holding_hours': round(holding_hours, 1),
            'holding_days': round(holding_hours / 24, 1),
            'raw_pnl_pct': round(raw_pnl_pct, 3),
            'pnl_pct': round(net_pnl_pct, 3),
            'pnl_leveraged_pct': round(pnl_leveraged, 3),
            'pnl_amount': round(pnl_amount, 2),
        }

    def _force_exit_hourly(self, conn, trade: dict, ts: pd.Timestamp) -> Optional[dict]:
        ts_ms = int(ts.timestamp() * 1000)
        row = conn.execute(
            "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1h' AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            (trade['symbol'], ts_ms)
        ).fetchone()
        if not row:
            return None
        close = float(row[0])
        holding_hours = (ts - trade['entry_ts']).total_seconds() / 3600
        return self._make_exit(trade, close, ts, holding_hours, 'TIMEOUT')

    def _calc_unrealized_hourly(self, conn, open_trades: list, ts: pd.Timestamp) -> float:
        if not open_trades:
            return 0.0
        total = 0.0
        ts_ms = int(ts.timestamp() * 1000)
        for trade in open_trades:
            row = conn.execute(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1h' AND timestamp=?",
                (trade['symbol'], ts_ms)
            ).fetchone()
            if not row:
                continue
            close = float(row[0])
            entry = trade['entry_price']
            is_long = trade['side'] == 'long'
            raw_pnl = ((close - entry) / entry * 100) if is_long else ((entry - close) / entry * 100)
            net_pnl = raw_pnl - self.ROUND_TRIP_COST_PCT
            leveraged = net_pnl * trade['leverage']
            total += trade['position_value'] * (leveraged / 100)
        return total

    def _calculate_metrics(self) -> dict:
        if not self.trades:
            return {
                'total_trades': 0, 'win_rate': 0, 'profit_factor': 0,
                'total_return_pct': 0, 'max_drawdown_pct': 0, 'sharpe_ratio': 0,
                'avg_holding_hours': 0, 'trades_per_day': 0,
                'min_capital': self.initial_capital,
                'max_simultaneous': getattr(self, 'max_simultaneous', 0),
                'skipped_count': getattr(self, 'skipped_count', 0),
                'equity_curve': self.equity_curve,
                'final_capital': self.initial_capital,
            }

        wins = [t for t in self.trades if t.get('pnl_leveraged_pct', 0) > 0]
        losses = [t for t in self.trades if t.get('pnl_leveraged_pct', 0) <= 0]
        total = len(self.trades)
        win_rate = len(wins) / total * 100

        gross_profit = sum(t['pnl_amount'] for t in wins) if wins else 0
        gross_loss = abs(sum(t['pnl_amount'] for t in losses)) if losses else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else 999

        final_capital = self.initial_capital + sum(t.get('pnl_amount', 0) for t in self.trades)
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # MDD
        peak = self.initial_capital
        max_dd = 0.0
        min_capital = self.initial_capital
        for ec in self.equity_curve:
            eq = ec.get('capital', self.initial_capital)
            min_capital = min(min_capital, eq)
            peak = max(peak, eq)
            if peak > 0:
                dd = (eq - peak) / peak * 100
                max_dd = min(max_dd, dd)

        avg_hold = np.mean([t.get('holding_hours', 0) for t in self.trades])

        # Trades per day
        if self.equity_curve:
            n_days = len(self.equity_curve)
            trades_per_day = total / max(n_days, 1)
        else:
            trades_per_day = 0

        # Sharpe (日次)
        sharpe = 0.0
        if len(self.equity_curve) >= 2:
            daily_returns = []
            for i in range(1, len(self.equity_curve)):
                prev = self.equity_curve[i-1].get('capital', self.initial_capital)
                curr = self.equity_curve[i].get('capital', self.initial_capital)
                if prev > 0:
                    daily_returns.append((curr - prev) / prev)
            if daily_returns and np.std(daily_returns) > 0:
                sharpe = round(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(365), 2)

        return {
            'total_trades': total,
            'win_rate': round(win_rate, 1),
            'profit_factor': round(min(pf, 999), 2),
            'total_return_pct': round(total_return, 1),
            'max_drawdown_pct': round(max_dd, 1),
            'sharpe_ratio': sharpe,
            'avg_holding_hours': round(avg_hold, 1),
            'trades_per_day': round(trades_per_day, 1),
            'min_capital': round(min_capital),
            'final_capital': round(final_capital),
            'max_simultaneous': getattr(self, 'max_simultaneous', 0),
            'skipped_count': getattr(self, 'skipped_count', 0),
            'equity_curve': self.equity_curve,
        }
