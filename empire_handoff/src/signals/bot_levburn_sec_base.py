"""LevBurn-Sec ベースシグナル（外部モジュール版 — バックテスト用）
BacktestEngineの_check_levburn_signalと同等のロジックを独立関数として提供"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def _estimate_fr_proxy(df, i):
    if i < 3:
        return {"fr_proxy": 0.0, "vol_ratio": 1.0, "atr_ratio": 1.0}
    consecutive_up = sum(1 for j in range(1, 4) if i - j >= 0 and df.iloc[i - j]["close"] > df.iloc[i - j]["open"])
    consecutive_down = sum(1 for j in range(1, 4) if i - j >= 0 and df.iloc[i - j]["close"] <= df.iloc[i - j]["open"])

    vol_start = max(0, i - 20)
    vol_window = df.iloc[vol_start:i]["volume"]
    vol_mean = vol_window.mean() if len(vol_window) > 0 else 1.0
    vol_ratio = df.iloc[i]["volume"] / vol_mean if vol_mean > 0 else 1.0

    atr_5 = float(df.iloc[max(0, i - 5):i + 1]["high"].max() - df.iloc[max(0, i - 5):i + 1]["low"].min())
    atr_20 = float(df.iloc[max(0, i - 20):i + 1]["high"].max() - df.iloc[max(0, i - 20):i + 1]["low"].min()) or atr_5
    atr_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0

    close_p = float(df.iloc[i]["close"])
    open_p = float(df.iloc[i]["open"])
    daily_change = (close_p - open_p) / open_p * 100 if open_p > 0 else 0

    fr_proxy = 0.0
    if consecutive_up >= 3 and vol_ratio > 2:
        fr_proxy = daily_change * 0.3
    elif consecutive_down >= 3 and vol_ratio > 2:
        fr_proxy = daily_change * 0.3
    elif vol_ratio > 3:
        fr_proxy = daily_change * 0.2
    else:
        fr_proxy = daily_change * 0.1

    return {"fr_proxy": fr_proxy, "vol_ratio": vol_ratio, "atr_ratio": atr_ratio}


def check_levburn_sec_base(conn, fg, btc_return, btc_df, date_str, symbols, config):
    fr_threshold = config.get('fr_threshold', 0.3)
    vol_threshold = config.get('vol_threshold', 3.0)

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    ts = int(dt.timestamp() * 1000)
    start_ts = ts - 25 * 86400000

    best_candidate = None
    best_score = -1

    for symbol in symbols[:200]:
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, ts)
        )
        if len(df) < 20:
            continue

        i = len(df) - 1
        proxy = _estimate_fr_proxy(df, i)
        fr = proxy["fr_proxy"]
        vol_r = proxy["vol_ratio"]
        atr_r = proxy["atr_ratio"]

        if abs(fr) < fr_threshold:
            continue
        if vol_r < vol_threshold:
            continue

        score = abs(fr) * 30 + min(vol_r / 5, 1.0) * 20 + min(atr_r, 2.0) * 10
        if fg < 25 and fr < 0:
            score += 10
        elif fg > 75 and fr > 0:
            score += 10

        if score > best_score:
            best_score = score
            side = 'short' if fr > 0 else 'long'
            best_candidate = {
                'symbol': symbol, 'side': side,
                'price': float(df.iloc[i]['close']),
                'fr_value': fr, 'vol_ratio': vol_r, 'score': score,
            }

    return best_candidate
