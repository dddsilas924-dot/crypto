"""Bot-VolumeExhaust: 出来高枯渇反転（MA乖離大 + 出来高減少 = 売り手枯渇 → ロング）

ナレッジ: L03(出来高)逆用 + L07(MA乖離)
逆説: 全既存Botは出来高「増加」を条件にするが、下落中の出来高「減少」こそ底打ちシグナル。
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def check_signal(conn, fg: int, btc_return: float, btc_df: pd.DataFrame,
                 date_str: str, symbols: list, config: dict) -> Optional[dict]:
    fear_min = config.get('fear_min', 25)
    fear_max = config.get('fear_max', 55)
    ma20_dev_threshold = config.get('ma20_dev_threshold', -10.0)  # 下方乖離10%以上
    vol_dry_ratio = config.get('vol_dry_ratio', 0.6)  # 5日平均が20日平均の0.6倍以下
    vol_recovery_min = config.get('vol_recovery_min', 1.1)  # 直近日 > 前日の1.1倍

    if not (fear_min <= fg <= fear_max):
        return None

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    end_ts = int(dt.timestamp() * 1000)
    start_ts = end_ts - 30 * 86400000

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
        volumes = sym_df['volume'].values
        current = float(closes[-1])
        ma20 = np.mean(closes[-20:])

        if ma20 <= 0:
            continue

        # MA20下方乖離チェック
        ma20_dev = (current - ma20) / ma20 * 100
        if ma20_dev > ma20_dev_threshold:  # -10%より上なら無視
            continue

        # 出来高枯渇チェック: 5日平均 vs 20日平均
        vol_5d = np.mean(volumes[-5:])
        vol_20d = np.mean(volumes[-21:-1])
        if vol_20d <= 0:
            continue
        vol_dry = vol_5d / vol_20d
        if vol_dry > vol_dry_ratio:
            continue

        # 出来高回復の兆し: 直近日 > 前日
        if float(volumes[-2]) <= 0:
            continue
        vol_recovery = float(volumes[-1]) / float(volumes[-2])
        if vol_recovery < vol_recovery_min:
            continue

        # スコア: 乖離の大きさ × 枯渇度（逆数）× 回復度
        score = abs(ma20_dev) * (1 / max(vol_dry, 0.1)) * vol_recovery
        if score > best_score:
            best_score = score
            best_target = {
                'symbol': symbol,
                'price': current,
                'ma20_dev': float(ma20_dev),
                'vol_dry_ratio': float(vol_dry),
                'vol_recovery': float(vol_recovery),
                'side': 'long',
            }

    return best_target
