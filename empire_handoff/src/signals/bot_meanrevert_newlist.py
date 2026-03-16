"""Bot-MeanRevert-NewList: 新規上場ハイプ崩壊ショート
is_new_listing=True, 安値+50%以上, RSI>75, 出来高減少中, MA20乖離≥15%
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    """RSI計算（Wilder方式）"""
    if len(closes) < period + 1:
        return 50.0
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
    ma20_dev_min = config.get('ma20_dev_min', 15.0)
    rsi_threshold = config.get('rsi_threshold', 75)
    price_from_low_pct = config.get('price_from_low_pct', 50.0)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        # 新規上場チェック
        nl_row = pd.read_sql_query(
            "SELECT is_new_listing FROM sanctuary WHERE symbol=? LIMIT 1",
            conn, params=(symbol,)
        )
        if len(nl_row) == 0 or nl_row.iloc[0]['is_new_listing'] != 1:
            continue

        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 15:  # 新規上場は21日分ないことも
            continue

        closes = sym_df['close'].values
        current = float(closes[-1])
        low_price = float(np.min(closes))

        if low_price <= 0:
            continue

        # 安値からの上昇率チェック
        price_from_low = (current - low_price) / low_price * 100
        if price_from_low < price_from_low_pct:
            continue

        # MA20乖離チェック（データ不足時はMA available分で計算）
        ma_period = min(20, len(closes))
        ma = np.mean(closes[-ma_period:])
        if ma <= 0:
            continue
        ma20_dev = (current - ma) / ma * 100
        if ma20_dev < ma20_dev_min:
            continue

        # RSIチェック
        rsi = _calc_rsi(closes)
        if rsi <= rsi_threshold:
            continue

        # 出来高減少チェック（直近2日 < 20日平均 = 買い圧枯渇）
        volumes = sym_df['volume'].values
        vol_avg = np.mean(volumes[:-2]) if len(volumes) > 2 else np.mean(volumes)
        if vol_avg <= 0:
            continue
        vol_recent = np.mean(volumes[-2:])
        vol_ratio = vol_recent / vol_avg
        if vol_ratio >= 1.0:  # 出来高が減少していない
            continue

        score = ma20_dev * (rsi / 75) * (1 / max(vol_ratio, 0.1))
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'ma20_dev': float(ma20_dev),
                'rsi': float(rsi),
                'price_from_low': float(price_from_low),
                'vol_ratio': float(vol_ratio),
                'side': 'short',
            }

    return best_target
