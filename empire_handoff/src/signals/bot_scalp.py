"""Bot-Scalp: 高速回転（BB±2σタッチ + RSI極値、日足代用）

注意: 本来1h足ベースだが、1hヒストリカルデータ不足のため日足で代用。
資金の5%のみ使用、高レバレッジ。高頻度。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    # Fear制限なし（常時稼働）
    bb_period = config.get('bb_period', 20)
    bb_std = config.get('bb_std', 2.0)
    rsi_period = config.get('rsi_period', 14)
    rsi_oversold = config.get('rsi_oversold', 30)
    rsi_overbought = config.get('rsi_overbought', 70)

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 40 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 25:
            continue

        closes = sym_df['close'].values
        current = float(closes[-1])

        # ボリンジャーバンド
        ma = np.mean(closes[-bb_period:])
        std = np.std(closes[-bb_period:])
        upper_bb = ma + bb_std * std
        lower_bb = ma - bb_std * std

        # RSI計算
        deltas = np.diff(closes[-rsi_period - 1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # BB下限タッチ + RSI oversold → ロング
        if current <= lower_bb and rsi <= rsi_oversold:
            deviation = (lower_bb - current) / lower_bb * 100
            score = abs(deviation) * (rsi_oversold - rsi + 1)
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'rsi': float(rsi),
                    'bb_dev': float(deviation),
                    'side': 'long',
                }

        # BB上限タッチ + RSI overbought → ショート
        elif current >= upper_bb and rsi >= rsi_overbought:
            deviation = (current - upper_bb) / upper_bb * 100
            score = abs(deviation) * (rsi - rsi_overbought + 1)
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'rsi': float(rsi),
                    'bb_dev': float(deviation),
                    'side': 'short',
                }

    return best_target
