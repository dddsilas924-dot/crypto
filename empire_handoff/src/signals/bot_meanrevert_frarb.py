"""Bot-MeanRevert-FRArb: 平均回帰 + HF-FRArb融合
MA20乖離 + FR偏りプロキシ(8hモメンタム+RSI) の合算スコア
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    fear_min = config.get('fear_min', 45)
    fear_max = config.get('fear_max', 80)
    ma20_threshold = config.get('ma20_threshold', 12.0)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 30 * 86400000

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

        # --- MeanRevert条件 ---
        if abs(deviation) < ma20_threshold:
            continue

        # --- FRArb条件 (proxy): 8日モメンタム + RSI ---
        if len(closes) < 15:
            continue
        mom_8d = (float(closes[-1]) - float(closes[-9])) / float(closes[-9]) * 100 if float(closes[-9]) > 0 else 0

        diffs = np.diff(closes[-15:])
        gains = np.where(diffs > 0, diffs, 0)
        losses_arr = np.where(diffs < 0, -diffs, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses_arr) if len(losses_arr) > 0 else 0
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

        # 合算スコア: MA乖離 + FRプロキシ一致でブースト
        fr_boost = 0
        side = None

        if deviation >= ma20_threshold:
            side = 'short'
            # overbought + FR long crowded
            if mom_8d >= 3 and rsi > 70:
                fr_boost = 20  # FRArb一致
        elif deviation <= -ma20_threshold:
            side = 'long'
            if mom_8d <= -3 and rsi < 30:
                fr_boost = 20

        if side is None:
            continue

        vol_avg = np.mean(volumes[-20:])
        vol_ratio = float(volumes[-1]) / vol_avg if vol_avg > 0 else 1.0

        score = abs(deviation) * vol_ratio + fr_boost
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol, 'price': current,
                'ma20_dev': float(deviation), 'rsi': float(rsi),
                'mom_8d': float(mom_8d), 'fr_boost': fr_boost,
                'side': side,
            }

    return best_target
