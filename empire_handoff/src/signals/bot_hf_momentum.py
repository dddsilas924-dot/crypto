"""Bot-HF-Momentum: 1h足モメンタム順張り

短期の強いトレンドに乗る:
- 3連続陽線/陰線
- 直近1hの出来高が前の1hの2倍以上
- EMA(5) と EMA(20) の乖離が拡大中
"""
import pandas as pd
import numpy as np
from typing import Optional


def check_signal_hf(conn, fg: int, btc_return_1h: float, btc_1h: pd.DataFrame,
                     current_ts: pd.Timestamp, symbols: list, config: dict) -> Optional[dict]:
    """1h足モメンタムシグナル"""
    consecutive = config.get('consecutive_bars', 3)
    vol_spike = config.get('vol_spike_ratio', 2.0)
    ema_fast = config.get('ema_fast', 5)
    ema_slow = config.get('ema_slow', 20)

    ts_ms = int(current_ts.timestamp() * 1000)
    lookback_ms = (ema_slow + 5) * 3600 * 1000

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

            if len(rows) < ema_slow + 2:
                continue

            closes = pd.Series([r[4] for r in rows])
            opens = [r[1] for r in rows]
            volumes = [r[5] for r in rows]
            current_close = closes.iloc[-1]

            if current_close <= 0:
                continue

            # 3連続陽線/陰線チェック
            bullish_count = 0
            bearish_count = 0
            for i in range(-consecutive, 0):
                if closes.iloc[i] > opens[i]:
                    bullish_count += 1
                elif closes.iloc[i] < opens[i]:
                    bearish_count += 1

            is_bullish = bullish_count == consecutive
            is_bearish = bearish_count == consecutive

            if not is_bullish and not is_bearish:
                continue

            # 出来高加速
            curr_vol = volumes[-1]
            prev_vol = volumes[-2] if len(volumes) >= 2 else 1
            vol_ratio = curr_vol / prev_vol if prev_vol > 0 else 0
            if vol_ratio < vol_spike:
                continue

            # EMA乖離拡大
            ema_f = closes.ewm(span=ema_fast).mean()
            ema_s = closes.ewm(span=ema_slow).mean()
            ema_gap_now = (ema_f.iloc[-1] - ema_s.iloc[-1]) / ema_s.iloc[-1] * 100
            ema_gap_prev = (ema_f.iloc[-2] - ema_s.iloc[-2]) / ema_s.iloc[-2] * 100

            # EMA乖離が拡大していること
            if is_bullish and ema_gap_now <= ema_gap_prev:
                continue
            if is_bearish and ema_gap_now >= ema_gap_prev:
                continue

            # スコアリング
            gap_change = abs(ema_gap_now - ema_gap_prev)
            score = gap_change * 10 + vol_ratio

            if score > best_score:
                side = 'long' if is_bullish else 'short'
                best_score = score
                best = {
                    'symbol': sym, 'price': current_close,
                    'side': side, 'vol_ratio': round(vol_ratio, 1),
                    'ema_gap': round(ema_gap_now, 2),
                }

        except Exception:
            continue

    return best
