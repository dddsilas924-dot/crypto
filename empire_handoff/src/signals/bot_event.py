"""Bot-Event: イベントドリブン（BTC日次±8%大変動時の逆張り）

注意: 本来4h足ベースだが、1hヒストリカルデータ不足のため日足で代用。
資金の5%のみ使用、高レバレッジ。年数回のブラックスワン専用。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    btc_move_threshold = config.get('btc_move_threshold', 8.0)
    vol_spike_min = config.get('vol_spike_min', 3.0)

    # BTC日次変動が±8%以上
    if abs(btc_return) < btc_move_threshold:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_vol_ratio = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 10:
            continue

        volumes = sym_df['volume'].values
        vol_avg = np.mean(volumes[-10:-1])
        if vol_avg <= 0:
            continue
        vol_ratio = float(volumes[-1]) / vol_avg

        if vol_ratio < vol_spike_min:
            continue

        if vol_ratio > best_vol_ratio:
            best_vol_ratio = vol_ratio
            current = float(sym_df['close'].values[-1])
            # BTC下落→ロング（リバウンド）、BTC上昇→ショート（過熱反転）
            side = 'long' if btc_return < 0 else 'short'
            best_target = {
                'symbol': symbol,
                'price': current,
                'btc_return': float(btc_return),
                'vol_ratio': float(vol_ratio),
                'side': side,
            }

    return best_target
