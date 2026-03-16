"""Bot-MeanRevert-Hybrid: ロング・ショート両面版
SHORT: MA20上方乖離 ≥ 15% (通常MeanRevert)
LONG:  MA20下方乖離 ≤ -15% かつ BTC 24h > +1%
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 50)
    fear_max = config.get('fear_max', 80)
    ma20_dev_min = config.get('ma20_dev_min', 15.0)
    btc_long_threshold = config.get('btc_long_threshold', 1.0)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_short = None
    best_short_score = 0
    best_long = None
    best_long_score = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 21:
            continue

        closes = sym_df['close'].values
        current = float(closes[-1])
        ma20 = np.mean(closes[-20:])

        if ma20 <= 0:
            continue

        ma20_dev = (current - ma20) / ma20 * 100

        # 出来高ボーナス
        volumes = sym_df['volume'].values
        vol_avg = np.mean(volumes[-20:])
        vol_recent = np.mean(volumes[-2:])
        vol_bonus = vol_recent / vol_avg if vol_avg > 0 and vol_recent / vol_avg > 1.2 else 1.0

        # SHORT: 上方乖離
        if ma20_dev >= ma20_dev_min:
            score = ma20_dev * vol_bonus
            if score > best_short_score:
                best_short_score = score
                best_short = {
                    'symbol': symbol,
                    'price': current,
                    'ma20_dev': float(ma20_dev),
                    'side': 'short',
                }

        # LONG: 下方乖離 + BTC上昇条件
        if ma20_dev <= -ma20_dev_min and btc_return > btc_long_threshold:
            score = abs(ma20_dev) * vol_bonus
            if score > best_long_score:
                best_long_score = score
                best_long = {
                    'symbol': symbol,
                    'price': current,
                    'ma20_dev': float(ma20_dev),
                    'side': 'long',
                }

    # ショートとロング、スコアが高い方を返す
    if best_short and best_long:
        return best_short if best_short_score >= best_long_score else best_long
    return best_short or best_long
