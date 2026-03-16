"""Bot-MeanRevert-Wide: パラメータ大幅緩和版 (2パターン)
variant A: Fear 35-85, MA20 ≥ 10%, TP 9%, SL 4%
variant B: Fear 40-90, MA20 ≥ 8%, TP 12%, SL 5% (超ワイド)
config.variant = 'wide_a' or 'wide_b'
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

VARIANTS = {
    'wide_a': {'fear_min': 35, 'fear_max': 85, 'ma20_threshold': 10.0, 'tp': 9.0, 'sl': 4.0},
    'wide_b': {'fear_min': 40, 'fear_max': 90, 'ma20_threshold': 8.0, 'tp': 12.0, 'sl': 5.0},
}


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    v = config.get('variant', 'wide_a')
    params = VARIANTS.get(v, VARIANTS['wide_a'])

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

        vol_avg = np.mean(volumes[-20:])
        vol_bonus = min(float(volumes[-1]) / vol_avg, 3.0) if vol_avg > 0 else 1.0

        score = deviation * vol_bonus
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol, 'price': current,
                'ma20_dev': float(deviation),
                'side': 'short',
            }

    return best_target
