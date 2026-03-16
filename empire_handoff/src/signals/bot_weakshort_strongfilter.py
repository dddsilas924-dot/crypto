"""Bot-WeakShort-StrongFilter: 逆行アルト（強いアルト）を除外する改良版

BTCが上がっているのにアルトも上がっている = 強い → ショート対象から除外
7日間のモメンタム + 出来高増加トレンド + RSI > 60 で「強者」判定 → 除外
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    fear_min = config.get('fear_min', 50)
    fear_max = config.get('fear_max', 75)
    btc_gain_min = config.get('btc_gain_min', 1.0)
    divergence_min = config.get('divergence_min', 3.0)

    if not (fear_min <= fg <= fear_max):
        return None
    if btc_return < btc_gain_min:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_div = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 10:
            continue

        closes = sym_df['close'].values
        volumes = sym_df['volume'].values
        sym_close = float(closes[-1])
        sym_prev = float(closes[-2])
        sym_ret = (sym_close - sym_prev) / sym_prev * 100

        divergence = btc_return - sym_ret
        if divergence < divergence_min:
            continue

        # === 強者フィルター: 7日モメンタム + 出来高増 + RSI ===
        if len(closes) >= 8:
            mom_7d = (float(closes[-1]) - float(closes[-8])) / float(closes[-8]) * 100
            # 7日で+5%以上上昇していたアルトは「実は強い」 → 除外
            if mom_7d > 5.0:
                continue

        if len(volumes) >= 8:
            vol_recent = np.mean(volumes[-3:])
            vol_old = np.mean(volumes[-8:-3])
            # 直近出来高が増加トレンド = 資金流入中 → 除外
            if vol_old > 0 and vol_recent / vol_old > 1.5:
                continue

        # RSI計算（14日）
        if len(closes) >= 15:
            diffs = np.diff(closes[-15:])
            gains = np.where(diffs > 0, diffs, 0)
            losses_arr = np.where(diffs < 0, -diffs, 0)
            avg_gain = np.mean(gains) if len(gains) > 0 else 0
            avg_loss = np.mean(losses_arr) if len(losses_arr) > 0 else 0
            rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
            # RSI > 60 = まだ強い → ショートすると焼かれる → 除外
            if rsi > 60:
                continue

        score = divergence
        if score > best_div:
            best_div = score
            best_target = {
                'symbol': symbol, 'price': sym_close,
                'sym_return': float(sym_ret), 'btc_return': float(btc_return),
                'divergence': float(divergence), 'side': 'short',
            }

    return best_target
