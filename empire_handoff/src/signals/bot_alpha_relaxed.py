"""Bot-Alpha-Relaxed: Alpha条件緩和10派生

厳選シグナルの維持 = 勝ったときに大きく取れるTP/SLバランス
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

# 10パターンの条件グリッド
ALPHA_VARIANTS = {
    'alpha_r1':  {'fear_max': 15, 'btc_ret': -0.8, 'btc_d': -0.4, 'corr_max': 0.5, 'alpha_min': 2.5, 'tp': 10, 'sl': 3},
    'alpha_r2':  {'fear_max': 20, 'btc_ret': -0.5, 'btc_d': -0.3, 'corr_max': 0.5, 'alpha_min': 2.0, 'tp': 10, 'sl': 3},
    'alpha_r3':  {'fear_max': 20, 'btc_ret': -1.0, 'btc_d': -0.3, 'corr_max': 0.6, 'alpha_min': 2.0, 'tp': 12, 'sl': 4},
    'alpha_r4':  {'fear_max': 25, 'btc_ret': -0.5, 'btc_d': -0.2, 'corr_max': 0.5, 'alpha_min': 1.5, 'tp': 10, 'sl': 3},
    'alpha_r5':  {'fear_max': 25, 'btc_ret': -0.3, 'btc_d':  0.0, 'corr_max': 0.4, 'alpha_min': 2.0, 'tp': 12, 'sl': 4},
    'alpha_r6':  {'fear_max': 15, 'btc_ret': -1.0, 'btc_d': -0.5, 'corr_max': 0.4, 'alpha_min': 2.0, 'tp': 15, 'sl': 5},
    'alpha_r7':  {'fear_max': 30, 'btc_ret': -0.5, 'btc_d': -0.2, 'corr_max': 0.5, 'alpha_min': 1.5, 'tp': 8,  'sl': 2},
    'alpha_r8':  {'fear_max': 20, 'btc_ret': -0.8, 'btc_d': -0.3, 'corr_max': 0.6, 'alpha_min': 1.0, 'tp': 15, 'sl': 5},
    'alpha_r9':  {'fear_max': 15, 'btc_ret': -0.5, 'btc_d': -0.5, 'corr_max': 0.3, 'alpha_min': 3.0, 'tp': 20, 'sl': 5},
    'alpha_r10': {'fear_max': 25, 'btc_ret': -1.0, 'btc_d':  0.0, 'corr_max': 0.6, 'alpha_min': 1.0, 'tp': 10, 'sl': 3},
}


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    variant = config.get('variant', 'alpha_r1')
    v = ALPHA_VARIANTS.get(variant, ALPHA_VARIANTS['alpha_r1'])

    if fg > v['fear_max']:
        return None
    if btc_return > v['btc_ret']:
        return None

    # BTC Dominance変化は近似: btcリターンの方向で代用
    btc_d_change = config.get('_btc_d_change', btc_return * 0.3)
    if btc_d_change > v['btc_d']:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(14)['close'].tolist()
    if len(btc_closes) < 14:
        return None

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        df = pd.read_sql_query(
            "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) < 14:
            continue
        closes = df['close'].values

        sym_ret = np.diff(closes[-14:]) / closes[-14:-1]
        btc_ret_arr = np.diff(btc_closes[-14:]) / np.array(btc_closes[-14:-1], dtype=float)
        min_len = min(len(sym_ret), len(btc_ret_arr))
        if min_len < 10:
            continue

        corr = np.corrcoef(sym_ret[-min_len:], btc_ret_arr[-min_len:])[0, 1]
        if np.isnan(corr) or corr > v['corr_max']:
            continue

        sym_daily = (float(closes[-1]) - float(closes[-2])) / float(closes[-2]) * 100
        alpha = sym_daily - btc_return
        if alpha < v['alpha_min']:
            continue

        score = (1 - corr) * 50 + min(alpha * 5, 50)
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol, 'price': float(closes[-1]),
                'alpha': float(alpha), 'btc_corr': float(corr),
                'side': 'long',
            }

    return best_target
