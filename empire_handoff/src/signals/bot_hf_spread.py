"""Bot-HF-Spread: 1h足ペアトレード（スプレッド収束）

相関の高い2銘柄のスプレッドが開いたら収束を狙う:
- 同セクター内で相関 > 0.8 のペアを検出
- スプレッドのZ-score > 2.0 でエントリー
- 強い方をショート + 弱い方をロング
- Z-score < 0.5 で利確

NOTE: バックテストでは弱い方のロングのみをシグナルとして返す
（ペアの同時ポジションはエンジン制約上シミュレート不可のため、
 片側のみで近似。実運用ではペアポジションを推奨）
"""
import pandas as pd
import numpy as np
from typing import Optional

# 高相関ペア候補（セクター別）
PAIR_CANDIDATES = [
    ('SOL/USDT:USDT', 'JUP/USDT:USDT'),
    ('ETH/USDT:USDT', 'ARB/USDT:USDT'),
    ('ETH/USDT:USDT', 'OP/USDT:USDT'),
    ('BNB/USDT:USDT', 'CAKE/USDT:USDT'),
    ('AVAX/USDT:USDT', 'JOE/USDT:USDT'),
    ('NEAR/USDT:USDT', 'AURORA/USDT:USDT'),
    ('SOL/USDT:USDT', 'RAY/USDT:USDT'),
    ('FET/USDT:USDT', 'RENDER/USDT:USDT'),
    ('TAO/USDT:USDT', 'RENDER/USDT:USDT'),
    ('DOGE/USDT:USDT', 'SHIB/USDT:USDT'),
    ('PEPE/USDT:USDT', 'FLOKI/USDT:USDT'),
    ('LINK/USDT:USDT', 'BAND/USDT:USDT'),
    ('ADA/USDT:USDT', 'DOT/USDT:USDT'),
    ('ATOM/USDT:USDT', 'TIA/USDT:USDT'),
    ('INJ/USDT:USDT', 'SEI/USDT:USDT'),
]


def _get_hourly_returns(conn, symbol: str, ts_ms: int, lookback_hours: int = 168) -> Optional[pd.Series]:
    """直近N時間の1h足リターン系列"""
    start_ms = ts_ms - lookback_hours * 3600 * 1000
    rows = conn.execute(
        "SELECT timestamp, close FROM ohlcv "
        "WHERE symbol=? AND timeframe='1h' AND timestamp > ? AND timestamp <= ? "
        "ORDER BY timestamp",
        (symbol, start_ms, ts_ms)
    ).fetchall()
    if len(rows) < lookback_hours // 2:
        return None
    closes = pd.Series([r[1] for r in rows])
    return closes.pct_change().dropna()


def check_signal_hf(conn, fg: int, btc_return_1h: float, btc_1h: pd.DataFrame,
                     current_ts: pd.Timestamp, symbols: list, config: dict) -> Optional[dict]:
    """ペアスプレッドシグナル"""
    z_entry = config.get('z_entry', 2.0)
    correlation_min = config.get('correlation_min', 0.6)
    lookback = config.get('spread_lookback', 168)  # 7日 = 168時間

    ts_ms = int(current_ts.timestamp() * 1000)
    best = None
    best_z = 0

    for sym_a, sym_b in PAIR_CANDIDATES:
        try:
            ret_a = _get_hourly_returns(conn, sym_a, ts_ms, lookback)
            ret_b = _get_hourly_returns(conn, sym_b, ts_ms, lookback)

            if ret_a is None or ret_b is None:
                continue

            # 長さを揃える
            min_len = min(len(ret_a), len(ret_b))
            ret_a = ret_a.iloc[-min_len:]
            ret_b = ret_b.iloc[-min_len:]

            if min_len < 48:  # 最低2日分
                continue

            # 相関チェック
            corr = ret_a.corr(ret_b)
            if corr < correlation_min:
                continue

            # スプレッド計算 (累積リターンの差)
            cum_a = (1 + ret_a).cumprod()
            cum_b = (1 + ret_b).cumprod()
            spread = cum_a.values - cum_b.values

            # Z-score
            spread_mean = np.mean(spread)
            spread_std = np.std(spread)
            if spread_std == 0:
                continue

            z_score = (spread[-1] - spread_mean) / spread_std

            if abs(z_score) > z_entry and abs(z_score) > abs(best_z):
                # A > B (z > 0): Aが上がりすぎ → Bをロング (Aショートは片側近似のため省略)
                # A < B (z < 0): Bが上がりすぎ → Aをロング
                if z_score > z_entry:
                    # sym_bが弱い → sym_bロング
                    weak_sym = sym_b
                    side = 'long'
                elif z_score < -z_entry:
                    # sym_aが弱い → sym_aロング
                    weak_sym = sym_a
                    side = 'long'
                else:
                    continue

                # 弱い方の現在価格
                price_row = conn.execute(
                    "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1h' AND timestamp=?",
                    (weak_sym, ts_ms)
                ).fetchone()
                if not price_row:
                    continue

                best_z = abs(z_score)
                best = {
                    'symbol': weak_sym, 'price': float(price_row[0]),
                    'side': side, 'z_score': round(z_score, 2),
                    'pair': f"{sym_a}/{sym_b}", 'corr': round(corr, 2),
                }

        except Exception:
            continue

    return best
