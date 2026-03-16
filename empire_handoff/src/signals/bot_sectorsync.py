"""Bot-SectorSync: クロスセクター同期異常（通常無相関セクター同期 → 遅延セクター買い）

ナレッジ: L17(相関シフト)逆用 + L21(セクターローテ)
逆説: 全既存Botは「低相関」を探す。このBotは逆に「通常無相関のセクターが同期した異常」を検知。
DeFiとMemeが同時に上がるのは「ありえない」が、マクロ資金流入時に発生。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

# セクター分類（sector_mapping.pyのMessariセクターから主要なもの）
SECTOR_REPRESENTATIVES = {
    'DeFi': ['UNI/USDT:USDT', 'AAVE/USDT:USDT', 'CAKE/USDT:USDT', 'DYDX/USDT:USDT', 'SUSHI/USDT:USDT'],
    'AI': ['FET/USDT:USDT', 'RENDER/USDT:USDT', 'TAO/USDT:USDT', 'AR/USDT:USDT', 'AIOZ/USDT:USDT'],
    'Gaming': ['AXS/USDT:USDT', 'GALA/USDT:USDT', 'IMX/USDT:USDT', 'BIGTIME/USDT:USDT', 'ALICE/USDT:USDT'],
    'Meme': ['DOGE/USDT:USDT', '1000BONK/USDT:USDT', '1000PEPE/USDT:USDT', 'FLOKI/USDT:USDT', 'WIF/USDT:USDT'],
    'L1L2': ['SOL/USDT:USDT', 'AVAX/USDT:USDT', 'NEAR/USDT:USDT', 'APT/USDT:USDT', 'SUI/USDT:USDT'],
}


def _calc_sector_return(conn, sector_symbols: list, end_ts: int, days: int) -> float:
    """セクターの平均リターンを計算"""
    start_ts = end_ts - (days + 2) * 86400000
    returns = []
    for sym in sector_symbols:
        df = pd.read_sql_query(
            "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(sym, start_ts, end_ts)
        )
        if len(df) < days + 1:
            continue
        closes = df['close'].values
        old = float(closes[-(days + 1)])
        new = float(closes[-1])
        if old > 0:
            returns.append((new - old) / old * 100)
    return np.mean(returns) if returns else 0.0


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 30)
    fear_max = config.get('fear_max', 70)
    sync_threshold = config.get('sync_threshold', 3.0)  # 2セクター > +3%
    lag_threshold = config.get('lag_threshold', 1.0)  # 遅延セクター < +1%
    lookback_days = config.get('lookback_days', 3)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)

    # 各セクターの3日リターン計算
    sector_returns = {}
    for sector, syms in SECTOR_REPRESENTATIVES.items():
        ret = _calc_sector_return(conn, syms, end_ts, lookback_days)
        sector_returns[sector] = ret

    if len(sector_returns) < 3:
        return None

    # 同期上昇セクターペアを探す
    sectors = list(sector_returns.keys())
    synced_sectors = []
    lagging_sectors = []

    for s in sectors:
        if sector_returns[s] >= sync_threshold:
            synced_sectors.append(s)
        elif sector_returns[s] < lag_threshold:
            lagging_sectors.append(s)

    # 2セクター以上が同期上昇 + 1セクター以上が遅延
    if len(synced_sectors) < 2 or len(lagging_sectors) < 1:
        return None

    # 最も遅れているセクターの銘柄から選択
    best_lag_sector = min(lagging_sectors, key=lambda s: sector_returns[s])
    lag_symbols = SECTOR_REPRESENTATIVES.get(best_lag_sector, [])

    best_target = None
    best_vol = 0
    start_ts = end_ts - 25 * 86400000

    for sym in lag_symbols:
        df = pd.read_sql_query(
            "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(sym, start_ts, end_ts)
        )
        if len(df) < 5:
            continue

        vol = float(df['volume'].values[-1])
        if vol > best_vol:
            best_vol = vol
            best_target = {
                'symbol': sym,
                'price': float(df['close'].values[-1]),
                'synced_sectors': ','.join(synced_sectors),
                'lag_sector': best_lag_sector,
                'lag_sector_ret': float(sector_returns[best_lag_sector]),
                'side': 'long',
            }

    return best_target
