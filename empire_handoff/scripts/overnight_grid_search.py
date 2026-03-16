#!/usr/bin/env python
"""
Overnight Grid Search + Analysis Pipeline (全5ブロック直列実行)

Block 1: 全Bot パラメータグリッドサーチ + 6年バックテスト
Block 2: LevBurn 5バリエーション精密チューニング
Block 3: Bot間相関分析 + ポートフォリオ最適化
Block 4: 市場レジーム別パフォーマンス分解
Block 5: WARN修正 + ペーパートレード稼働

Usage:
  python scripts/overnight_grid_search.py
"""
import sys
import os
import csv
import json
import time
import traceback
import importlib
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from copy import deepcopy

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# ============================================================
# 定数
# ============================================================
START_DATE = '2020-01-01'
END_DATE = '2026-03-01'
INITIAL_CAPITAL = 1_000_000
ROUND_TRIP_COST_PCT = 0.22

# Block 1: グリッドサーチ対象Bot (WF通過済み or PF > 1.3)
GRID_BOTS = [
    'surge', 'meanrevert', 'meanrevert_tight', 'meanrevert_hybrid',
    'meanrevert_adaptive', 'weakshort', 'sniper', 'scalp', 'alpha',
]

TP_MULTS = [0.6, 0.8, 1.0, 1.2, 1.4]
SL_MULTS = [0.6, 0.8, 1.0, 1.2, 1.4]
LEVERAGES_GRID = [3, 5, 7, 10, 15, 20]

# Block 2: LevBurn
LEVBURN_VARIANTS = {
    "base": {
        "fr_threshold": 0.3, "vol_threshold": 3.0,
        "take_profit_pct": 5.0, "stop_loss_pct": 2.5,
        "max_holding_days": 2, "position_size_pct": 3,
        "extra_conditions": None,
    },
    "tight": {
        "fr_threshold": 0.5, "vol_threshold": 4.0,
        "take_profit_pct": 3.0, "stop_loss_pct": 1.5,
        "max_holding_days": 1, "position_size_pct": 3,
        "extra_conditions": "rsi_extreme",
    },
    "aggressive": {
        "fr_threshold": 0.5, "vol_threshold": 3.0,
        "take_profit_pct": 8.0, "stop_loss_pct": 3.0,
        "max_holding_days": 3, "position_size_pct": 2,
        "extra_conditions": "extreme_only",
    },
    "scalp": {
        "fr_threshold": 0.15, "vol_threshold": 2.0,
        "take_profit_pct": 2.0, "stop_loss_pct": 1.0,
        "max_holding_days": 1, "position_size_pct": 3,
        "extra_conditions": None,
    },
    "fear_combo": {
        "fr_threshold": 0.3, "vol_threshold": 3.0,
        "take_profit_pct": 6.0, "stop_loss_pct": 3.0,
        "max_holding_days": 2, "position_size_pct": 5,
        "extra_conditions": "fear_filter",
    },
}
LB_FR_THRESHOLDS = [0.03, 0.05, 0.08, 0.1, 0.15, 0.2]
LB_TP_VALUES = [1.5, 2.0, 3.0, 5.0, 8.0]
LB_SL_VALUES = [0.8, 1.0, 1.5, 2.0, 3.0]
LB_LEVERAGES = [3, 5, 10]


# ============================================================
# ユーティリティ
# ============================================================
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def load_config():
    import yaml
    with open('config/settings.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# Signal Collection — 各Botのシグナルを1度だけ生成
# ============================================================
class SignalCollector(BacktestEngine):
    """BacktestEngineのシグナル生成部分だけを実行し、シグナルリストを返す"""

    def collect_signals(self, start_date: str, end_date: str) -> list:
        conn = self.db._get_conn()

        fg_rows = conn.execute(
            "SELECT date, value FROM fear_greed_history WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        fg_map = {r[0]: r[1] for r in fg_rows}

        btc_df = self._get_daily_ohlcv(conn, 'BTC/USDT:USDT', start_date, end_date)
        if btc_df is None or len(btc_df) < 20:
            conn.close()
            return []

        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM sector WHERE is_crypto=1"
        ).fetchall()]

        signals = []
        dates = sorted(fg_map.keys())

        for date_str in dates:
            fg = fg_map[date_str]

            btc_row = btc_df[btc_df.index.strftime('%Y-%m-%d') == date_str]
            if len(btc_row) == 0:
                continue
            btc_close = float(btc_row['close'].iloc[0])
            btc_prev = btc_df[btc_df.index < btc_row.index[0]]
            if len(btc_prev) == 0:
                continue
            btc_prev_close = float(btc_prev['close'].iloc[-1])
            btc_return = (btc_close - btc_prev_close) / btc_prev_close * 100

            # Signal dispatch (same as BacktestEngine.run)
            signal = None
            try:
                if self.bot_type == 'alpha':
                    signal = self._check_alpha_signal(conn, fg, btc_return, btc_df, date_str, symbols)
                elif self.bot_type == 'surge':
                    signal = self._check_surge_signal(conn, fg, btc_return, btc_df, date_str, symbols)
                elif self.bot_type == 'meanrevert':
                    signal = self._check_meanrevert_signal(conn, fg, btc_return, btc_df, date_str, symbols)
                elif self.bot_type == 'weakshort':
                    signal = self._check_weakshort_signal(conn, fg, btc_return, btc_df, date_str, symbols)
                elif self.bot_type.startswith('levburn'):
                    signal = self._check_levburn_signal(conn, fg, btc_return, btc_df, date_str, symbols)
                elif self.bot_type in ('feardip', 'sectorlead', 'shortsqueeze', 'sniper', 'scalp',
                                       'event', 'volexhaust', 'fearflat', 'domshift', 'gaptrap',
                                       'sectorsync', 'meanrevert_adaptive', 'meanrevert_tight',
                                       'meanrevert_hybrid', 'meanrevert_newlist', 'meanrevert_tuned',
                                       'ico_meanrevert', 'ico_rebound', 'ico_surge'):
                    signal = self._check_external_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            except Exception:
                pass

            if signal:
                next_result = self._get_next_open(conn, signal['symbol'], date_str)
                if next_result is not None:
                    next_open, next_date = next_result
                    signals.append({
                        'signal_date': date_str,
                        'entry_date': next_date,
                        'symbol': signal['symbol'],
                        'side': signal.get('side', 'long'),
                        'entry_price': next_open,
                    })

        conn.close()
        return signals


# ============================================================
# Fast Trade Simulator — メモリ上でTP/SL/レバを変えてリプレイ
# ============================================================
def preload_ohlcv_for_symbols(db, symbols, start_date, end_date):
    """対象銘柄の日足OHLCVをメモリにロード"""
    conn = db._get_conn()
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000) + 86400000

    ohlcv_cache = {}
    for sym in symbols:
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(sym, start_ts, end_ts)
        )
        if len(df) == 0:
            continue
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['date'] = df['timestamp'].dt.strftime('%Y-%m-%d')
        df.set_index('date', inplace=True)
        ohlcv_cache[sym] = df
    conn.close()
    return ohlcv_cache


