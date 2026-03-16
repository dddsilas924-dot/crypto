"""Bot-MeanRevert-Strict: パラメータ大幅厳格化版 (2パターン)
variant A: Fear 55-75, MA20 ≥ 25%, RSI > 75, TP 5%, SL 2%
variant B: Fear 60-80, MA20 ≥ 30%, RSI > 80, TP 4%, SL 1.5% (超厳格)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

VARIANTS = {
    'strict_a': {'fear_min': 55, 'fear_max': 75, 'ma20_threshold': 25.0, 'rsi_min': 75, 'tp': 5.0, 'sl': 2.0},
    'strict_b': {'fear_min': 60, 'fear_max': 80, 'ma20_threshold': 30.0, 'rsi_min': 80, 'tp': 4.0, 'sl': 1.5},
}


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    v = config.get('variant', 'strict_a')
    params = VARIANTS.get(v, VARIANTS['strict_a'])

    if not (params['fear_min'] <= fg <= params['fear_max']):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) < 21:
            continue
        closes = df['close'].values
        volumes = df['volume'].values
        current = float(closes[-1])
        ma20 = float(np.mean(closes[-20:]))
        if ma20 <= 0:
            continue
        deviation = (current - ma20) / ma20 * 100
        if deviation < params['ma20_threshold']:
            continue

        # RSIチェック
        if len(closes) < 15:
            continue
        diffs = np.diff(closes[-15:])
        gains = np.where(diffs > 0, diffs, 0)
        losses_arr = np.where(diffs < 0, -diffs, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses_arr)
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
        if rsi < params['rsi_min']:
            continue

        vol_avg = np.mean(volumes[-20:])
        vol_ratio = float(volumes[-1]) / vol_avg if vol_avg > 0 else 1.0
        if vol_ratio < 1.5:
            continue

        score = deviation * vol_ratio * (rsi / 70)
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol, 'price': current,
                'ma20_dev': float(deviation), 'rsi': float(rsi),
                'side': 'short',
            }

    return best_target
