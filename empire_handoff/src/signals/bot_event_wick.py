"""Bot-Event-Wick: ヒゲキャッチ版イベント駆動 2派生
v1: 下ヒゲ/上ヒゲ比率でリバーサル強度を判定
v2: ヒゲ + 出来高爆発 の複合条件（ヒゲ2x + vol 5x）
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    variant = config.get('variant', 'wick_v1')
    btc_move_threshold = config.get('btc_move_threshold', 6.0)  # 元8%→6%に緩和
    vol_spike_min = config.get('vol_spike_min', 3.0)
    wick_min = config.get('wick_min', 2.0)  # ヒゲ/本体 最低比率

    if abs(btc_return) < btc_move_threshold:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        df = pd.read_sql_query(
            "SELECT open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) < 10:
            continue

        o = float(df.iloc[-1]['open'])
        h = float(df.iloc[-1]['high'])
        l = float(df.iloc[-1]['low'])
        c = float(df.iloc[-1]['close'])
        vol = float(df.iloc[-1]['volume'])

        body = abs(c - o)
        if body <= 0:
            body = 0.001 * c  # prevent div by zero

        # 下ヒゲ / 上ヒゲ計算
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)

        # BTC下落時: 下ヒゲの長さでリバーサル判定
        if btc_return < 0:
            wick_ratio = lower_wick / body
            side = 'long'
        else:
            wick_ratio = upper_wick / body
            side = 'short'

        if wick_ratio < wick_min:
            continue

        # 出来高チェック
        vol_avg = np.mean(df['volume'].values[-10:-1])
        if vol_avg <= 0:
            continue
        vol_ratio = vol / vol_avg
        if vol_ratio < vol_spike_min:
            continue

        # v2: ヒゲ + 出来高 両方が極端に高い場合のみ
        if variant == 'wick_v2':
            if wick_ratio < 3.0 or vol_ratio < 5.0:
                continue

        score = wick_ratio * vol_ratio
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol, 'price': c,
                'btc_return': float(btc_return),
                'wick_ratio': float(wick_ratio),
                'vol_ratio': float(vol_ratio),
                'side': side,
            }

    return best_target