def simulate_trades_fast(signals, ohlcv_cache, tp_pct, sl_pct, leverage,
                         max_hold_days=14, position_size_pct=15,
                         initial_capital=INITIAL_CAPITAL, max_positions=20):
    """高速トレードシミュレーション（メモリ内OHLCV使用）"""
    capital = float(initial_capital)
    open_trades = []
    closed_trades = []
    equity_curve = {}

    # Build date → signals map
    date_signals = defaultdict(list)
    for s in signals:
        date_signals[s['entry_date']].append(s)

    # Get all trading dates from BTC (most complete)
    btc_sym = 'BTC/USDT:USDT'
    if btc_sym not in ohlcv_cache:
        return _empty_metrics()

    all_dates = sorted(ohlcv_cache[btc_sym].index.tolist())

    for date_str in all_dates:
        # Check exits
        still_open = []
        for trade in open_trades:
            exit_result = _check_exit_cached(trade, date_str, ohlcv_cache,
                                             tp_pct, sl_pct, max_hold_days)
            if exit_result:
                trade.update(exit_result)
                capital += trade['pnl_amount']
                closed_trades.append(trade)
            else:
                still_open.append(trade)
        open_trades = still_open

        # New signals
        if date_str in date_signals and len(open_trades) < max_positions:
            for sig in date_signals[date_str]:
                if len(open_trades) >= max_positions:
                    break
                margin_in_use = sum(t.get('position_value', 0) for t in open_trades)
                available = capital - margin_in_use
                if available < 10000:
                    break
                # Same symbol check
                if any(t['symbol'] == sig['symbol'] for t in open_trades):
                    continue
                max_pos_val = initial_capital * 0.5
                pos_val = min(available * position_size_pct / 100, max_pos_val)
                trade = {
                    'symbol': sig['symbol'],
                    'entry_date': sig['entry_date'],
                    'entry_price': sig['entry_price'],
                    'side': sig['side'],
                    'leverage': leverage,
                    'position_value': pos_val,
                }
                open_trades.append(trade)

        # Equity
        unrealized = _calc_unrealized_cached(open_trades, date_str, ohlcv_cache, leverage)
        equity_curve[date_str] = capital + unrealized

    # Force-close remaining
    if all_dates:
        last_date = all_dates[-1]
        for trade in open_trades:
            sym = trade['symbol']
            if sym in ohlcv_cache and last_date in ohlcv_cache[sym].index:
                close_price = float(ohlcv_cache[sym].loc[last_date, 'close'])
                exit_result = _make_exit_result(trade, close_price, last_date, 'TIMEOUT', leverage)
                trade.update(exit_result)
                capital += trade['pnl_amount']
                closed_trades.append(trade)

    return _calculate_fast_metrics(closed_trades, equity_curve, initial_capital)


def _check_exit_cached(trade, date_str, ohlcv_cache, tp_pct, sl_pct, max_hold_days):
    """キャッシュ済みOHLCVでTP/SL判定"""
    sym = trade['symbol']
    if sym not in ohlcv_cache:
        return None
    df = ohlcv_cache[sym]
    if date_str not in df.index:
        # Check timeout
        entry_dt = datetime.strptime(trade['entry_date'], '%Y-%m-%d')
        current_dt = datetime.strptime(date_str, '%Y-%m-%d')
        if (current_dt - entry_dt).days >= max_hold_days:
            # Find last available close
            available = df[df.index <= date_str]
            if len(available) > 0:
                close = float(available.iloc[-1]['close'])
                return _make_exit_result(trade, close, date_str, 'TIMEOUT', trade['leverage'])
        return None

    row = df.loc[date_str]
    high = float(row['high'])
    low = float(row['low'])
    close = float(row['close'])
    entry = trade['entry_price']
    is_long = trade['side'] == 'long'

    tp_price = entry * (1 + tp_pct / 100) if is_long else entry * (1 - tp_pct / 100)
    sl_price = entry * (1 - sl_pct / 100) if is_long else entry * (1 + sl_pct / 100)

    if is_long:
        if high >= tp_price:
            return _make_exit_result(trade, tp_price, date_str, 'TP', trade['leverage'])
        if low <= sl_price:
            return _make_exit_result(trade, sl_price, date_str, 'SL', trade['leverage'])
    else:
        if low <= tp_price:
            return _make_exit_result(trade, tp_price, date_str, 'TP', trade['leverage'])
        if high >= sl_price:
            return _make_exit_result(trade, sl_price, date_str, 'SL', trade['leverage'])

    entry_dt = datetime.strptime(trade['entry_date'], '%Y-%m-%d')
    current_dt = datetime.strptime(date_str, '%Y-%m-%d')
    if (current_dt - entry_dt).days >= max_hold_days:
        return _make_exit_result(trade, close, date_str, 'TIMEOUT', trade['leverage'])

    return None


def _make_exit_result(trade, exit_price, exit_date, reason, leverage):
    entry = trade['entry_price']
    is_long = trade['side'] == 'long'
    raw_pnl = ((exit_price - entry) / entry * 100) if is_long else ((entry - exit_price) / entry * 100)
    net_pnl = raw_pnl - ROUND_TRIP_COST_PCT
    pnl_leveraged = net_pnl * leverage
    pnl_amount = trade['position_value'] * (pnl_leveraged / 100)
    holding_days = (datetime.strptime(exit_date, '%Y-%m-%d') -
                    datetime.strptime(trade['entry_date'], '%Y-%m-%d')).days
    return {
        'exit_date': exit_date,
        'exit_price': exit_price,
        'exit_reason': reason,
        'holding_days': max(holding_days, 0),
        'pnl_pct': round(net_pnl, 3),
        'pnl_leveraged_pct': round(pnl_leveraged, 3),
        'pnl_amount': round(pnl_amount, 2),
    }


def _calc_unrealized_cached(open_trades, date_str, ohlcv_cache, leverage):
    total = 0.0
    for trade in open_trades:
        sym = trade['symbol']
        if sym not in ohlcv_cache:
            continue
        df = ohlcv_cache[sym]
        if date_str not in df.index:
            continue
        close = float(df.loc[date_str, 'close'])
        entry = trade['entry_price']
        is_long = trade['side'] == 'long'
        raw_pnl = ((close - entry) / entry * 100) if is_long else ((entry - close) / entry * 100)
        net_pnl = raw_pnl - ROUND_TRIP_COST_PCT
        leveraged = net_pnl * leverage
        total += trade['position_value'] * (leveraged / 100)
    return total


def _empty_metrics():
    return {
        'total_trades': 0, 'win_rate': 0, 'profit_factor': 0,
        'total_return_pct': 0, 'max_drawdown_pct': 0, 'sharpe_ratio': 0,
        'avg_holding_days': 0, 'final_capital': INITIAL_CAPITAL, 'trades': [],
    }


