"""Bot-MeanRevert-Tuned: パラメータ微調整版
Fear 45-75, MA20乖離 ≥ 12% (80%), TP 7.2% (120%), SL 2.7% (90%)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 45)
    fear_max = config.get('fear_max', 75)
    ma20_dev_min = config.get('ma20_dev_min', 12.0)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_dev = 0

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

        if ma20_dev < ma20_dev_min:
            continue

        # 出来高ボーナス
        volumes = sym_df['volume'].values
        vol_avg = np.mean(volumes[-20:])
        vol_recent = np.mean(volumes[-2:])
        vol_bonus = vol_recent / vol_avg if vol_avg > 0 and vol_recent / vol_avg > 1.2 else 1.0

        score = ma20_dev * vol_bonus
        if score > best_dev:
            best_dev = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'ma20_dev': float(ma20_dev),
                'side': 'short',
            }

    return best_target
