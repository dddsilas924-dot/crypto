"""Bot-HF-FRArb: Funding Rate裁定

Funding Rateが極端に偏った銘柄で逆ポジションを取る:
- FR > +0.05% → ショート（ロング過剰、FR収入 + 価格下落期待）
- FR < -0.05% → ロング（ショート過剰、FR収入 + 価格上昇期待）

NOTE: 現在のDBにはFRデータが格納されていないため、
代替として「過去8hの価格変動率」をFRのプロキシとして使用。
- 8h連続上昇 + RSI > 70 → ロング過剰（ショート有利）
- 8h連続下落 + RSI < 30 → ショート過剰（ロング有利）
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


def check_signal_hf(conn, fg: int, btc_return_1h: float, btc_1h: pd.DataFrame,
                     current_ts: pd.Timestamp, symbols: list, config: dict) -> Optional[dict]:
    """FR裁定シグナル（プロキシ版）"""
    rsi_overbought = config.get('rsi_overbought', 70)
    rsi_oversold = config.get('rsi_oversold', 30)
    momentum_hours = config.get('momentum_hours', 8)
    momentum_threshold = config.get('momentum_threshold', 3.0)  # 8hで3%以上の動き

    ts_ms = int(current_ts.timestamp() * 1000)
    lookback_ms = 24 * 3600 * 1000

    best = None
    best_score = 0

    for sym in symbols[:200]:
        try:
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=? AND timeframe='1h' AND timestamp > ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (sym, ts_ms - lookback_ms, ts_ms)
            ).fetchall()

            if len(rows) < momentum_hours + 2:
                continue

            closes = pd.Series([r[4] for r in rows])
            current_close = closes.iloc[-1]
            if current_close <= 0:
                continue

            # 8h前の価格からの変動率
            if len(closes) >= momentum_hours:
                price_8h_ago = closes.iloc[-momentum_hours]
                momentum_pct = (current_close - price_8h_ago) / price_8h_ago * 100
            else:
                continue

            if abs(momentum_pct) < momentum_threshold:
                continue

            # RSI
            rsi = _calc_rsi(closes)

            # 出来高チェック（最低限の流動性）
            volumes = [r[5] for r in rows]
            avg_vol = np.mean(volumes[-24:]) if len(volumes) >= 24 else np.mean(volumes)
            recent_vol = np.mean(volumes[-4:])
            if avg_vol * current_close < 100000:  # $100K以下は流動性不足
                continue

            # シグナル判定
            if momentum_pct > momentum_threshold and rsi > rsi_overbought:
                # ロング過剰 → ショート
                score = abs(momentum_pct) * (rsi - 50) / 50
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'short', 'momentum_8h': round(momentum_pct, 2),
                        'rsi': round(rsi, 1),
                    }

            elif momentum_pct < -momentum_threshold and rsi < rsi_oversold:
                # ショート過剰 → ロング
                score = abs(momentum_pct) * (50 - rsi) / 50
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'long', 'momentum_8h': round(momentum_pct, 2),
                        'rsi': round(rsi, 1),
                    }

        except Exception:
            continue

    return best
