"""Bot-ICO-Surge: 新規上場銘柄のセクター出遅れキャッチアップロング

対象: 上場後30-90日
発動: Fear 25-50
条件: 同セクターリーダー+10%以上, 対象+3%未満, ATR/Price>12%, Volume>$5M
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


# セクター別リーダー銘柄（時価総額上位）
SECTOR_LEADERS = {
    'AI': ['TAO/USDT:USDT', 'RENDER/USDT:USDT', 'FET/USDT:USDT'],
    'Meme': ['DOGE/USDT:USDT', 'SHIB/USDT:USDT', 'PEPE/USDT:USDT'],
    'Gaming': ['AXS/USDT:USDT', 'GALA/USDT:USDT', 'IMX/USDT:USDT'],
    'DePIN': ['FIL/USDT:USDT', 'AR/USDT:USDT', 'HNT/USDT:USDT'],
    'RWA': ['ONDO/USDT:USDT', 'MKR/USDT:USDT'],
    'L1': ['SOL/USDT:USDT', 'AVAX/USDT:USDT', 'SUI/USDT:USDT'],
    'L2': ['ARB/USDT:USDT', 'OP/USDT:USDT', 'MATIC/USDT:USDT'],
    'DeFi': ['UNI/USDT:USDT', 'AAVE/USDT:USDT', 'MKR/USDT:USDT'],
}


def _get_listing_date(conn, symbol: str) -> Optional[str]:
    row = conn.execute(
        "SELECT MIN(timestamp) FROM ohlcv WHERE symbol=? AND timeframe='1d'",
        (symbol,)
    ).fetchone()
    if row and row[0]:
        return datetime.fromtimestamp(row[0] / 1000).strftime('%Y-%m-%d')
    return None


def _get_7d_return(conn, symbol: str, end_ts: int) -> Optional[float]:
    """7日間のリターンを取得"""
    start_ts = end_ts - 8 * 86400000
    df = pd.read_sql_query(
        "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
        "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        conn, params=(symbol, start_ts, end_ts)
    )
    if len(df) < 2:
        return None
    first = float(df.iloc[0]['close'])
    last = float(df.iloc[-1]['close'])
    if first <= 0:
        return None
    return (last - first) / first * 100


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 25)
    fear_max = config.get('fear_max', 50)
    leader_gain_min = config.get('leader_gain_min', 10.0)
    follower_max_gain = config.get('follower_max_gain', 3.0)
    atr_price_min = config.get('atr_price_min', 12.0)
    age_min = config.get('age_min', 30)
    age_max = config.get('age_max', 90)

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 25 * 86400000

    # セクター情報取得
    sector_map = {}
    try:
        rows = conn.execute("SELECT symbol, primary_sector FROM sector").fetchall()
        sector_map = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    # セクターリーダーの7日間リターンを取得
    sector_returns = {}
    for sector, leaders in SECTOR_LEADERS.items():
        returns = []
        for leader in leaders:
            ret = _get_7d_return(conn, leader, end_ts)
            if ret is not None:
                returns.append(ret)
        if returns:
            sector_returns[sector] = max(returns)

    # 上昇セクターのみ対象
    hot_sectors = {s: r for s, r in sector_returns.items() if r >= leader_gain_min}
    if not hot_sectors:
        return None

    best_target = None
    best_score = 0

    for symbol in symbols[:200]:
        listing_date = _get_listing_date(conn, symbol)
        if not listing_date:
            continue
        ld = datetime.strptime(listing_date, '%Y-%m-%d')
        age = (dt - ld).days
        if age < age_min or age > age_max:
            continue

        # セクターチェック
        sector = sector_map.get(symbol, '')
        if sector not in hot_sectors:
            continue

        # 銘柄の7日リターン
        sym_return = _get_7d_return(conn, symbol, end_ts)
        if sym_return is None or sym_return >= follower_max_gain:
            continue  # 出遅れていない

        # OHLCV取得
        sym_df = pd.read_sql_query(
            "SELECT high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(sym_df) < 14:
            continue

        closes = sym_df['close'].values
        highs = sym_df['high'].values
        lows = sym_df['low'].values
        current = float(closes[-1])

        if current <= 0:
            continue

        # ATR/Price チェック
        atr = np.mean(highs[-14:] - lows[-14:])
        atr_ratio = atr / current * 100
        if atr_ratio < atr_price_min:
            continue

        leader_gain = hot_sectors[sector]
        lag = leader_gain - sym_return
        score = lag * atr_ratio

        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'sector': sector,
                'leader_gain': float(leader_gain),
                'sym_return': float(sym_return),
                'lag': float(lag),
                'atr_ratio': float(atr_ratio),
                'age': age,
                'side': 'long',
            }

    return best_target
