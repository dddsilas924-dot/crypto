"""Bot-GapTrap: 窓埋めトラップ（大幅ギャップ + 低出来高 = 偽ブレイク → 逆張り）

ナレッジ: L12(イベントリスク) + L03(出来高)逆 + L15(ATR)
逆説: ギャップアップ＝「強い」と解釈するのが常識。しかし出来高を伴わないギャップは偽物。
ギャップパターンは既存Botで一度も使用されていない完全な空白領域。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    # Fear制限なし（常時稼働）
    gap_threshold = config.get('gap_threshold', 3.0)  # |open - prev_close| > 3%
    vol_low_max = config.get('vol_low_max', 0.8)  # 出来高 < 20日平均の0.8倍

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    best_target = None
    best_score = 0

    for symbol in symbols[:100]:
        sym_df = pd.read_sql_query(
            "SELECT open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 22:
            continue

        closes = sym_df['close'].values
        opens = sym_df['open'].values
        volumes = sym_df['volume'].values

        prev_close = float(closes[-2])
        today_open = float(opens[-1])
        today_vol = float(volumes[-1])

        if prev_close <= 0:
            continue

        # ギャップ計算
        gap_pct = (today_open - prev_close) / prev_close * 100

        if abs(gap_pct) < gap_threshold:
            continue

        # 出来高チェック: 低出来高 = ファンダなしギャップ
        vol_avg20 = np.mean(volumes[-22:-2])
        if vol_avg20 <= 0:
            continue
        vol_ratio = today_vol / vol_avg20

        if vol_ratio > vol_low_max:
            continue  # 出来高が伴っている場合はスキップ（本物のブレイク）

        # ギャップの方向で逆張り
        if gap_pct > 0:
            side = 'short'  # ギャップアップ → ショート（窓埋め）
        else:
            side = 'long'   # ギャップダウン → ロング（窓埋め）

        # スコア: ギャップの大きさ × 出来高の低さ（逆数）
        score = abs(gap_pct) * (1 / max(vol_ratio, 0.01))
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': float(closes[-1]),
                'gap_pct': float(gap_pct),
                'vol_ratio': float(vol_ratio),
                'side': side,
            }

    return best_target
