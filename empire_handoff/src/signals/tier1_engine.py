"""Tier 1: 全銘柄軽量スクリーニング（L02, L03, L04, L09, L17 + Alpha乖離）"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from src.core.state import SymbolState

class Tier1Engine:
    def __init__(self, config: dict):
        self.volume_spike_ratio = config.get('volume_spike_ratio', 2.0)
        self.volatility_threshold = config.get('volatility_threshold', 5.0)
        self.correlation_threshold = config.get('correlation_threshold', 0.5)
        self.alpha_threshold = config.get('alpha_threshold', 3.0)

    def calculate_indicators(self, state: SymbolState) -> None:
        df = state.ohlcv_1d
        if df is None or len(df) < 200:
            if df is not None and len(df) >= 5:
                close = df['close']
                state.sma_5 = close.rolling(5).mean().iloc[-1]
                state.last_price = close.iloc[-1]
            return

        close = df['close']
        volume = df['volume']
        state.sma_5 = close.rolling(5).mean().iloc[-1]
        state.sma_200 = close.rolling(200).mean().iloc[-1]
        state.last_price = close.iloc[-1]
        state.volume_sma_20 = volume.rolling(20).mean().iloc[-1]

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 0
        state.rsi_14 = 100 - (100 / (1 + rs))

    def l02_alpha_sanctuary(self, state: SymbolState, sanctuary_price: Optional[float] = None) -> Dict:
        result = {'passed': True, 'score': 0, 'reason': ''}
        if sanctuary_price is None:
            if state.ohlcv_1d is not None and len(state.ohlcv_1d) >= 200:
                sanctuary_price = state.ohlcv_1d['low'].tail(200).min()
            else:
                # 聖域未設定: バイパス（新規上場銘柄等）
                result['score'] = 5
                result['reason'] = '聖域未設定（バイパス）'
                return result

        if state.last_price <= sanctuary_price:
            result['passed'] = False
            result['score'] = -100
            result['reason'] = f'聖域割れ: {state.last_price} <= {sanctuary_price}'
        else:
            dist_pct = (state.last_price - sanctuary_price) / sanctuary_price * 100
            result['score'] = min(dist_pct * 2, 30)
            result['reason'] = f'聖域乖離: +{dist_pct:.1f}%'
        return result

    def l03_inflow(self, state: SymbolState) -> Dict:
        result = {'passed': False, 'score': 0, 'reason': ''}
        if state.ohlcv_1m is None or len(state.ohlcv_1m) < 20:
            result['reason'] = 'データ不足'
            return result

        current_vol = state.ohlcv_1m['volume'].iloc[-1]
        avg_vol = state.ohlcv_1m['volume'].tail(20).mean()
        if avg_vol == 0:
            result['reason'] = '出来高ゼロ'
            return result

        ratio = current_vol / avg_vol
        if ratio >= self.volume_spike_ratio:
            result['passed'] = True
            result['score'] = min(ratio * 10, 25)
            result['reason'] = f'出来高スパイク: {ratio:.1f}倍'
        else:
            result['reason'] = f'出来高通常: {ratio:.1f}倍'
        return result

    def l09_immediate_entry(self, state: SymbolState) -> Dict:
        result = {'passed': False, 'score': 0, 'reason': '', 'urgent': False}
        if state.ohlcv_1m is None or len(state.ohlcv_1m) < 5:
            result['reason'] = 'データ不足'
            return result

        recent = state.ohlcv_1m.tail(5)
        price_change = (recent['close'].iloc[-1] - recent['open'].iloc[0]) / recent['open'].iloc[0] * 100
        if abs(price_change) >= self.volatility_threshold:
            result['passed'] = True
            result['urgent'] = True
            result['score'] = min(abs(price_change) * 3, 20)
            direction = '急騰' if price_change > 0 else '急落'
            result['reason'] = f'{direction}: {price_change:+.1f}%（5分間）'
        return result

    def l17_correlation_shift(self, state: SymbolState) -> Dict:
        result = {'passed': False, 'score': 0, 'reason': ''}
        if state.btc_correlation < self.correlation_threshold:
            result['passed'] = True
            result['score'] = (1 - state.btc_correlation) * 25
            result['reason'] = f'BTC非相関: {state.btc_correlation:.2f}'
        else:
            result['reason'] = f'BTC相関: {state.btc_correlation:.2f}'
        return result

    def l_alpha_divergence(self, state: SymbolState) -> Dict:
        """Alpha乖離検知: 相関<0.5 & アルファ>3%"""
        result = {'passed': False, 'score': 0, 'reason': ''}
        if (state.btc_correlation < self.correlation_threshold and
            state.btc_alpha >= self.alpha_threshold):
            result['passed'] = True
            result['score'] = min(state.btc_alpha * 5, 30)
            result['reason'] = f'Alpha乖離: corr={state.btc_correlation:.2f}, α={state.btc_alpha:+.1f}%'
        else:
            result['reason'] = f'Alpha条件未達: corr={state.btc_correlation:.2f}, α={state.btc_alpha:+.1f}%'
        return result

    def run(self, state: SymbolState) -> Dict:
        self.calculate_indicators(state)
        results = {
            'L02': self.l02_alpha_sanctuary(state),
            'L03': self.l03_inflow(state),
            'L09': self.l09_immediate_entry(state),
            'L17': self.l17_correlation_shift(state),
            'L_alpha': self.l_alpha_divergence(state),
        }

        if not results['L02']['passed']:
            state.tier1_passed = False
            state.tier1_score = -100
            return results

        total_score = sum(r['score'] for r in results.values())
        state.tier1_score = total_score
        state.tier1_passed = total_score > 20
        state.tier1_details = results
        return results
