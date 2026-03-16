"""Bot-ICO-MeanRevert: 新規上場銘柄のハイプ崩壊ショート

対象: 上場後7-90日
発動: Fear 40-80
条件: 最安値から+50%以上, RSI>70, 出来高減少, 直近3日中2日以上が陰線
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
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


def _get_listing_date(conn, symbol: str) -> Optional[str]:
    """最古の日足データ日を上場日として推定"""
    row = conn.execute(
        "SELECT MIN(timestamp) FROM ohlcv WHERE symbol=? AND timeframe='1d'",
        (symbol,)
    ).fetchone()
    if row and row[0]:
        return datetime.fromtimestamp(row[0] / 1000).strftime('%Y-%m-%d')
    return None


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 40)
    fear_max = config.get('fear_max', 80)
    rsi_threshold = config.get('rsi_threshold', 70)
    price_from_low_pct = config.get('price_from_low_pct', 50.0)
    age_min = config.get('age_min', 7)
    age_max = config.get('age_max', 90)
    min_volume_usd = config.get('min_volume_usd', 0)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 95 * 86400000  # 最大90日+バッファ

    best_target = None
    best_score = 0

    for symbol in symbols[:200]:
        # 上場日チェック
        listing_date = _get_listing_date(conn, symbol)
        if not listing_date:
            continue
        ld = datetime.strptime(listing_date, '%Y-%m-%d')
        age = (dt - ld).days
        if age < age_min or age > age_max:
            continue

        sym_df = pd.read_sql_query(
            "SELECT open, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 10:
            continue

        closes = sym_df['close'].values
        opens = sym_df['open'].values
        volumes = sym_df['volume'].values
        current = float(closes[-1])
        low_price = float(np.min(closes))

        if low_price <= 0:
            continue

        # 安値からの上昇率
        price_from_low = (current - low_price) / low_price * 100
        if price_from_low < price_from_low_pct:
            continue

        # RSI
        rsi = _calc_rsi(closes)
        if rsi <= rsi_threshold:
            continue

        # 出来高減少チェック（直近2日 < 3日前の出来高）
        if len(volumes) < 5:
            continue
        vol_recent = np.mean(volumes[-2:])
        vol_prev = np.mean(volumes[-5:-2])
        if vol_prev <= 0 or vol_recent >= vol_prev:
            continue  # 出来高が減少していない

        # 直近3日中2日以上が陰線
        bearish_count = 0
        for i in range(-3, 0):
            if len(opens) + i >= 0 and closes[i] < opens[i]:
                bearish_count += 1
        if bearish_count < 2:
            continue

        score = price_from_low * (rsi / 70) * (vol_prev / max(vol_recent, 0.001))
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'rsi': float(rsi),
                'price_from_low': float(price_from_low),
                'age': age,
                'side': 'short',
            }

    return best_target
