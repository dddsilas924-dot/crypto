"""Bot-Sniper: 精密狙撃（Fear<30, BTC急落, 出来高爆発, 低BTC相関アルト）

注意: 本来1h足ベースだが、1hヒストリカルデータ不足のため日足で代用。
資金の5%のみ使用、高レバレッジ。条件が厳しく月0-2回。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 30)
    btc_drop_threshold = config.get('btc_drop_threshold', -3.0)
    vol_spike_min = config.get('vol_spike_min', 5.0)
    corr_max = config.get('corr_max', 0.3)

    if fg >= fear_max:
        return None
    if btc_return > btc_drop_threshold:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(21)['close'].tolist()
    if len(btc_closes) < 14:
        return None

    candidates = []

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 21:
            continue

        closes = sym_df['close'].values
        volumes = sym_df['volume'].values

        # 出来高スパイク（24h平均の5倍以上）
        vol_avg = np.mean(volumes[-21:-1])
        if vol_avg <= 0:
            continue
        vol_ratio = float(volumes[-1]) / vol_avg
        if vol_ratio < vol_spike_min:
            continue

        # BTC相関チェック
        sym_ret = np.diff(closes[-14:]) / closes[-14:-1]
        btc_ret = np.diff(btc_closes[-14:]) / np.array(btc_closes[-14:-1], dtype=float)
        min_len = min(len(sym_ret), len(btc_ret))
        if min_len < 10:
            continue
        corr = np.corrcoef(sym_ret[-min_len:], btc_ret[-min_len:])[0, 1]
        if np.isnan(corr):
            continue
        if corr > corr_max:
            continue

        candidates.append({
            'symbol': symbol,
            'price': float(closes[-1]),
            'vol_ratio': float(vol_ratio),
            'btc_corr': float(corr),
            'side': 'long',
        })

    if not candidates:
        return None

    # 上位3候補から最高スコアを選択
    candidates.sort(key=lambda x: x['vol_ratio'] * (1 - x['btc_corr']), reverse=True)
    return candidates[0]
