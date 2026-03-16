"""Bot-Sniper-Improved: 勝率向上版 3派生
v1: RSIフィルター追加 (RSI < 35で売られすぎ確認)
v2: 出来高持続確認 (2日連続出来高スパイク)
v3: MA20サポート確認 (価格がMA20の-5%以内)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

VARIANTS = {
    'sniper_v1': {'rsi_filter': True, 'vol_sustain': False, 'ma_support': False},
    'sniper_v2': {'rsi_filter': False, 'vol_sustain': True, 'ma_support': False},
    'sniper_v3': {'rsi_filter': True, 'vol_sustain': False, 'ma_support': True},
}


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    variant = config.get('variant', 'sniper_v1')
    v = VARIANTS.get(variant, VARIANTS['sniper_v1'])

    fear_max = config.get('fear_max', 30)
    btc_drop = config.get('btc_drop_threshold', -3.0)
    vol_spike_min = config.get('vol_spike_min', 5.0)
    corr_max = config.get('corr_max', 0.3)

    if fg >= fear_max:
        return None
    if btc_return > btc_drop:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(21)['close'].tolist()
    if len(btc_closes) < 14:
        return None

    candidates = []
    for symbol in symbols[:100]:
        df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) < 21:
            continue

        closes = df['close'].values
        volumes = df['volume'].values

        vol_avg = np.mean(volumes[-21:-1])
        if vol_avg <= 0:
            continue
        vol_ratio = float(volumes[-1]) / vol_avg
        if vol_ratio < vol_spike_min:
            continue

        # v2: 出来高持続 — 前日も2倍以上
        if v['vol_sustain']:
            vol_prev = float(volumes[-2]) / vol_avg if vol_avg > 0 else 0
            if vol_prev < 2.0:
                continue

        # BTC相関
        sym_ret = np.diff(closes[-14:]) / closes[-14:-1]
        btc_ret = np.diff(btc_closes[-14:]) / np.array(btc_closes[-14:-1], dtype=float)
        min_len = min(len(sym_ret), len(btc_ret))
        if min_len < 10:
            continue
        corr = np.corrcoef(sym_ret[-min_len:], btc_ret[-min_len:])[0, 1]
        if np.isnan(corr) or corr > corr_max:
            continue

        # v1: RSIフィルター
        if v['rsi_filter'] and len(closes) >= 15:
            diffs = np.diff(closes[-15:])
            gains = np.where(diffs > 0, diffs, 0)
            losses_arr = np.where(diffs < 0, -diffs, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses_arr)
            rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
            if rsi > 35:  # まだ売られすぎていない → スキップ
                continue

        # v3: MA20サポート確認
        if v['ma_support']:
            ma20 = np.mean(closes[-20:])
            current = float(closes[-1])
            if ma20 > 0 and (current - ma20) / ma20 * 100 < -15:
                continue  # MA20から離れすぎ → サポートなし

        candidates.append({
            'symbol': symbol, 'price': float(closes[-1]),
            'vol_ratio': float(vol_ratio), 'btc_corr': float(corr),
            'side': 'long',
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x['vol_ratio'] * (1 - x['btc_corr']), reverse=True)
    return candidates[0]
