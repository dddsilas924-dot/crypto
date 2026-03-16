"""Bot-FearFlat: 恐怖×低ボラ底固め（Fear<30 + ATR低 = パニック終了 → ロング）

ナレッジ: L06(ボラ安定性) + L11(センチメント逆張り)
逆説: Fear低=暴落中と思いきや、ATR低=もう動いていない。恐怖の最終段階で売り切った後の静寂。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 30)
    atr_ratio_max = config.get('atr_ratio_max', 3.0)  # ATR14/close < 3%
    range_max = config.get('range_max', 4.0)  # 5日平均日中レンジ < 4%
    btc_floor = config.get('btc_floor', -1.0)  # BTC日次 > -1%（暴落終了確認）

    if fg >= fear_max:
        return None
    if btc_return < btc_floor:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 20:
            continue

        closes = sym_df['close'].values
        highs = sym_df['high'].values
        lows = sym_df['low'].values
        current = float(closes[-1])

        if current <= 0:
            continue

        # ATR14計算
        tr_values = []
        for i in range(-14, 0):
            h = float(highs[i])
            l = float(lows[i])
            prev_c = float(closes[i - 1])
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_values.append(tr)
        atr14 = np.mean(tr_values)
        atr_ratio = atr14 / current * 100

        if atr_ratio > atr_ratio_max:
            continue

        # 5日平均日中レンジ
        ranges_5d = []
        for i in range(-5, 0):
            day_range = (float(highs[i]) - float(lows[i])) / float(closes[i]) * 100
            ranges_5d.append(day_range)
        avg_range = np.mean(ranges_5d)

        if avg_range > range_max:
            continue

        # MA20からの下方乖離（底からの回復余地）
        ma20 = np.mean(closes[-20:])
        if ma20 <= 0:
            continue
        ma20_dev = (current - ma20) / ma20 * 100

        # 下方乖離が大きいほど回復余地あり
        if ma20_dev > 0:
            continue  # MA上にいる場合は底固めではない

        # スコア: 低ボラ × 下方乖離の大きさ
        score = (1 / max(atr_ratio, 0.1)) * abs(ma20_dev) * (1 / max(avg_range, 0.1))
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'atr_ratio': float(atr_ratio),
                'avg_range': float(avg_range),
                'ma20_dev': float(ma20_dev),
                'side': 'long',
            }

    return best_target
