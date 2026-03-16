"""Bot-ShortSqueeze: ショートカバー検知ロング（Fear<25, ショート過剰プロキシ）

注意: FR/OIのヒストリカルデータがDBにないため、価格ベースのプロキシを使用。
- FR < -0.03% プロキシ: 3日連続下落 + 出来高増加（ショート圧力の兆候）
- OI -10% プロキシ: 大きな下ヒゲ（清算による急反発）
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 25)
    consecutive_down_days = config.get('consecutive_down_days', 3)
    wick_ratio_min = config.get('wick_ratio_min', 2.0)

    if fg >= fear_max:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 10 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 5:
            continue

        closes = sym_df['close'].values
        opens = sym_df['open'].values
        highs = sym_df['high'].values
        lows = sym_df['low'].values
        volumes = sym_df['volume'].values

        # プロキシ1: N日連続下落（ショート圧力）
        down_count = 0
        for i in range(-consecutive_down_days, 0):
            if float(closes[i]) < float(opens[i]):
                down_count += 1
        if down_count < consecutive_down_days:
            continue

        # プロキシ2: 直近足の下ヒゲが実体の wick_ratio_min 倍以上（清算反発シグナル）
        body = abs(float(closes[-1]) - float(opens[-1]))
        lower_wick = min(float(closes[-1]), float(opens[-1])) - float(lows[-1])
        if body <= 0:
            continue
        wick_ratio = lower_wick / body
        if wick_ratio < wick_ratio_min:
            continue

        # 出来高増加確認
        vol_avg = np.mean(volumes[-5:-1])
        if vol_avg <= 0:
            continue
        vol_ratio = float(volumes[-1]) / vol_avg
        if vol_ratio < 1.5:
            continue

        score = wick_ratio * vol_ratio
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': float(closes[-1]),
                'wick_ratio': float(wick_ratio),
                'vol_ratio': float(vol_ratio),
                'down_days': down_count,
                'side': 'long',
            }

    return best_target
