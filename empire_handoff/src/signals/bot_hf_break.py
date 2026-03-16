"""Bot-HF-Break: 1h足レンジブレイクアウト

直近12時間のレンジが収縮した後のブレイクアウトに飛び乗る:
- レンジ幅が平均の50%以下（収束中 = ブレイク前兆）
- 12hレンジの高値/安値を1h足終値で上抜け/下抜けでエントリー
"""
import pandas as pd
import numpy as np
from typing import Optional


def check_signal_hf(conn, fg: int, btc_return_1h: float, btc_1h: pd.DataFrame,
                     current_ts: pd.Timestamp, symbols: list, config: dict) -> Optional[dict]:
    """レンジブレイクアウトシグナル"""
    range_hours = config.get('range_hours', 12)
    range_squeeze = config.get('range_squeeze_ratio', 0.5)
    avg_range_hours = config.get('avg_range_hours', 48)  # 平均レンジ計算期間

    ts_ms = int(current_ts.timestamp() * 1000)
    lookback_ms = avg_range_hours * 3600 * 1000
    range_ms = range_hours * 3600 * 1000

    best = None
    best_score = 0

    for sym in symbols[:200]:
        try:
            # 直近48h分のデータ
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=? AND timeframe='1h' AND timestamp > ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (sym, ts_ms - lookback_ms, ts_ms)
            ).fetchall()

            if len(rows) < avg_range_hours // 2:
                continue

            highs = [r[2] for r in rows]
            lows = [r[3] for r in rows]
            closes = [r[4] for r in rows]
            current_close = closes[-1]

            if current_close <= 0:
                continue

            # 直近12hのレンジ (現在足を除く前12本)
            if len(highs) < range_hours + 1:
                continue
            range_high = max(highs[-(range_hours+1):-1])
            range_low = min(lows[-(range_hours+1):-1])
            range_width = (range_high - range_low) / current_close * 100

            # 全体の平均レンジ (12h窓のローリング)
            if len(highs) >= range_hours * 2:
                ranges = []
                for i in range(range_hours, len(highs)):
                    h = max(highs[i-range_hours:i])
                    l = min(lows[i-range_hours:i])
                    ranges.append((h - l) / closes[i] * 100 if closes[i] > 0 else 0)
                avg_range = np.mean(ranges) if ranges else range_width
            else:
                avg_range = range_width * 2  # データ不足時は大きめに

            if avg_range == 0:
                continue

            # レンジ収縮チェック
            squeeze_ratio = range_width / avg_range
            if squeeze_ratio > range_squeeze:
                continue  # まだ十分に収縮していない

            # ブレイクアウト判定
            if current_close > range_high:
                # 上方ブレイク → ロング
                breakout_pct = (current_close - range_high) / range_high * 100
                score = (1 / squeeze_ratio) * breakout_pct * 10
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'long', 'breakout_pct': round(breakout_pct, 2),
                        'squeeze_ratio': round(squeeze_ratio, 2),
                        'range_width': round(range_width, 2),
                    }
            elif current_close < range_low:
                # 下方ブレイク → ショート
                breakout_pct = (range_low - current_close) / range_low * 100
                score = (1 / squeeze_ratio) * breakout_pct * 10
                if score > best_score:
                    best_score = score
                    best = {
                        'symbol': sym, 'price': current_close,
                        'side': 'short', 'breakout_pct': round(breakout_pct, 2),
                        'squeeze_ratio': round(squeeze_ratio, 2),
                        'range_width': round(range_width, 2),
                    }

        except Exception:
            continue

    return best
