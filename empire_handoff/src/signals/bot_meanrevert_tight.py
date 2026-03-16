"""Bot-MeanRevert-Tight: 厳選エントリー版
MA20乖離 ≥ 22.5% (1.5倍), RSI > 70, vol_ratio ≥ 1.5 必須, SL 2.1% (70%)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    """RSI計算（Wilder方式）"""
    if len(closes) < period + 1:
        return 50.0  # デフォルト中立
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 50)
    fear_max = config.get('fear_max', 80)
    ma20_dev_min = config.get('ma20_dev_min', 22.5)
    rsi_threshold = config.get('rsi_threshold', 70)
    vol_ratio_min = config.get('vol_ratio_min', 1.5)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

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

        # RSIチェック
        rsi = _calc_rsi(closes)
        if rsi <= rsi_threshold:
            continue

        # 出来高チェック（必須条件）
        volumes = sym_df['volume'].values
        vol_avg = np.mean(volumes[-20:])
        if vol_avg <= 0:
            continue
        vol_recent = np.mean(volumes[-2:])
        vol_ratio = vol_recent / vol_avg
        if vol_ratio < vol_ratio_min:
            continue

        score = ma20_dev * (rsi / 70) * vol_ratio
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'ma20_dev': float(ma20_dev),
                'rsi': float(rsi),
                'vol_ratio': float(vol_ratio),
                'side': 'short',
            }

    return best_target
