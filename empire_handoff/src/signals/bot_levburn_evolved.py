"""Bot-LevBurn-Evolved: levburn_sec_agg_7x_fr に追加ロジックを組み合わせた進化版

追加候補:
  oi_classify   : OI方向分類 (価格×OI変化で清算前/後を識別)
  slip_filter   : 銘柄別滑りやすさ係数 (スプレッド/板厚プロキシ)
  weakshort_mix : WeakShort思想統合 (弱いのにロング積まれてるアルト検出)
  multi_confirm : 過熱多重確認 (FR+RSI+出来高+現物乖離)
  meta_variant  : 市場状態でvariant自動切替

config.evolve_features = ['oi_classify', 'slip_filter', ...] で組み合わせ指定
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional


def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    diffs = np.diff(closes[-(period+1):])
    gains = np.where(diffs > 0, diffs, 0)
    losses = np.where(diffs < 0, -diffs, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))


def _calc_slippage_score(df):
    """滑りやすさ係数: スプレッドプロキシ(HL幅/Close) × 出来高逆数"""
    if len(df) < 5:
        return 1.0
    recent = df.iloc[-5:]
    avg_spread = float(np.mean((recent['high'] - recent['low']) / recent['close'] * 100))
    avg_vol = float(np.mean(recent['volume']))
    # 高スプレッド + 低出来高 = 滑りやすい (スコア高い = 悪い)
    if avg_vol <= 0:
        return 10.0
    vol_score = min(avg_vol / 1e8, 10.0)  # 出来高正規化
    slip = avg_spread / max(vol_score, 0.01)
    return float(min(slip, 10.0))


def _classify_oi_direction(df, i):
    """OI方向分類: 価格変化 × 出来高変化（OIプロキシ）で4パターン判定
    Returns: (pattern, confidence)
      'new_long_accumulation' : 価格↑ + OI(vol)↑ → 新規ロング蓄積（焼かれる前）
      'short_covering'        : 価格↑ + OI(vol)↓ → ショートカバー（焼かれた後）
      'new_short_accumulation': 価格↓ + OI(vol)↑ → 新規ショート蓄積（焼かれる前）
      'long_liquidation'      : 価格↓ + OI(vol)↓ → ロング投げ（焼かれた後）
    """
    if i < 3:
        return 'unknown', 0.0

    price_change = (float(df.iloc[i]['close']) - float(df.iloc[i-1]['close'])) / float(df.iloc[i-1]['close'])
    vol_now = float(df.iloc[i]['volume'])
    vol_prev = float(df.iloc[i-1]['volume'])
    vol_change = (vol_now - vol_prev) / vol_prev if vol_prev > 0 else 0

    # 3日トレンドも加味
    price_3d = (float(df.iloc[i]['close']) - float(df.iloc[i-3]['close'])) / float(df.iloc[i-3]['close'])

    confidence = min(abs(price_change) * 100 + abs(vol_change) * 50, 100) / 100

    if price_change > 0 and vol_change > 0:
        return 'new_long_accumulation', confidence  # 焼かれる前
    elif price_change > 0 and vol_change <= 0:
        return 'short_covering', confidence  # 焼かれた後
    elif price_change <= 0 and vol_change > 0:
        return 'new_short_accumulation', confidence  # 焼かれる前
    else:
        return 'long_liquidation', confidence  # 焼かれた後


def _is_weak_alt_with_longs(df, i, btc_return):
    """WeakShort思想: BTCが横ばい〜強いのに弱いアルトを検出
    + 出来高増（=ロングが積まれている）"""
    if i < 7:
        return False, 0
    closes = df['close'].values
    volumes = df['volume'].values

    sym_ret_7d = (float(closes[i]) - float(closes[i-7])) / float(closes[i-7]) * 100
    sym_ret_1d = (float(closes[i]) - float(closes[i-1])) / float(closes[i-1]) * 100
    vol_recent = float(np.mean(volumes[i-3:i+1]))
    vol_old = float(np.mean(volumes[max(0,i-7):i-3])) if i > 6 else vol_recent

    # BTCが横ばい以上なのにアルトが弱い
    btc_ok = btc_return > -1.0
    alt_weak = sym_ret_7d < 0 and sym_ret_1d < btc_return
    vol_increasing = vol_recent > vol_old * 1.2 if vol_old > 0 else False

    score = 0
    if btc_ok and alt_weak:
        score += 30
    if vol_increasing:
        score += 20
    if sym_ret_7d < -5:
        score += 10

    return score >= 30, score


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    """進化版LevBurnシグナル"""
    features = config.get('evolve_features', [])
    fr_threshold = config.get('fr_threshold', 0.3)
    vol_threshold = config.get('vol_threshold', 3.0)
    slip_max = config.get('slip_max', 3.0)  # 滑りやすさ上限

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    ts = int(dt.timestamp() * 1000)
    start_ts = ts - 25 * 86400000

    best_candidate = None
    best_score = -1

    for symbol in symbols[:200]:
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, ts)
        )
        if len(df) < 20:
            continue

        i = len(df) - 1
        closes = df['close'].values
        volumes = df['volume'].values

        # === 基本FR推定（既存ロジック） ===
        consecutive_up = sum(1 for j in range(1, 4) if i-j >= 0 and df.iloc[i-j]['close'] > df.iloc[i-j]['open'])
        consecutive_down = sum(1 for j in range(1, 4) if i-j >= 0 and df.iloc[i-j]['close'] <= df.iloc[i-j]['open'])

        vol_start = max(0, i - 20)
        vol_window = df.iloc[vol_start:i]['volume']
        vol_mean = vol_window.mean() if len(vol_window) > 0 else 1.0
        vol_ratio = float(df.iloc[i]['volume']) / vol_mean if vol_mean > 0 else 1.0

        close_p = float(df.iloc[i]['close'])
        open_p = float(df.iloc[i]['open'])
        daily_change = (close_p - open_p) / open_p * 100 if open_p > 0 else 0

        fr_proxy = 0.0
        if consecutive_up >= 3 and vol_ratio > 2:
            fr_proxy = daily_change * 0.3
        elif consecutive_down >= 3 and vol_ratio > 2:
            fr_proxy = daily_change * 0.3
        elif vol_ratio > 3:
            fr_proxy = daily_change * 0.2
        else:
            fr_proxy = daily_change * 0.1

        # 実FR取得
        real_fr = None
        fr_row = conn.execute(
            "SELECT funding_rate FROM funding_rate_history WHERE symbol=? AND timestamp LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (symbol, f"{date_str}%")
        ).fetchone()
        if fr_row:
            real_fr = fr_row[0]

        fr = real_fr * 100 if real_fr is not None else fr_proxy

        if abs(fr) < fr_threshold:
            continue
        if vol_ratio < vol_threshold:
            continue

        # 基本スコア
        score = abs(fr) * 30 + min(vol_ratio / 5, 1.0) * 20
        side = 'short' if fr > 0 else 'long'

        # === FR方向フィルター（base 7x_fr と同じ） ===
        if real_fr is not None:
            if real_fr > 0 and side == 'long':
                continue
            elif real_fr < 0 and side == 'short':
                continue
        elif abs(fr) < 0.5:
            continue

        # === 追加候補1: OI方向分類 ===
        if 'oi_classify' in features:
            pattern, oi_conf = _classify_oi_direction(df, i)
            # 「焼かれる前」のみエントリー（焼かれた後は残り火でリスク高い）
            if side == 'short' and pattern == 'new_long_accumulation':
                score += 15 * oi_conf  # 新規ロング蓄積 → SHORT好機
            elif side == 'long' and pattern == 'new_short_accumulation':
                score += 15 * oi_conf  # 新規ショート蓄積 → LONG好機
            elif pattern in ('short_covering', 'long_liquidation'):
                score -= 10  # 焼かれた後 → 減点
                if config.get('oi_strict', False):
                    continue  # strict mode: 焼かれた後は完全スキップ

        # === 追加候補3: 滑りやすさ係数 ===
        if 'slip_filter' in features:
            slip = _calc_slippage_score(df)
            if slip > slip_max:
                continue  # 滑りやすい銘柄を除外
            score -= slip * 3  # 滑りやすさで減点

        # === 追加候補5: WeakShort統合 ===
        if 'weakshort_mix' in features and side == 'short':
            is_weak, ws_score = _is_weak_alt_with_longs(df, i, btc_return)
            if is_weak:
                score += ws_score * 0.5  # WeakShort条件一致でブースト

        # === 追加候補6: 過熱多重確認 ===
        if 'multi_confirm' in features:
            rsi = _calc_rsi(closes)
            confirmations = 0
            if side == 'short':
                if rsi > 70: confirmations += 1
                if vol_ratio > 2.0: confirmations += 1
                if daily_change > 3.0: confirmations += 1
                if abs(fr) > 0.5: confirmations += 1
            elif side == 'long':
                if rsi < 30: confirmations += 1
                if vol_ratio > 2.0: confirmations += 1
                if daily_change < -3.0: confirmations += 1
                if abs(fr) > 0.5: confirmations += 1

            min_confirmations = config.get('min_confirmations', 2)
            if confirmations < min_confirmations:
                continue  # 確認不足 → スキップ
            score += confirmations * 5

        # === 追加候補4: メタvariant切替 ===
        if 'meta_variant' in features:
            if abs(fr) > 1.0:
                # FR極端 → TP/SL拡大（大きく動く前提）
                config['_meta_tp_mult'] = 1.5
                config['_meta_sl_mult'] = 1.2
            elif vol_ratio < 1.5:
                # ボラ小 → Conservative寄り
                config['_meta_tp_mult'] = 0.7
                config['_meta_sl_mult'] = 0.7
            else:
                config['_meta_tp_mult'] = 1.0
                config['_meta_sl_mult'] = 1.0

        if score > best_score:
            best_score = score
            best_candidate = {
                'symbol': symbol,
                'side': side,
                'price': close_p,
                'fr_value': fr,
                'fr_for_check': fr,
                'vol_ratio': vol_ratio,
                'score': score,
            }

    return best_candidate
