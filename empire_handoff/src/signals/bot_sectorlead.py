"""Bot-SectorLead: セクターリーダー先行反発ロング（Fear<25, リーダー反発→フォロワー遅延買い）"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

SECTOR_LEADERS = {
    'SOL/USDT:USDT': 'Solana',
    'ETH/USDT:USDT': 'Ethereum',
    'BNB/USDT:USDT': 'BNB',
}


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_max = config.get('fear_max', 25)
    leader_gain_min = config.get('leader_gain_min', 2.0)

    if fg >= fear_max:
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)

    for leader_sym, chain in SECTOR_LEADERS.items():
        leader_df = pd.read_sql_query(
            "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
            conn, params=(leader_sym, end_ts)
        )
        if len(leader_df) < 2:
            continue

        leader_close = float(leader_df.iloc[0]['close'])
        leader_prev = float(leader_df.iloc[1]['close'])
        leader_ret = (leader_close - leader_prev) / leader_prev * 100

        if leader_ret < leader_gain_min:
            continue

        # フォロワー: 同チェーンでまだ下落中の銘柄
        followers = [r[0] for r in conn.execute(
            "SELECT symbol FROM sector WHERE chain=? AND is_crypto=1 AND symbol != ?",
            (chain, leader_sym)
        ).fetchall()]

        best_follower = None
        best_lag = 0

        for fsym in followers[:50]:
            f_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
                conn, params=(fsym, end_ts)
            )
            if len(f_df) < 2:
                continue

            f_close = float(f_df.iloc[0]['close'])
            f_prev = float(f_df.iloc[1]['close'])
            f_ret = (f_close - f_prev) / f_prev * 100

            # フォロワーがまだ下落中
            if f_ret >= 0:
                continue

            lag = leader_ret - f_ret
            if lag > best_lag:
                best_lag = lag
                best_follower = {
                    'symbol': fsym,
                    'price': f_close,
                    'leader': leader_sym.split('/')[0],
                    'leader_ret': float(leader_ret),
                    'follower_ret': float(f_ret),
                    'lag': float(lag),
                    'side': 'long',
                }

        if best_follower:
            return best_follower

    return None