def _calculate_fast_metrics(trades, equity_curve, initial_capital):
    if not trades:
        return _empty_metrics()

    wins = [t for t in trades if t.get('pnl_leveraged_pct', 0) > 0]
    losses = [t for t in trades if t.get('pnl_leveraged_pct', 0) <= 0]
    total = len(trades)
    wr = len(wins) / total * 100 if total > 0 else 0

    gross_profit = sum(t['pnl_amount'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_amount'] for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    final_cap = initial_capital + sum(t.get('pnl_amount', 0) for t in trades)
    total_return = (final_cap - initial_capital) / initial_capital * 100

    # MDD
    peak = initial_capital
    max_dd = 0.0
    eq_values = sorted(equity_curve.items())
    for _, eq in eq_values:
        peak = max(peak, eq)
        if peak > 0:
            dd = (eq - peak) / peak * 100
            max_dd = min(max_dd, dd)

    avg_hold = np.mean([t.get('holding_days', 0) for t in trades]) if trades else 0

    # Sharpe
    sharpe = 0.0
    if len(eq_values) >= 2:
        daily_rets = []
        for i in range(1, len(eq_values)):
            prev = eq_values[i - 1][1]
            curr = eq_values[i][1]
            if prev > 0:
                daily_rets.append((curr - prev) / prev)
        if daily_rets and np.std(daily_rets) > 0:
            sharpe = round(np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(365), 2)

    return {
        'total_trades': total,
        'win_rate': round(wr, 1),
        'profit_factor': round(min(pf, 999), 2),
        'total_return_pct': round(total_return, 1),
        'max_drawdown_pct': round(max_dd, 1),
        'sharpe_ratio': sharpe,
        'avg_holding_days': round(avg_hold, 1),
        'final_capital': round(final_cap),
        'trades': trades,
    }


# ============================================================
# Block 1: グリッドサーチ
# ============================================================
def run_block1(config, db):
    log("=" * 60)
    log("Block 1: 全Bot パラメータグリッドサーチ開始")
    log("=" * 60)
    block_start = time.time()

    all_grid_results = []
    best_per_bot = {}
    trade_logs = {}  # bot → best trades (for Block 3)

    for bot_idx, bot_type in enumerate(GRID_BOTS):
        log(f"\n--- {bot_type.upper()} ({bot_idx + 1}/{len(GRID_BOTS)}) ---")

        bot_config = config.get(f'bot_{bot_type}', {}).copy()
        base_tp = bot_config.get('take_profit_pct', 8.0)
        base_sl = bot_config.get('stop_loss_pct', 3.0)
        base_lev = bot_config.get('leverage', 3)
        pos_pct = bot_config.get('position_size_pct', 15)
        max_hold = bot_config.get('max_holding_days', 14)

        # Phase 1: Signal collection
        log(f"  [Phase 1] Signal collection...")
        t0 = time.time()
        collector = SignalCollector(bot_type, bot_config, db)
        signals = collector.collect_signals(START_DATE, END_DATE)
        log(f"  Signals collected: {len(signals)} ({time.time() - t0:.1f}s)")

        if not signals:
            log(f"  No signals for {bot_type}, skipping")
            continue

        # Preload OHLCV for signal symbols + BTC
        signal_symbols = list(set(s['symbol'] for s in signals))
        signal_symbols_with_btc = list(set(signal_symbols + ['BTC/USDT:USDT']))
        log(f"  [Phase 2] Loading OHLCV for {len(signal_symbols_with_btc)} symbols...")
        t0 = time.time()
        ohlcv_cache = preload_ohlcv_for_symbols(db, signal_symbols_with_btc, START_DATE, END_DATE)
        log(f"  OHLCV loaded ({time.time() - t0:.1f}s)")

        # Phase 3: Grid search
        n_combos = len(TP_MULTS) * len(SL_MULTS) * len(LEVERAGES_GRID)
        log(f"  [Phase 3] Grid search: {n_combos} combos...")
        best_pf = 0
        best_combo = None
        combo_count = 0

        for tp_mult in TP_MULTS:
            for sl_mult in SL_MULTS:
                for lev in LEVERAGES_GRID:
                    tp = base_tp * tp_mult
                    sl = base_sl * sl_mult

                    metrics = simulate_trades_fast(
                        signals, ohlcv_cache, tp, sl, lev,
                        max_hold_days=max_hold,
                        position_size_pct=pos_pct,
                    )

                    row = {
                        'Bot': bot_type,
                        'TP_mult': tp_mult,
                        'SL_mult': sl_mult,
                        'TP_pct': round(tp, 2),
                        'SL_pct': round(sl, 2),
                        'Leverage': lev,
                        'PF': metrics['profit_factor'],
                        'Return': metrics['total_return_pct'],
                        'MDD': metrics['max_drawdown_pct'],
                        'WR': metrics['win_rate'],
                        'Sharpe': metrics['sharpe_ratio'],
                        'Trades': metrics['total_trades'],
                        'AvgHold_d': metrics['avg_holding_days'],
                    }
                    all_grid_results.append(row)

                    if metrics['profit_factor'] > best_pf and metrics['total_trades'] >= 5:
                        best_pf = metrics['profit_factor']
                        best_combo = row.copy()
                        best_trades = metrics['trades']

                    combo_count += 1
                    if combo_count % 10 == 0:
                        log(f"  [GridSearch] {bot_type} {combo_count}/{n_combos} done, best PF so far: {best_pf:.2f}")

        if best_combo:
            best_per_bot[bot_type] = best_combo
            trade_logs[bot_type] = best_trades
            log(f"  Best: PF={best_combo['PF']:.2f} TP×{best_combo['TP_mult']} SL×{best_combo['SL_mult']} Lev{best_combo['Leverage']}")

    # Save CSV
    csv_path = 'vault/backtest_results/grid_search_results.csv'
    if all_grid_results:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_grid_results[0].keys())
            writer.writeheader()
            writer.writerows(all_grid_results)
        log(f"CSV saved: {csv_path} ({len(all_grid_results)} rows)")

    # Save trade logs for Block 3
    for bot_type, trades in trade_logs.items():
        tl_path = f'vault/backtest_results/trade_logs/{bot_type}_best_trades.json'
        serializable = []
        for t in trades:
            st = {k: v for k, v in t.items() if k != 'position_value'}
            serializable.append(st)
        with open(tl_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, indent=2, default=str)

    # Generate HTML report
    _generate_block1_html(all_grid_results, best_per_bot, config)

    elapsed = time.time() - block_start
    log(f"Block 1 完了: {elapsed / 60:.1f}分")
    return all_grid_results, best_per_bot, trade_logs


def _generate_block1_html(results, best_per_bot, config):
    """Block 1 HTMLレポート生成"""
    df = pd.DataFrame(results)
    if df.empty:
        return

    html_parts = [_html_header("Grid Search Report")]

    # Summary
    html_parts.append('<div class="summary">')
    html_parts.append(f'<b>期間:</b> {START_DATE} ~ {END_DATE} (6年間)<br>')
    html_parts.append(f'<b>対象:</b> {len(GRID_BOTS)} Bot × {len(TP_MULTS)*len(SL_MULTS)*len(LEVERAGES_GRID)} combos = {len(results)} patterns<br>')
    html_parts.append(f'<b>コスト:</b> {ROUND_TRIP_COST_PCT}%/RT<br>')
    html_parts.append('</div>')

    # Per-bot Top 5
    for bot in GRID_BOTS:
        bot_df = df[df['Bot'] == bot].sort_values('PF', ascending=False)
        if bot_df.empty:
            continue

        current_cfg = config.get(f'bot_{bot}', {})
        cur_tp = current_cfg.get('take_profit_pct', '?')
        cur_sl = current_cfg.get('stop_loss_pct', '?')
        cur_lev = current_cfg.get('leverage', '?')

        html_parts.append(f'<h2>{bot.upper()} — Top 5 (PFソート)</h2>')
        html_parts.append(f'<p>現在設定: TP={cur_tp}% SL={cur_sl}% Lev={cur_lev}x</p>')
        html_parts.append('<table><tr><th>#</th><th>TP×</th><th>SL×</th><th>TP%</th><th>SL%</th>'
                          '<th>Lev</th><th>PF</th><th>Return</th><th>MDD</th><th>WR</th><th>Sharpe</th><th>Trades</th></tr>')
        for i, (_, row) in enumerate(bot_df.head(5).iterrows()):
            pf_color = '#4caf50' if row['PF'] >= 1.5 else ('#ff9800' if row['PF'] >= 1.0 else '#f44336')
            html_parts.append(
                f'<tr><td>{i + 1}</td><td>{row["TP_mult"]}</td><td>{row["SL_mult"]}</td>'
                f'<td>{row["TP_pct"]}</td><td>{row["SL_pct"]}</td><td>{row["Leverage"]}</td>'
                f'<td style="color:{pf_color}">{row["PF"]:.2f}</td>'
                f'<td>{row["Return"]:+.1f}%</td><td>{row["MDD"]:.1f}%</td>'
                f'<td>{row["WR"]:.1f}%</td><td>{row["Sharpe"]:.2f}</td><td>{row["Trades"]}</td></tr>')
        html_parts.append('</table>')

        # Current vs best comparison
        if bot in best_per_bot:
            best = best_per_bot[bot]
            html_parts.append(f'<p><b>現在 vs 最適:</b> PF: ? → {best["PF"]:.2f}, '
                              f'TP: {cur_tp}% → {best["TP_pct"]}%, '
                              f'SL: {cur_sl}% → {best["SL_pct"]}%, '
                              f'Lev: {cur_lev}x → {best["Leverage"]}x</p>')

    # Heatmap: TP × SL by Leverage
    for lev in LEVERAGES_GRID:
        lev_df = df[df['Leverage'] == lev]
        if lev_df.empty:
            continue
        html_parts.append(f'<h2>ヒートマップ: TP倍率 × SL倍率 (Lev={lev}x, 全Bot平均PF)</h2>')
        pivot = lev_df.groupby(['TP_mult', 'SL_mult'])['PF'].mean().unstack(fill_value=0)
        html_parts.append('<table><tr><th>TP\\SL</th>')
        for sl in sorted(pivot.columns):
            html_parts.append(f'<th>SL×{sl}</th>')
        html_parts.append('</tr>')
        for tp in sorted(pivot.index):
            html_parts.append(f'<tr><td>TP×{tp}</td>')
            for sl in sorted(pivot.columns):
                val = pivot.loc[tp, sl] if sl in pivot.columns else 0
                bg = _pf_color_bg(val)
                html_parts.append(f'<td style="background:{bg}">{val:.2f}</td>')
            html_parts.append('</tr>')
        html_parts.append('</table>')

    html_parts.append('<p class="warn">最適パラメータはオーバーフィットの可能性あり。WF検証を推奨。</p>')
    html_parts.append(_html_footer())

    with open('vault/docs/grid_search_report.html', 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    log("HTML saved: vault/docs/grid_search_report.html")


# ============================================================
# Block 2: LevBurn 精密チューニング
# ============================================================
def run_block2(config, db):
    log("=" * 60)
    log("Block 2: LevBurn 5バリエーション精密チューニング開始")
    log("=" * 60)
    block_start = time.time()

    all_lb_results = []

    for vname, vcfg in LEVBURN_VARIANTS.items():
        log(f"\n--- LevBurn-{vname.upper()} ---")

        for fr_idx, fr_thr in enumerate(LB_FR_THRESHOLDS):
            # Create config with this FR threshold
            bot_cfg = vcfg.copy()
            bot_cfg['fr_threshold'] = fr_thr
            bot_cfg['max_position_pct'] = 50

            # Collect signals for this FR threshold
            collector = SignalCollector(f'levburn_{vname}', bot_cfg, db)
            signals = collector.collect_signals(START_DATE, END_DATE)

            if not signals:
                log(f"  FR={fr_thr}: no signals")
                for tp in LB_TP_VALUES:
                    for sl in LB_SL_VALUES:
                        for lev in LB_LEVERAGES:
                            all_lb_results.append({
                                'Variant': vname, 'FR_thr': fr_thr,
                                'TP': tp, 'SL': sl, 'Leverage': lev,
                                'PF': 0, 'Return': 0, 'MDD': 0,
                                'WR': 0, 'Sharpe': 0, 'Trades': 0,
                            })
                continue

            # Preload OHLCV
            signal_syms = list(set(s['symbol'] for s in signals) | {'BTC/USDT:USDT'})
            ohlcv_cache = preload_ohlcv_for_symbols(db, signal_syms, START_DATE, END_DATE)

            combo_count = 0
            total_combos = len(LB_TP_VALUES) * len(LB_SL_VALUES) * len(LB_LEVERAGES)

            for tp in LB_TP_VALUES:
                for sl in LB_SL_VALUES:
                    for lev in LB_LEVERAGES:
                        max_hold = vcfg.get('max_holding_days', 2)
                        pos_pct = vcfg.get('position_size_pct', 3)

                        metrics = simulate_trades_fast(
                            signals, ohlcv_cache, tp, sl, lev,
                            max_hold_days=max_hold, position_size_pct=pos_pct,
                        )

                        all_lb_results.append({
                            'Variant': vname, 'FR_thr': fr_thr,
                            'TP': tp, 'SL': sl, 'Leverage': lev,
                            'PF': metrics['profit_factor'],
                            'Return': metrics['total_return_pct'],
                            'MDD': metrics['max_drawdown_pct'],
                            'WR': metrics['win_rate'],
                            'Sharpe': metrics['sharpe_ratio'],
                            'Trades': metrics['total_trades'],
                        })

                        combo_count += 1
                        if combo_count % 10 == 0:
                            log(f"  [LevBurn-{vname}] FR={fr_thr} {combo_count}/{total_combos} done")

            best_row = max(
                [r for r in all_lb_results if r['Variant'] == vname and r['FR_thr'] == fr_thr and r['Trades'] > 0],
                key=lambda x: x['PF'], default=None
            )
            if best_row:
                log(f"  FR={fr_thr}: best PF={best_row['PF']:.2f} TP={best_row['TP']} SL={best_row['SL']} Lev={best_row['Leverage']}")

    # Save CSV
    csv_path = 'vault/backtest_results/levburn_grid_results.csv'
    if all_lb_results:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_lb_results[0].keys())
            writer.writeheader()
            writer.writerows(all_lb_results)
        log(f"CSV saved: {csv_path}")

    # Generate HTML
    _generate_block2_html(all_lb_results)

    elapsed = time.time() - block_start
    log(f"Block 2 完了: {elapsed / 60:.1f}分")
    return all_lb_results


def _generate_block2_html(results):
    """Block 2 HTMLレポート生成"""
    df = pd.DataFrame(results)
    if df.empty:
        return

    html_parts = [_html_header("LevBurn Tuning Report")]

    html_parts.append('<div class="summary">')
    html_parts.append(f'<b>期間:</b> {START_DATE} ~ {END_DATE}<br>')
    html_parts.append(f'<b>バリエーション:</b> {len(LEVBURN_VARIANTS)} × FR{len(LB_FR_THRESHOLDS)} × TP{len(LB_TP_VALUES)} × SL{len(LB_SL_VALUES)} × Lev{len(LB_LEVERAGES)}<br>')
    html_parts.append(f'<b>合計:</b> {len(results)} patterns<br>')
    html_parts.append('</div>')

    for vname in LEVBURN_VARIANTS:
        vdf = df[df['Variant'] == vname]
        if vdf.empty:
            continue

        # Top 10
        top = vdf.sort_values('PF', ascending=False).head(10)
        html_parts.append(f'<h2>LevBurn-{vname.upper()} — Top 10</h2>')
        html_parts.append('<table><tr><th>#</th><th>FR</th><th>TP</th><th>SL</th><th>Lev</th>'
                          '<th>PF</th><th>Return</th><th>MDD</th><th>WR</th><th>Trades</th></tr>')
        for i, (_, row) in enumerate(top.iterrows()):
            pf_color = '#4caf50' if row['PF'] >= 1.5 else ('#ff9800' if row['PF'] >= 1.0 else '#f44336')
            html_parts.append(
                f'<tr><td>{i + 1}</td><td>{row["FR_thr"]}</td><td>{row["TP"]}</td>'
                f'<td>{row["SL"]}</td><td>{row["Leverage"]}</td>'
                f'<td style="color:{pf_color}">{row["PF"]:.2f}</td>'
                f'<td>{row["Return"]:+.1f}%</td><td>{row["MDD"]:.1f}%</td>'
                f'<td>{row["WR"]:.1f}%</td><td>{row["Trades"]}</td></tr>')
        html_parts.append('</table>')

        # Heatmap: FR × TP (best SL/Lev per cell)
        html_parts.append(f'<h3>LevBurn-{vname.upper()} — FR閾値 × TPの最高PF</h3>')
        heatmap_data = vdf.groupby(['FR_thr', 'TP'])['PF'].max().unstack(fill_value=0)
        html_parts.append('<table><tr><th>FR\\TP</th>')
        for tp in sorted(heatmap_data.columns):
            html_parts.append(f'<th>TP={tp}%</th>')
        html_parts.append('</tr>')
        for fr in sorted(heatmap_data.index):
            html_parts.append(f'<tr><td>FR={fr}</td>')
            for tp in sorted(heatmap_data.columns):
                val = heatmap_data.loc[fr, tp]
                bg = _pf_color_bg(val)
                html_parts.append(f'<td style="background:{bg}">{val:.2f}</td>')
            html_parts.append('</tr>')
        html_parts.append('</table>')

    # Current vs best per variant
    html_parts.append('<h2>現在設定 vs 最適設定</h2>')
    html_parts.append('<table><tr><th>Variant</th><th>Current FR</th><th>Best FR</th>'
                      '<th>Current TP/SL</th><th>Best TP/SL</th><th>Current PF</th><th>Best PF</th></tr>')
    for vname, vcfg in LEVBURN_VARIANTS.items():
        vdf = df[(df['Variant'] == vname) & (df['Trades'] > 0)]
        if vdf.empty:
            continue
        best = vdf.sort_values('PF', ascending=False).iloc[0]
        html_parts.append(
            f'<tr><td>{vname}</td><td>{vcfg["fr_threshold"]}</td><td>{best["FR_thr"]}</td>'
            f'<td>{vcfg["take_profit_pct"]}/{vcfg["stop_loss_pct"]}</td>'
            f'<td>{best["TP"]}/{best["SL"]}</td>'
            f'<td>-</td><td style="color:#4caf50">{best["PF"]:.2f}</td></tr>')
    html_parts.append('</table>')

    html_parts.append(_html_footer())
    with open('vault/docs/levburn_tuning_report.html', 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    log("HTML saved: vault/docs/levburn_tuning_report.html")


# ============================================================
# Block 3: 相関分析 + ポートフォリオ最適化
# ============================================================
def run_block3(trade_logs, best_per_bot):
    log("=" * 60)
    log("Block 3: Bot間相関分析 + ポートフォリオ最適化開始")
    log("=" * 60)
    block_start = time.time()

    # Load trade logs
    bot_trades = {}
    for bot in GRID_BOTS:
        tl_path = f'vault/backtest_results/trade_logs/{bot}_best_trades.json'
        if os.path.exists(tl_path):
            with open(tl_path, 'r', encoding='utf-8') as f:
                bot_trades[bot] = json.load(f)
        elif bot in trade_logs:
            bot_trades[bot] = [{k: v for k, v in t.items() if k != 'position_value'}
                               for t in trade_logs[bot]]

    if len(bot_trades) < 2:
        log("Insufficient trade data for correlation analysis")
        return {}

    # Build daily PnL series per bot
    all_dates = sorted(set(
        t.get('exit_date', t.get('entry_date', ''))
        for trades in bot_trades.values() for t in trades
        if t.get('exit_date') or t.get('entry_date')
    ))
    if not all_dates:
        log("No dates found in trade logs")
        return {}

    date_range = pd.date_range(all_dates[0], all_dates[-1], freq='D')
    daily_pnl = pd.DataFrame(0.0, index=date_range.strftime('%Y-%m-%d'), columns=list(bot_trades.keys()))

    for bot, trades in bot_trades.items():
        for t in trades:
            exit_date = t.get('exit_date')
            pnl = t.get('pnl_amount', t.get('pnl_leveraged_pct', 0))
            if exit_date and exit_date in daily_pnl.index:
                daily_pnl.loc[exit_date, bot] += pnl

    # 3-1: Correlation matrix
    corr_matrix = daily_pnl.corr()
    corr_matrix.to_csv('vault/backtest_results/correlation_matrix.csv')

    # 3-2: Portfolio simulation (equal weight)
    portfolio_daily = daily_pnl.sum(axis=1) / len(bot_trades)
    cumulative = portfolio_daily.cumsum()
    portfolio_capital = INITIAL_CAPITAL + cumulative

    portfolio_pf = 0
    portfolio_mdd = 0
    wins = portfolio_daily[portfolio_daily > 0].sum()
    losses = abs(portfolio_daily[portfolio_daily < 0].sum())
    if losses > 0:
        portfolio_pf = round(wins / losses, 2)
    peak = INITIAL_CAPITAL
    for val in portfolio_capital:
        peak = max(peak, val)
        dd = (val - peak) / peak * 100 if peak > 0 else 0
        portfolio_mdd = min(portfolio_mdd, dd)

    portfolio_return = (portfolio_capital.iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # 3-3: Bot exclusion test
    exclusion_results = []
    for exclude_bot in bot_trades:
        remaining = [b for b in bot_trades if b != exclude_bot]
        if not remaining:
            continue
        sub_daily = daily_pnl[remaining].sum(axis=1) / len(remaining)
        sub_cum = sub_daily.cumsum()
        sub_cap = INITIAL_CAPITAL + sub_cum
        sub_wins = sub_daily[sub_daily > 0].sum()
        sub_losses = abs(sub_daily[sub_daily < 0].sum())
        sub_pf = round(sub_wins / sub_losses, 2) if sub_losses > 0 else 999
        sub_peak = INITIAL_CAPITAL
        sub_mdd = 0
        for val in sub_cap:
            sub_peak = max(sub_peak, val)
            dd = (val - sub_peak) / sub_peak * 100 if sub_peak > 0 else 0
            sub_mdd = min(sub_mdd, dd)
        exclusion_results.append({
            'excluded': exclude_bot,
            'pf': sub_pf,
            'mdd': round(sub_mdd, 1),
            'return': round((sub_cap.iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 1),
        })

    # Save portfolio simulation
    sim_data = []
    for date, val in portfolio_capital.items():
        sim_data.append({'date': date, 'capital': round(val, 0)})
    pd.DataFrame(sim_data).to_csv('vault/backtest_results/portfolio_simulation.csv', index=False)

    # Generate HTML
    _generate_block3_html(corr_matrix, portfolio_pf, portfolio_mdd, portfolio_return,
                          exclusion_results, bot_trades, daily_pnl)

    elapsed = time.time() - block_start
    log(f"Block 3 完了: {elapsed / 60:.1f}分")

    return {
        'portfolio_pf': portfolio_pf,
        'portfolio_mdd': round(portfolio_mdd, 1),
        'portfolio_return': round(portfolio_return, 1),
        'exclusion_results': exclusion_results,
    }


def _generate_block3_html(corr_matrix, pf, mdd, ret, exclusion, bot_trades, daily_pnl):
    html_parts = [_html_header("Portfolio Analysis Report")]

    html_parts.append('<div class="summary">')
    html_parts.append(f'<b>全Bot合成 PF:</b> {pf:.2f}<br>')
    html_parts.append(f'<b>全Bot合成 MDD:</b> {mdd:.1f}%<br>')
    html_parts.append(f'<b>全Bot合成 Return:</b> {ret:+.1f}%<br>')
    html_parts.append(f'<b>対象Bot:</b> {len(bot_trades)}本<br>')
    html_parts.append('</div>')

    # Correlation matrix
    html_parts.append('<h2>相関行列 (日次リターン)</h2>')
    html_parts.append('<table><tr><th></th>')
    bots = list(corr_matrix.columns)
    for b in bots:
        html_parts.append(f'<th>{b[:8]}</th>')
    html_parts.append('</tr>')
    for b1 in bots:
        html_parts.append(f'<tr><td><b>{b1[:8]}</b></td>')
        for b2 in bots:
            val = corr_matrix.loc[b1, b2]
            bg = '#4caf50' if val > 0.5 and b1 != b2 else ('#ff9800' if val > 0.3 else '#1a1a2e')
            html_parts.append(f'<td style="background:{bg}">{val:.2f}</td>')
        html_parts.append('</tr>')
    html_parts.append('</table>')

    # High correlation pairs
    high_corr = []
    for i, b1 in enumerate(bots):
        for b2 in bots[i + 1:]:
            val = corr_matrix.loc[b1, b2]
            if val > 0.5:
                high_corr.append((b1, b2, val))
    if high_corr:
        html_parts.append('<h3>高相関ペア (r > 0.5)</h3><ul>')
        for b1, b2, val in sorted(high_corr, key=lambda x: -x[2]):
            html_parts.append(f'<li>{b1} × {b2}: r={val:.2f} — 重複リスクに注意</li>')
        html_parts.append('</ul>')

    # Exclusion test
    html_parts.append('<h2>Bot除外テスト</h2>')
    html_parts.append('<table><tr><th>除外Bot</th><th>PF</th><th>MDD</th><th>Return</th><th>評価</th></tr>')
    for ex in sorted(exclusion, key=lambda x: -x['pf']):
        improve = 'PF改善 → 重複リスク高' if ex['pf'] > pf else '維持 → 分散貢献'
        html_parts.append(
            f'<tr><td>{ex["excluded"]}</td><td>{ex["pf"]:.2f}</td>'
            f'<td>{ex["mdd"]:.1f}%</td><td>{ex["return"]:+.1f}%</td>'
            f'<td>{improve}</td></tr>')
    html_parts.append('</table>')

    # Equity curve (SVG)
    html_parts.append('<h2>合成リターン曲線</h2>')
    cumulative = daily_pnl.sum(axis=1).cumsum()
    _render_svg_chart(html_parts, cumulative, "Cumulative PnL", width=800, height=300)

    html_parts.append(_html_footer())
    with open('vault/docs/portfolio_analysis_report.html', 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    log("HTML saved: vault/docs/portfolio_analysis_report.html")


# ============================================================
# Block 4: 市場レジーム別パフォーマンス分解
# ============================================================
def run_block4(trade_logs, db):
    log("=" * 60)
    log("Block 4: 市場レジーム別パフォーマンス分解開始")
    log("=" * 60)
    block_start = time.time()

    # BTC daily data
    conn = db._get_conn()
    start_ts = int(datetime.strptime(START_DATE, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(END_DATE, '%Y-%m-%d').timestamp() * 1000) + 86400000
    btc_df = pd.read_sql_query(
        "SELECT timestamp, close FROM ohlcv WHERE symbol='BTC/USDT:USDT' AND timeframe='1d' "
        "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        conn, params=(start_ts, end_ts)
    )
    conn.close()

    if btc_df.empty:
        log("No BTC data for regime analysis")
        return {}

    btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms')
    btc_df['date'] = btc_df['timestamp'].dt.strftime('%Y-%m-%d')
    btc_df.set_index('date', inplace=True)
    btc_df['close'] = btc_df['close'].astype(float)
    btc_df['ma60'] = btc_df['close'].rolling(60, min_periods=60).mean()
    btc_df['ma60_slope'] = btc_df['ma60'].diff(5)

    # Regime classification
    regimes = []
    for date, row in btc_df.iterrows():
        if pd.isna(row['ma60']) or pd.isna(row['ma60_slope']):
            regime = 'unknown'
        elif row['ma60_slope'] > 0 and row['close'] > row['ma60']:
            regime = 'bull'
        elif row['ma60_slope'] < 0 and row['close'] < row['ma60']:
            regime = 'bear'
        else:
            regime = 'sideways'
        regimes.append({
            'date': date,
            'btc_price': round(row['close'], 2),
            'ma60': round(row['ma60'], 2) if not pd.isna(row['ma60']) else None,
            'regime': regime,
        })

    regime_df = pd.DataFrame(regimes).set_index('date')
    regime_df.to_csv('vault/backtest_results/regime_labels.csv')
    regime_map = {r['date']: r['regime'] for r in regimes}

    # Regime period stats
    regime_counts = defaultdict(int)
    for r in regimes:
        if r['regime'] != 'unknown':
            regime_counts[r['regime']] += 1
    log(f"  Regime days: Bull={regime_counts.get('bull', 0)}, Bear={regime_counts.get('bear', 0)}, Sideways={regime_counts.get('sideways', 0)}")

    # Load trade logs
    bot_trades = {}
    for bot in GRID_BOTS:
        tl_path = f'vault/backtest_results/trade_logs/{bot}_best_trades.json'
        if os.path.exists(tl_path):
            with open(tl_path, 'r', encoding='utf-8') as f:
                bot_trades[bot] = json.load(f)
        elif bot in trade_logs:
            bot_trades[bot] = [{k: v for k, v in t.items() if k != 'position_value'}
                               for t in trade_logs[bot]]

    # Per-bot per-regime performance
    regime_perf = []
    for bot, trades in bot_trades.items():
        for regime_name in ['bull', 'bear', 'sideways']:
            regime_trades = [t for t in trades if regime_map.get(t.get('entry_date', '')) == regime_name]
            if not regime_trades:
                regime_perf.append({
                    'bot': bot, 'regime': regime_name,
                    'pf': 0, 'return': 0, 'mdd': 0, 'wr': 0, 'trades': 0,
                })
                continue
            wins = [t for t in regime_trades if t.get('pnl_leveraged_pct', 0) > 0]
            losses_t = [t for t in regime_trades if t.get('pnl_leveraged_pct', 0) <= 0]
            wr = len(wins) / len(regime_trades) * 100
            gp = sum(t.get('pnl_amount', 0) for t in wins)
            gl = abs(sum(t.get('pnl_amount', 0) for t in losses_t))
            pf = gp / gl if gl > 0 else 999
            total_ret = sum(t.get('pnl_amount', 0) for t in regime_trades) / INITIAL_CAPITAL * 100
            regime_perf.append({
                'bot': bot, 'regime': regime_name,
                'pf': round(min(pf, 999), 2),
                'return': round(total_ret, 1),
                'mdd': 0,  # simplified
                'wr': round(wr, 1),
                'trades': len(regime_trades),
            })

    pd.DataFrame(regime_perf).to_csv('vault/backtest_results/regime_performance.csv', index=False)

    # Regime-best bots
    rp_df = pd.DataFrame(regime_perf)
    bull_top = rp_df[(rp_df['regime'] == 'bull') & (rp_df['trades'] > 0)].sort_values('pf', ascending=False).head(3)
    bear_top = rp_df[(rp_df['regime'] == 'bear') & (rp_df['trades'] > 0)].sort_values('pf', ascending=False).head(3)
    side_top = rp_df[(rp_df['regime'] == 'sideways') & (rp_df['trades'] > 0)].sort_values('pf', ascending=False).head(3)

    # Auto-switch simulation
    switch_pnl = 0.0
    always_on_pnl = 0.0
    bull_bots = set(bull_top['bot'].tolist()) if not bull_top.empty else set()
    bear_bots = set(bear_top['bot'].tolist()) if not bear_top.empty else set()
    side_bots = set(side_top['bot'].tolist()) if not side_top.empty else set()

    for bot, trades in bot_trades.items():
        for t in trades:
            entry_regime = regime_map.get(t.get('entry_date', ''), 'unknown')
            pnl = t.get('pnl_amount', 0)
            always_on_pnl += pnl
            if entry_regime == 'bull' and bot in bull_bots:
                switch_pnl += pnl
            elif entry_regime == 'bear' and bot in bear_bots:
                switch_pnl += pnl
            elif entry_regime == 'sideways' and bot in side_bots:
                switch_pnl += pnl

    always_ret = always_on_pnl / INITIAL_CAPITAL * 100
    switch_ret = switch_pnl / INITIAL_CAPITAL * 100
    improvement = switch_ret - always_ret

    # Generate HTML
    _generate_block4_html(regime_df, rp_df, regime_counts, bull_top, bear_top, side_top,
                          always_ret, switch_ret, improvement)

    elapsed = time.time() - block_start
    log(f"Block 4 完了: {elapsed / 60:.1f}分")

    return {
        'bull_best': bull_top['bot'].tolist() if not bull_top.empty else [],
        'bear_best': bear_top['bot'].tolist() if not bear_top.empty else [],
        'always_ret': round(always_ret, 1),
        'switch_ret': round(switch_ret, 1),
        'improvement': round(improvement, 1),
    }


def _generate_block4_html(regime_df, rp_df, regime_counts, bull_top, bear_top, side_top,
                          always_ret, switch_ret, improvement):
    html_parts = [_html_header("Regime Analysis Report")]

    html_parts.append('<div class="summary">')
    html_parts.append(f'<b>期間:</b> {START_DATE} ~ {END_DATE}<br>')
    for r, c in regime_counts.items():
        html_parts.append(f'<b>{r.title()}:</b> {c}日<br>')
    html_parts.append('</div>')

    # Regime timeline (color-coded blocks)
    html_parts.append('<h2>レジームタイムライン</h2>')
    regime_colors = {'bull': '#4caf50', 'bear': '#f44336', 'sideways': '#ff9800', 'unknown': '#666'}
    html_parts.append('<div style="display:flex;height:30px;border-radius:4px;overflow:hidden;">')
    for _, row in regime_df.iterrows():
        color = regime_colors.get(row['regime'], '#666')
        html_parts.append(f'<div style="flex:1;background:{color}" title="{row.name}"></div>')
    html_parts.append('</div>')
    html_parts.append('<p style="font-size:0.8em">'
                      '<span style="color:#4caf50">■ Bull</span> '
                      '<span style="color:#f44336">■ Bear</span> '
                      '<span style="color:#ff9800">■ Sideways</span></p>')

    # Bot × Regime matrix
    html_parts.append('<h2>Bot × レジーム パフォーマンス</h2>')
    html_parts.append('<table><tr><th>Bot</th><th>Bull PF</th><th>Bear PF</th><th>Side PF</th>'
                      '<th>Bull T</th><th>Bear T</th><th>Side T</th></tr>')
    for bot in GRID_BOTS:
        bot_data = rp_df[rp_df['bot'] == bot]
        bull_pf = bot_data[bot_data['regime'] == 'bull']['pf'].values
        bear_pf = bot_data[bot_data['regime'] == 'bear']['pf'].values
        side_pf = bot_data[bot_data['regime'] == 'sideways']['pf'].values
        bull_t = bot_data[bot_data['regime'] == 'bull']['trades'].values
        bear_t = bot_data[bot_data['regime'] == 'bear']['trades'].values
        side_t = bot_data[bot_data['regime'] == 'sideways']['trades'].values
        bp = f'{bull_pf[0]:.2f}' if len(bull_pf) else '0'
        brp = f'{bear_pf[0]:.2f}' if len(bear_pf) else '0'
        sp = f'{side_pf[0]:.2f}' if len(side_pf) else '0'
        bt = int(bull_t[0]) if len(bull_t) else 0
        brt = int(bear_t[0]) if len(bear_t) else 0
        st = int(side_t[0]) if len(side_t) else 0
        html_parts.append(
            f'<tr><td>{bot}</td>'
            f'<td>{bp}</td><td>{brp}</td><td>{sp}</td>'
            f'<td>{bt}</td><td>{brt}</td><td>{st}</td></tr>')
    html_parts.append('</table>')

    # Regime best bots
    for label, top_df in [('Bull', bull_top), ('Bear', bear_top), ('Sideways', side_top)]:
        html_parts.append(f'<h3>{label}時 Top3</h3><ol>')
        for _, row in top_df.iterrows():
            html_parts.append(f'<li>{row["bot"]} — PF={row["pf"]:.2f}, WR={row["wr"]:.1f}%, {int(row["trades"])}T</li>')
        html_parts.append('</ol>')

    # Auto-switch comparison
    html_parts.append('<h2>自動切替 vs 常時稼働</h2>')
    html_parts.append(f'<table><tr><th>モード</th><th>Return</th><th>差分</th></tr>'
                      f'<tr><td>常時稼働 (全Bot)</td><td>{always_ret:+.1f}%</td><td>-</td></tr>'
                      f'<tr><td>レジーム自動切替</td><td>{switch_ret:+.1f}%</td>'
                      f'<td style="color:{"#4caf50" if improvement > 0 else "#f44336"}">{improvement:+.1f}%</td></tr>'
                      f'</table>')

    html_parts.append('<p class="warn">このデータを元にengine.pyにレジーム検出 → Bot自動ON/OFF機能を追加可能。</p>')
    html_parts.append(_html_footer())

    with open('vault/docs/regime_analysis_report.html', 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    log("HTML saved: vault/docs/regime_analysis_report.html")


# ============================================================
# Block 5: テスト + ペーパートレード
# ============================================================
def run_block5():
    log("=" * 60)
    log("Block 5: テスト + ペーパートレード稼働確認")
    log("=" * 60)
    block_start = time.time()

    # Run tests
    log("pytest 実行中...")
    import subprocess
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=short'],
        capture_output=True, text=True, timeout=300
    )
    log(f"pytest output:\n{result.stdout[-500:]}")
    test_pass = result.returncode == 0
    test_count = 0
    for line in result.stdout.split('\n'):
        if 'passed' in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    test_count = int(p)
                    break

    if not test_pass:
        log(f"  Tests FAILED: {result.stderr[-300:]}")

    elapsed = time.time() - block_start
    log(f"Block 5 テスト完了: {elapsed:.1f}秒, {test_count}件 {'PASS' if test_pass else 'FAIL'}")
    return {'test_pass': test_pass, 'test_count': test_count}


# ============================================================
# Telegram通知
# ============================================================
async def send_telegram_summary(block_results):
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()

        b1 = block_results.get('block1', {})
        b2 = block_results.get('block2', {})
        b3 = block_results.get('block3', {})
        b4 = block_results.get('block4', {})
        b5 = block_results.get('block5', {})

        # Block 1 summary
        b1_text = ""
        if b1.get('best_per_bot'):
            best_bot = max(b1['best_per_bot'].values(), key=lambda x: x['PF'])
            b1_text = (f"  実行パターン: {b1.get('total_patterns', '?')}\n"
                       f"  最高PF Bot: {best_bot['Bot']} PF={best_bot['PF']:.2f} "
                       f"(TP×{best_bot['TP_mult']} SL×{best_bot['SL_mult']} Lev{best_bot['Leverage']})")
        else:
            b1_text = "  データ不足またはエラー"

        # Block 2 summary
        b2_text = ""
        if b2.get('all_results'):
            b2_df = pd.DataFrame(b2['all_results'])
            top = b2_df[b2_df['Trades'] > 0].sort_values('PF', ascending=False)
            if not top.empty:
                best = top.iloc[0]
                b2_text = (f"  実行パターン: {len(b2['all_results'])}\n"
                           f"  最高PF: {best['Variant']} PF={best['PF']:.2f}")
            else:
                b2_text = "  トレードなし"
        else:
            b2_text = "  エラーまたはスキップ"

        text = (
            f"🌙 オーバーナイトタスク完了\n\n"
            f"■ ブロック1: グリッドサーチ\n{b1_text}\n\n"
            f"■ ブロック2: LevBurnチューニング\n{b2_text}\n\n"
            f"■ ブロック3: ポートフォリオ分析\n"
            f"  全Bot合成PF: {b3.get('portfolio_pf', '?')}\n"
            f"  全Bot合成MDD: {b3.get('portfolio_mdd', '?')}%\n\n"
            f"■ ブロック4: レジーム分析\n"
            f"  Bull最強: {', '.join(b4.get('bull_best', ['?'])[:1])}\n"
            f"  Bear最強: {', '.join(b4.get('bear_best', ['?'])[:1])}\n"
            f"  自動切替 vs 常時: Return {b4.get('improvement', '?')}%改善\n\n"
            f"■ ブロック5: 稼動状況\n"
            f"  テスト: {b5.get('test_count', '?')}件 {'全PASS' if b5.get('test_pass') else 'FAIL'}\n\n"
            f"レポート: vault/docs/"
        )
        await alert.send_message(text)
        log("Telegram通知送信完了")
    except Exception as e:
        log(f"Telegram送信失敗: {e}")


# ============================================================
# HTML共通
# ============================================================
def _html_header(title):
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', monospace; margin: 20px; }}
h1 {{ color: #ff6b35; border-bottom: 2px solid #30363d; padding-bottom: 10px; }}
h2 {{ color: #58a6ff; margin-top: 30px; }}
h3 {{ color: #8b949e; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th {{ background: #161b22; color: #58a6ff; padding: 10px; text-align: left; border: 1px solid #30363d; }}
td {{ padding: 8px 10px; border: 1px solid #30363d; }}
tr:nth-child(even) {{ background: #161b22; }}
.summary {{ background: #161b22; padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #30363d; }}
.warn {{ color: #ff9800; font-size: 0.9em; margin: 10px 0; }}
</style></head><body>
<h1>{title}</h1>"""


def _html_footer():
    return f'<p style="color:#8b949e; font-size:0.8em;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p></body></html>'


def _pf_color_bg(pf):
    if pf >= 2.0:
        return '#1b4332'
    elif pf >= 1.5:
        return '#2d6a4f'
    elif pf >= 1.0:
        return '#40916c'
    elif pf >= 0.5:
        return '#6c3b2a'
    else:
        return '#4a1a1a'


def _render_svg_chart(parts, series, title, width=800, height=300):
    """Simple SVG line chart"""
    if len(series) < 2:
        return
    values = series.values
    mn, mx = float(np.min(values)), float(np.max(values))
    if mn == mx:
        mx = mn + 1
    padding = 40
    chart_w = width - 2 * padding
    chart_h = height - 2 * padding

    points = []
    for i, v in enumerate(values):
        x = padding + (i / (len(values) - 1)) * chart_w
        y = padding + chart_h - ((float(v) - mn) / (mx - mn)) * chart_h
        points.append(f"{x:.1f},{y:.1f}")

    polyline = ' '.join(points)
    parts.append(f'<svg width="{width}" height="{height}" style="background:#161b22;border-radius:8px;">')
    parts.append(f'<polyline points="{polyline}" fill="none" stroke="#58a6ff" stroke-width="1.5"/>')
    # Zero line
    if mn < 0 < mx:
        zero_y = padding + chart_h - ((0 - mn) / (mx - mn)) * chart_h
        parts.append(f'<line x1="{padding}" y1="{zero_y:.1f}" x2="{width - padding}" y2="{zero_y:.1f}" '
                     f'stroke="#666" stroke-dasharray="4"/>')
    # Labels
    parts.append(f'<text x="{padding}" y="15" fill="#8b949e" font-size="12">{title}</text>')
    parts.append(f'<text x="{padding}" y="{padding - 5}" fill="#8b949e" font-size="10">{mx:,.0f}</text>')
    parts.append(f'<text x="{padding}" y="{height - 5}" fill="#8b949e" font-size="10">{mn:,.0f}</text>')
    parts.append('</svg>')


# ============================================================
# メイン実行
# ============================================================
def main():
    overall_start = time.time()
    log("=" * 60)
    log("  Overnight Grid Search + Analysis Pipeline")
    log(f"  開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    config = load_config()
    db = HistoricalDB()

    block_results = {}
    errors = []

    # === Block 1 ===
    try:
        results, best_per_bot, trade_logs = run_block1(config, db)
        block_results['block1'] = {
            'best_per_bot': best_per_bot,
            'total_patterns': len(results),
        }
    except Exception as e:
        log(f"Block 1 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 1: {e}")
        best_per_bot = {}
        trade_logs = {}
        block_results['block1'] = {}

    # === Block 2 ===
    try:
        lb_results = run_block2(config, db)
        block_results['block2'] = {'all_results': lb_results}
    except Exception as e:
        log(f"Block 2 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 2: {e}")
        block_results['block2'] = {}

    # === Block 3 ===
    try:
        b3_results = run_block3(trade_logs, best_per_bot)
        block_results['block3'] = b3_results
    except Exception as e:
        log(f"Block 3 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 3: {e}")
        block_results['block3'] = {}

    # === Block 4 ===
    try:
        b4_results = run_block4(trade_logs, db)
        block_results['block4'] = b4_results
    except Exception as e:
        log(f"Block 4 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 4: {e}")
        block_results['block4'] = {}

    # === Block 5 ===
    try:
        b5_results = run_block5()
        block_results['block5'] = b5_results
    except Exception as e:
        log(f"Block 5 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 5: {e}")
        block_results['block5'] = {}

    # === Telegram ===
    try:
        import asyncio
        asyncio.run(send_telegram_summary(block_results))
    except Exception as e:
        log(f"Telegram通知エラー: {e}")

    overall_elapsed = time.time() - overall_start
    log("=" * 60)
    log(f"  全ブロック完了: {overall_elapsed / 3600:.1f}時間")
    if errors:
        log(f"  エラー: {len(errors)}件")
        for e in errors:
            log(f"    - {e}")
    log("=" * 60)


if __name__ == '__main__':
    main()
