"""Bot-HF-MeanRevert: 1h足平均回帰

1h足RSI + ボリンジャーバンドで「上がりすぎ/下がりすぎ」を検知して逆張り。
- RSI > 75 + BB上限超え → ショート
- RSI < 25 + BB下限超え → ロング
- 出来高が24h平均の2倍以上（流動性確保）
"""
import pandas as pd
import numpy as np
from typing import Optional


def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.iloc[1:period+1].mean()
    avg_loss = loss.iloc[1:period+1].mean()
    for i in range(period + 1, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_bb(closes: pd.Series, period: int = 20, std_mult: float = 2.0):
    if len(closes) < period:
        return None, None, None
    ma = closes.rolling(period).mean().iloc[-1]
    std = closes.rolling(period).std().iloc[-1]
    return ma, ma + std_mult * std, ma - std_mult * std


def check_signal_hf(conn, fg: int, btc_return_1h: float, btc_1h: pd.DataFrame,
                     current_ts: pd.Timestamp, symbols: list, config: dict) -> Optional[dict]:
    """1h足シグナル判定（緩和版: RSI + BB のいずれか + 出来高）"""
    rsi_high = config.get('rsi_high', 70)
    rsi_low = config.get('rsi_low', 30)
    vol_ratio_min = config.get('vol_ratio_min', 1.5)
    bb_period = config.get('bb_period', 20)

    ts_ms = int(current_ts.timestamp() * 1000)
    lookback_ms = 24 * 3600 * 1000  # 24h
    bb_lookback_ms = (bb_period + 10) * 3600 * 1000  # BB期間+余裕

    best = None
    best_score = 0

    for sym in symbols[:200]:
        try:
            # 直近BB期間+αの1h足を取得
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=? AND timeframe='1h' AND timestamp > ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (sym, ts_ms - bb_lookback_ms - 3600000, ts_ms)
            ).fetchall()

            if len(rows) < bb_period + 2:
                continue

            closes = pd.Series([r[4] for r in rows])
            volumes = [r[5] for r in rows]
            current_close = closes.iloc[-1]

            if current_close <= 0:
                continue

            # RSI
            rsi = _calc_rsi(closes)

            # ボリンジャーバンド
            ma, bb_upper, bb_lower = _calc_bb(closes, bb_period)
            if ma is None:
                continue

            # 出来高チェック (直近4h vs 24h平均)
            recent_vol = sum(volumes[-4:])
            if len(volumes) >= 24:
                avg_vol_24h = sum(volumes[-24:]) / 24 * 4
            else:
                avg_vol_24h = sum(volumes) / len(volumes) * 4
            vol_ratio = recent_vol / avg_vol_24h if avg_vol_24h > 0 else 0

            if vol_ratio < vol_ratio_min:
                continue

            # シグナル判定: RSI条件 OR BB条件 (いずれか+出来高)
            is_overbought = rsi > rsi_high or current_close > bb_upper
            is_oversold = rsi < rsi_low or current_close < bb_lower

            if is_overbought:
                bb_dev = (current_close - bb_upper) / ma * 100 if current_close > bb_upper else 0
                rsi_excess = max(rsi - rsi_high, 0)
                score = rsi_excess + bb_dev * 3 + vol_ratio
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'short', 'rsi': round(rsi, 1),
                        'bb_dev': round(bb_dev, 2), 'vol_ratio': round(vol_ratio, 1),
                    }

            elif is_oversold:
                bb_dev = (bb_lower - current_close) / ma * 100 if current_close < bb_lower else 0
                rsi_excess = max(rsi_low - rsi, 0)
                score = rsi_excess + bb_dev * 3 + vol_ratio
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'long', 'rsi': round(rsi, 1),
                        'bb_dev': round(bb_dev, 2), 'vol_ratio': round(vol_ratio, 1),
                    }

        except Exception:
            continue

    return best
