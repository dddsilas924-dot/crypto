"""Bot-DomShift: BTC独走→アルト回転（BTC.Dプロキシで独走極限検知 → アルト先回り）

ナレッジ: L01(ドミナンスマトリクス) + L21(セクターローテ)
逆説: BTC+5%時にアルトを買う人はいない。しかしBTC独走の極限はアルトシーズン直前。
L01は一度もBot化されていない最重要未使用ナレッジ。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 40)
    fear_max = config.get('fear_max', 75)
    btc_7d_gain_min = config.get('btc_7d_gain_min', 5.0)  # BTC 7日 > +5%
    alt_lag_max = config.get('alt_lag_max', 25.0)  # アルト中央値 < BTCの25%
    alt_vol_recovery = config.get('alt_vol_recovery', 1.2)  # アルト出来高回復

    if not (fear_min <= fg <= fear_max):
        return None

    # BTC 7日リターン
    btc_recent = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(8)
    if len(btc_recent) < 8:
        return None
    btc_7d_ret = (float(btc_recent['close'].iloc[-1]) - float(btc_recent['close'].iloc[0])) / float(btc_recent['close'].iloc[0]) * 100
    if btc_7d_ret < btc_7d_gain_min:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 10 * 86400000

    # アルト群の7日リターン計算
    alt_returns = []
    alt_candidates = []

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 8:
            continue

        closes = sym_df['close'].values
        volumes = sym_df['volume'].values
        current = float(closes[-1])
        close_8d = float(closes[-8]) if len(closes) >= 8 else float(closes[0])

        if close_8d <= 0:
            continue

        alt_ret = (current - close_8d) / close_8d * 100
        alt_returns.append(alt_ret)

        # 出来高回復チェック
        if len(volumes) >= 3 and float(volumes[-2]) > 0:
            vol_change = float(volumes[-1]) / float(volumes[-2])
        else:
            vol_change = 1.0

        alt_candidates.append({
            'symbol': symbol,
            'price': current,
            'alt_ret': float(alt_ret),
            'vol_change': float(vol_change),
        })

    if len(alt_returns) < 10:
        return None

    # アルト中央値がBTCの alt_lag_max% 未満（アルト遅延確認）
    alt_median = np.median(alt_returns)
    lag_ratio = (alt_median / btc_7d_ret * 100) if btc_7d_ret > 0 else 100

    if lag_ratio > alt_lag_max:
        return None

    # 最も遅れている + 出来高が回復しているアルトを選択
    best_target = None
    best_score = 0

    for c in alt_candidates:
        # 遅延度が大きく、出来高が回復しているものを優先
        if c['alt_ret'] >= alt_median:
            continue  # 中央値以上に上がっているものは除外

        lag = alt_median - c['alt_ret']  # 中央値からさらに遅れている度合い
        if c['vol_change'] < alt_vol_recovery:
            continue  # 出来高回復なし

        score = lag * c['vol_change']
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': c['symbol'],
                'price': c['price'],
                'btc_7d_ret': float(btc_7d_ret),
                'alt_median_ret': float(alt_median),
                'alt_ret': c['alt_ret'],
                'lag_ratio': float(lag_ratio),
                'side': 'long',
            }

    return best_target
