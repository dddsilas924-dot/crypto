"""VETOシステム - 3層拒否判定（L10既存 + データ異常 + 手動フラグ）"""
import yaml
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple


class VetoSystem:
    """VETO判定: 3層の拒否ロジック

    Layer 1: L10 流動性VETO（既存 - tier2_engine.py）
        - orderbook depth < $100K → score=-100 → 即除外
    Layer 2: データ異常VETO（本クラス）
        - 価格0 / 負値 / 出来高0 / OHLCVデータ欠損
    Layer 3: 手動VETO（settings.yaml）
        - veto.manual_symbols リストに含まれる銘柄を除外
    """

    def __init__(self, config: dict = None):
        config = config or {}
        veto_config = config.get('veto', {})

        # Layer 3: 手動VETOリスト
        self.manual_symbols: Set[str] = set(veto_config.get('manual_symbols', []))

        # データ異常閾値
        self.min_price = veto_config.get('min_price', 0.0)
        self.min_volume_usd = veto_config.get('min_volume_usd', 0.0)
        self.max_spread_pct = veto_config.get('max_spread_pct', 10.0)

        # VETO履歴（デバッグ用）
        self.veto_log: List[Dict] = []

    def check(self, symbol: str, price: float = 0, volume_usd: float = 0,
              ohlcv_available: bool = True, spread_pct: float = 0,
              extra_checks: Dict = None) -> Tuple[bool, Optional[str]]:
        """VETO判定

        Returns:
            (is_vetoed: bool, reason: Optional[str])
            - True, "reason" = VETOされた
            - False, None = 通過
        """
        # Layer 3: 手動VETO（最優先）
        if symbol in self.manual_symbols:
            reason = f'手動VETO: {symbol}はsettings.yaml veto.manual_symbolsに登録済み'
            self._log(symbol, reason)
            return True, reason

        # Layer 2: データ異常VETO
        if price <= self.min_price:
            reason = f'データ異常: 価格={price} (≤{self.min_price})'
            self._log(symbol, reason)
            return True, reason

        if price < 0:
            reason = f'データ異常: 負の価格={price}'
            self._log(symbol, reason)
            return True, reason

        if volume_usd <= self.min_volume_usd:
            reason = f'データ異常: 出来高=${volume_usd:,.0f} (≤${self.min_volume_usd:,.0f})'
            self._log(symbol, reason)
            return True, reason

        if not ohlcv_available:
            reason = 'データ異常: OHLCVデータ欠損'
            self._log(symbol, reason)
            return True, reason

        if spread_pct > self.max_spread_pct:
            reason = f'データ異常: スプレッド={spread_pct:.1f}% (>{self.max_spread_pct}%)'
            self._log(symbol, reason)
            return True, reason

        # Layer 1: L10 流動性VETO は tier2_engine.py で既存実装済み
        # ここでは重複実装しない（tier2_engine.py L10: depth<$100K → -100）

        # 追加チェック（拡張用）
        if extra_checks:
            for check_name, (value, threshold, op) in extra_checks.items():
                if op == 'lt' and value < threshold:
                    reason = f'{check_name}: {value} < {threshold}'
                    self._log(symbol, reason)
                    return True, reason
                elif op == 'gt' and value > threshold:
                    reason = f'{check_name}: {value} > {threshold}'
                    self._log(symbol, reason)
                    return True, reason

        return False, None

    def is_manual_vetoed(self, symbol: str) -> bool:
        """手動VETOリストに含まれるか"""
        return symbol in self.manual_symbols

    def add_manual_veto(self, symbol: str):
        """手動VETOに追加"""
        self.manual_symbols.add(symbol)

    def remove_manual_veto(self, symbol: str):
        """手動VETOから削除"""
        self.manual_symbols.discard(symbol)

    def get_manual_list(self) -> List[str]:
        """手動VETOリスト取得"""
        return sorted(self.manual_symbols)

    def _log(self, symbol: str, reason: str):
        """VETO履歴に記録"""
        self.veto_log.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'reason': reason,
        })
        # 最新1000件保持
        if len(self.veto_log) > 1000:
            self.veto_log = self.veto_log[-500:]

    def get_recent_vetos(self, limit: int = 50) -> List[Dict]:
        """直近のVETO履歴"""
        return self.veto_log[-limit:]

    def get_veto_stats(self) -> Dict:
        """VETO統計"""
        if not self.veto_log:
            return {'total': 0, 'by_reason': {}}

        by_reason = {}
        for entry in self.veto_log:
            # 理由の先頭部分でグルーピング
            reason_key = entry['reason'].split(':')[0]
            by_reason[reason_key] = by_reason.get(reason_key, 0) + 1

        return {
            'total': len(self.veto_log),
            'by_reason': by_reason,
            'manual_count': len(self.manual_symbols),
        }
