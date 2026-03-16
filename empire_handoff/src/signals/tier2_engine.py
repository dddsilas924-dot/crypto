"""Tier 2: 需給・健全性検証（L08, L10, L13）"""
from typing import Dict
from src.core.state import SymbolState

class Tier2Engine:
    def __init__(self, config: dict):
        self.min_depth = config.get('min_orderbook_depth_usd', 100000)
        self.fr_extreme = config.get('funding_rate_extreme', 0.05)

    def l08_fr_oi(self, state: SymbolState) -> Dict:
        result = {'passed': True, 'score': 0, 'reason': '', 'signal': 'neutral'}
        fr = state.funding_rate
        if fr is None:
            result['reason'] = 'FR取得不可'
            return result

        if fr < -0.01:
            result['signal'] = 'short_squeeze'
            result['score'] = 20
            result['reason'] = f'踏み上げ兆候: FR={fr:.4f}'
        elif fr > self.fr_extreme:
            result['signal'] = 'overheated'
            result['score'] = -10
            result['reason'] = f'過熱警告: FR={fr:.4f}'
        else:
            result['reason'] = f'FR正常: {fr:.4f}'
        return result

    def l10_liquidity_health(self, state: SymbolState) -> Dict:
        result = {'passed': True, 'score': 0, 'reason': '', 'veto': False}
        depth = state.orderbook_depth_usd
        if depth < self.min_depth:
            result['passed'] = False
            result['veto'] = True
            result['score'] = -100
            result['reason'] = f'VETO: 板厚${depth:,.0f} < ${self.min_depth:,.0f}'
        else:
            result['score'] = min(depth / self.min_depth * 10, 20)
            result['reason'] = f'板厚OK: ${depth:,.0f}'
        return result

    def l13_lcef(self, state: SymbolState) -> Dict:
        result = {'passed': True, 'score': 0, 'reason': ''}
        if state.funding_rate and state.funding_rate < -0.02 and state.open_interest > 0:
            result['score'] = -15
            result['reason'] = '清算リスク警告: 高OI+極端FR'
        else:
            result['score'] = 5
            result['reason'] = '清算リスク低'
        return result

    def run(self, state: SymbolState) -> Dict:
        results = {
            'L08': self.l08_fr_oi(state),
            'L10': self.l10_liquidity_health(state),
            'L13': self.l13_lcef(state),
        }
        if results['L10'].get('veto'):
            state.tier2_passed = False
            state.tier2_score = -100
            return results

        total_score = sum(r['score'] for r in results.values())
        state.tier2_score = total_score
        state.tier2_passed = total_score > 10
        state.tier2_details = results
        return results
