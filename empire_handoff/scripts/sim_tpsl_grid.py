"""TP/SL深化シミュレーション — 2日間ペーパーデータ × 5段階 × 4BOT × (通常+SHORT_ONLY)"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = 'data/empire_monitor.db'
COST_PCT = 0.22  # round-trip cost

# 4 BOT
BOTS = [
    'levburn_sec_scalp_micro',
    'levburn_sec_aggressive',
    'levburn_sec_aggressive_lev1',
    'levburn_sec_aggressive_lev3',
]

# 5段階のTP/SL倍率 (元のTP/SLに対する倍率)
TPSL_LEVELS = [
    {'label': '0.5x (浅い)', 'tp_mult': 0.5, 'sl_mult': 0.5},
    {'label': '1.0x (現状)', 'tp_mult': 1.0, 'sl_mult': 1.0},
    {'label': '1.5x',        'tp_mult': 1.5, 'sl_mult': 1.5},
    {'label': '2.0x (深い)', 'tp_mult': 2.0, 'sl_mult': 2.0},
    {'label': '3.0x (最深)', 'tp_mult': 3.0, 'sl_mult': 3.0},
]


def get_signals(conn, bot_type):
    """指定BOTのペーパーシグナルを取得（元の結果も含む）"""
    rows = conn.execute('''
        SELECT id, symbol, side, entry_price, leverage,
               take_profit_pct, stop_loss_pct, signal_time,
               exit_price, exit_reason, realized_pnl_pct
        FROM paper_signals
        WHERE status='closed' AND bot_type=?
        ORDER BY signal_time
    ''', (bot_type,)).fetchall()
    return [dict(zip(['id','symbol','side','entry_price','leverage','tp_pct','sl_pct',
                      'signal_time','exit_price','exit_reason','realized_pnl'], r)) for r in rows]


def get_price_after_entry(conn, symbol, entry_time_str, hours=48):
    """エントリー後のOHLCVデータ（1h足）を取得"""
    # Parse entry time
    entry_dt = datetime.fromisoformat(entry_time_str)
    start_ts = int(entry_dt.timestamp() * 1000)
    end_ts = start_ts + hours * 3600 * 1000

    # Try different symbol formats
    sym_variants = [symbol]
    if '_' in symbol:
        base = symbol.replace('_USDT', '')
        sym_variants.append(f'{base}/USDT:USDT')

    for sym in sym_variants:
        df = conn.execute('''
            SELECT timestamp, high, low, close FROM ohlcv
            WHERE symbol=? AND timeframe='1h'
            AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
        ''', (sym, start_ts, end_ts)).fetchall()
        if df:
            return df

    return []


def simulate_trade(signal, tp_mult, sl_mult, price_data, short_only=False):
    """1トレードをシミュレート"""
    if short_only and signal['side'] == 'long':
        return None  # LONGスキップ

    entry = signal['entry_price']
    lev = signal['leverage']
    base_tp = signal['tp_pct']
    base_sl = signal['sl_pct']

    tp_pct = base_tp * tp_mult
    sl_pct = base_sl * sl_mult

    is_long = signal['side'] == 'long'

    if is_long:
        tp_price = entry * (1 + tp_pct / 100)
        sl_price = entry * (1 - sl_pct / 100)
    else:
        tp_price = entry * (1 - tp_pct / 100)
        sl_price = entry * (1 + sl_pct / 100)

    # Walk through price data
    for row in price_data:
        high = row[1]
        low = row[2]

        if is_long:
            if low <= sl_price:
                raw_pnl = -sl_pct
                return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'SL', 'win': False}
            if high >= tp_price:
                raw_pnl = tp_pct
                return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'TP', 'win': True}
        else:
            if high >= sl_price:
                raw_pnl = -sl_pct
                return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'SL', 'win': False}
            if low <= tp_price:
                raw_pnl = tp_pct
                return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'TP', 'win': True}

    # Timeout - use last close
    if price_data:
        last_close = price_data[-1][3]
        if is_long:
            raw_pnl = (last_close - entry) / entry * 100
        else:
            raw_pnl = (entry - last_close) / entry * 100
        return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'TIMEOUT', 'win': raw_pnl > COST_PCT}

    # No price data available — fallback to original signal result
    # If wider TP/SL: original TP still hits (same or better), original SL might not hit
    orig_reason = signal.get('exit_reason', '')
    orig_pnl = signal.get('realized_pnl', 0) or 0
    if tp_mult == 1.0 and sl_mult == 1.0:
        # Exact original
        return {'pnl': orig_pnl, 'reason': orig_reason, 'win': orig_pnl > 0}
    elif orig_reason == 'TP':
        # Original hit TP. Wider TP might not hit → assume timeout at original TP level
        if tp_mult > 1.0:
            # Conservative: assume only reaches original TP price, not wider
            raw_pnl = signal['tp_pct']  # original TP distance
            return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'TP_PARTIAL', 'win': True}
        else:
            # Tighter TP: would hit even sooner
            raw_pnl = signal['tp_pct'] * tp_mult
            return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'TP', 'win': True}
    elif orig_reason == 'SL':
        # Original hit SL. Wider SL might survive → check
        orig_sl_dist = signal['sl_pct']
        new_sl_dist = orig_sl_dist * sl_mult
        if sl_mult > 1.0:
            # Wider SL: original price movement was within original SL but might recover
            # Conservative: assume still hits SL at wider level (worst case)
            raw_pnl = -new_sl_dist
            return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'SL', 'win': False}
        else:
            # Tighter SL: hits sooner
            raw_pnl = -new_sl_dist
            return {'pnl': (raw_pnl - COST_PCT) * lev, 'reason': 'SL', 'win': False}
    else:
        return {'pnl': orig_pnl, 'reason': 'FALLBACK', 'win': orig_pnl > 0}


def run_simulation():
    conn = sqlite3.connect(DB_PATH)
    results = {}  # {(bot, level_label, short_only): stats}

    for bot in BOTS:
        signals = get_signals(conn, bot)
        if not signals:
            continue

        # Cache price data per symbol+time
        price_cache = {}

        for level in TPSL_LEVELS:
            for short_only in [False, True]:
                mode = 'short_only' if short_only else 'normal'
                key = (bot, level['label'], mode)

                wins = 0
                losses = 0
                total_pnl = 0
                trade_count = 0
                pnl_list = []

                for sig in signals:
                    cache_key = (sig['symbol'], sig['signal_time'])
                    if cache_key not in price_cache:
                        price_cache[cache_key] = get_price_after_entry(
                            conn, sig['symbol'], sig['signal_time'])

                    price_data = price_cache[cache_key]
                    result = simulate_trade(sig, level['tp_mult'], level['sl_mult'],
                                           price_data, short_only)
                    if result is None:
                        continue

                    trade_count += 1
                    total_pnl += result['pnl']
                    pnl_list.append(result['pnl'])
                    if result['win']:
                        wins += 1
                    else:
                        losses += 1

                wr = round(wins / trade_count * 100, 1) if trade_count > 0 else 0
                avg_pnl = round(total_pnl / trade_count, 2) if trade_count > 0 else 0

                # Profit factor
                gross_profit = sum(p for p in pnl_list if p > 0)
                gross_loss = abs(sum(p for p in pnl_list if p < 0))
                pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999

                results[key] = {
                    'bot': bot,
                    'level': level['label'],
                    'mode': mode,
                    'tp_mult': level['tp_mult'],
                    'sl_mult': level['sl_mult'],
                    'trades': trade_count,
                    'wins': wins,
                    'losses': losses,
                    'wr': wr,
                    'pf': pf,
                    'total_pnl': round(total_pnl, 2),
                    'avg_pnl': avg_pnl,
                }

    conn.close()
    return results


def main():
    print("Running TP/SL grid simulation...")
    results = run_simulation()

    # Save as JSON
    out = Path('vault/backtest_results/variants')
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'tpsl_grid_results.json', 'w') as f:
        json.dump({str(k): v for k, v in results.items()}, f, indent=2)

    # Print summary
    print(f"\nTotal configs: {len(results)}")
    print(f"\n{'Bot':<35} {'Level':<16} {'Mode':<12} {'Tr':>4} {'WR%':>6} {'PF':>6} {'TotalPnL':>10} {'AvgPnL':>8}")
    print('=' * 100)
    for key in sorted(results.keys()):
        r = results[key]
        print(f"{r['bot']:<35} {r['level']:<16} {r['mode']:<12} {r['trades']:>4} {r['wr']:>6.1f} {r['pf']:>6.2f} {r['total_pnl']:>10.2f} {r['avg_pnl']:>8.2f}")

    return results


if __name__ == '__main__':
    main()
