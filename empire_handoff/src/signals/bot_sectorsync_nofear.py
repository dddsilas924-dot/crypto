"""Bot-SectorSync-NoFear: Fear制限なしセクター同期異常
4つのタイムフレーム派生: 1d(default), 3d, 1h_proxy(=1d with lag1), 1min_proxy(=1d tight)
bot_type名で分岐: sectorsync_nofear_1d / _3d / _1h / _1m
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

SECTOR_REPRESENTATIVES = {
    'DeFi': ['UNI/USDT:USDT', 'AAVE/USDT:USDT', 'CAKE/USDT:USDT', 'DYDX/USDT:USDT', 'SUSHI/USDT:USDT'],
    'AI': ['FET/USDT:USDT', 'RENDER/USDT:USDT', 'TAO/USDT:USDT', 'AR/USDT:USDT', 'AIOZ/USDT:USDT'],
    'Gaming': ['AXS/USDT:USDT', 'GALA/USDT:USDT', 'IMX/USDT:USDT', 'BIGTIME/USDT:USDT', 'ALICE/USDT:USDT'],
    'Meme': ['DOGE/USDT:USDT', '1000BONK/USDT:USDT', '1000PEPE/USDT:USDT', 'FLOKI/USDT:USDT', 'WIF/USDT:USDT'],
    'L1L2': ['SOL/USDT:USDT', 'AVAX/USDT:USDT', 'NEAR/USDT:USDT', 'APT/USDT:USDT', 'SUI/USDT:USDT'],
}

# タイムフレーム別パラメータ
TIMEFRAME_PARAMS = {
    '1d': {'lookback_days': 3, 'sync_threshold': 3.0, 'lag_threshold': 1.0},
    '3d': {'lookback_days': 9, 'sync_threshold': 5.0, 'lag_threshold': 2.0},
    '1h': {'lookback_days': 1, 'sync_threshold': 1.5, 'lag_threshold': 0.5},
    '1m': {'lookback_days': 1, 'sync_threshold': 1.0, 'lag_threshold': 0.3},
}


def _calc_sector_return(conn, sector_symbols, end_ts, days):
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


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    # タイムフレーム判定（config経由）
    tf = config.get('timeframe', '1d')
    params = TIMEFRAME_PARAMS.get(tf, TIMEFRAME_PARAMS['1d'])

    lookback_days = config.get('lookback_days', params['lookback_days'])
    sync_threshold = config.get('sync_threshold', params['sync_threshold'])
    lag_threshold = config.get('lag_threshold', params['lag_threshold'])

    # Fear制限なし（従来との最大の違い）

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)

    sector_returns = {}
    for sector, syms in SECTOR_REPRESENTATIVES.items():
        ret = _calc_sector_return(conn, syms, end_ts, lookback_days)
        sector_returns[sector] = ret

    if len(sector_returns) < 3:
        return None

    synced = [s for s, r in sector_returns.items() if r >= sync_threshold]
    lagging = [s for s, r in sector_returns.items() if r < lag_threshold]

    if len(synced) < 2 or len(lagging) < 1:
        return None

    best_lag_sector = min(lagging, key=lambda s: sector_returns[s])
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
                'synced_sectors': ','.join(synced),
                'lag_sector': best_lag_sector,
                'lag_sector_ret': float(sector_returns[best_lag_sector]),
                'side': 'long',
            }

    return best_target
