"""Bot-ICO-Rebound: 新規上場銘柄の暴落後リバウンドロング

対象: 上場後14-90日
発動: Fear < 40
条件: 最高値から-50%以上下落, RSI<30, 出来高+50%増加
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
    row = conn.execute(
        "SELECT MIN(timestamp) FROM ohlcv WHERE symbol=? AND timeframe='1d'",
        (symbol,)
    ).fetchone()
    if row and row[0]:
        return datetime.fromtimestamp(row[0] / 1000).strftime('%Y-%m-%d')
    return None


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 40)
    rsi_threshold = config.get('rsi_threshold', 30)
    drop_from_high_pct = config.get('drop_from_high_pct', -50.0)
    vol_surge_min = config.get('vol_surge_min', 1.5)
    age_min = config.get('age_min', 14)
    age_max = config.get('age_max', 90)
    preferred_sectors = config.get('preferred_sectors', ['AI', 'Meme', 'Gaming', 'DePIN', 'RWA'])

    if fg >= fear_max:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 95 * 86400000

    # セクター情報取得
    sector_map = {}
    try:
        rows = conn.execute("SELECT symbol, primary_sector FROM sector").fetchall()
        sector_map = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    best_target = None
    best_score = 0

    for symbol in symbols[:200]:
        listing_date = _get_listing_date(conn, symbol)
        if not listing_date:
            continue
        ld = datetime.strptime(listing_date, '%Y-%m-%d')
        age = (dt - ld).days
        if age < age_min or age > age_max:
            continue

        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 10:
            continue

        closes = sym_df['close'].values
        volumes = sym_df['volume'].values
        current = float(closes[-1])
        high_price = float(np.max(closes))

        if high_price <= 0:
            continue

        # 最高値からの下落率
        drop_from_high = (current - high_price) / high_price * 100
        if drop_from_high > drop_from_high_pct:  # -50%より大きい（下落が不十分）
            continue

        # RSI
        rsi = _calc_rsi(closes)
        if rsi >= rsi_threshold:
            continue

        # 出来高増加（底打ちの兆候）
        if len(volumes) < 3:
            continue
        vol_today = float(volumes[-1])
        vol_prev = float(volumes[-2])
        if vol_prev <= 0 or vol_today / vol_prev < vol_surge_min:
            continue

        # セクターボーナス
        sector = sector_map.get(symbol, '')
        sector_bonus = 1.3 if sector in preferred_sectors else 1.0

        score = abs(drop_from_high) * (1 / max(rsi, 1)) * (vol_today / vol_prev) * sector_bonus
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'rsi': float(rsi),
                'drop_from_high': float(drop_from_high),
                'vol_surge': float(vol_today / vol_prev),
                'age': age,
                'sector': sector,
                'side': 'long',
            }

    return best_target
