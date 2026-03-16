"""Bot-FearDip: 恐怖底値ロング（Fear<25, BTC急落, 聖域接近+出来高急増）"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 25)
    btc_drop_threshold = config.get('btc_drop_threshold', -3.0)
    sanctuary_dev_min = config.get('sanctuary_dev_min', -15.0)
    sanctuary_dev_max = config.get('sanctuary_dev_max', -5.0)
    vol_ratio_min = config.get('vol_ratio_min', 2.0)

    if fg >= fear_max:
        return None
    if btc_return > btc_drop_threshold:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        # 聖域価格取得
        sanc = conn.execute(
            "SELECT sanctuary_price FROM sanctuary WHERE symbol=?", (symbol,)
        ).fetchone()
        if not sanc or not sanc[0]:
            continue
        sanctuary_price = float(sanc[0])

        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 21:
            continue

        closes = sym_df['close'].values
        volumes = sym_df['volume'].values
        current = float(closes[-1])

        if sanctuary_price <= 0:
            continue

        # 聖域価格からの乖離
        sanc_dev = (current - sanctuary_price) / sanctuary_price * 100

        if not (sanctuary_dev_min <= sanc_dev <= sanctuary_dev_max):
            continue

        # 出来高スパイク
        vol_avg20 = np.mean(volumes[-21:-1])
        if vol_avg20 <= 0:
            continue
        vol_ratio = float(volumes[-1]) / vol_avg20

        if vol_ratio < vol_ratio_min:
            continue

        # スコア: 聖域への近さ × 出来高
        score = (1 / max(abs(sanc_dev), 1)) * vol_ratio
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'sanctuary_dev': float(sanc_dev),
                'vol_ratio': float(vol_ratio),
                'side': 'long',
            }

    return best_target
