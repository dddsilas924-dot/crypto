"""Bot-Alpha: 極限一撃モード - Fear < 10 でのみ発火"""
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
from src.data.database import HistoricalDB


class BotAlphaEngine:
    """極限一撃モード - Fear < 10 でのみ発火"""

    def __init__(self, config: dict, db: HistoricalDB):
        self.fear_threshold = config.get('fear_threshold', 10)
        self.btc_return_threshold = config.get('btc_return_threshold', -1.0)
        self.btc_d_drop_threshold = config.get('btc_d_drop_threshold', -0.5)
        self.correlation_max = config.get('correlation_max', 0.5)
        self.alpha_min = config.get('alpha_min', 3.0)
        self.leverage = config.get('leverage', 3)
        self.position_size_pct = config.get('position_size_pct', 30)
        self.take_profit_pct = config.get('take_profit_pct', 8.0)
        self.stop_loss_pct = config.get('stop_loss_pct', 3.0)
        self.db = db
        self.activated = False
        self.last_activation = None

    def check_activation(self, fear_greed: int, btc_daily_return: float,
                         btc_d_change: float) -> Dict:
        """三条件同時成立チェック"""
        result = {
            'activated': False,
            'fear_greed': fear_greed,
            'btc_return': btc_daily_return,
            'btc_d_change': btc_d_change,
            'conditions': {
                'fear_below_10': fear_greed < self.fear_threshold,
                'btc_negative': btc_daily_return <= self.btc_return_threshold,
                'btc_d_dropping': btc_d_change <= self.btc_d_drop_threshold,
            }
        }

        all_met = all(result['conditions'].values())
        result['activated'] = all_met
        self.activated = all_met

        if all_met:
            self.last_activation = datetime.now()

        return result

    def scan_targets(self, symbols_data: List[Dict]) -> List[Dict]:
        """低相関・高アルファ銘柄をスキャン

        symbols_data: list of {symbol, correlation, alpha, price, sector}
        """
        if not self.activated:
            return []

        targets = []
        for sd in symbols_data:
            corr = sd.get('correlation', 1.0)
            alpha = sd.get('alpha', 0.0)

            if corr < self.correlation_max and alpha >= self.alpha_min:
                score = self._calc_score(corr, alpha)
                targets.append({
                    'symbol': sd['symbol'],
                    'correlation': corr,
                    'alpha': alpha,
                    'price': sd.get('price', 0),
                    'sector': sd.get('sector', 'Unknown'),
                    'score': score,
                    'leverage': self.leverage,
                    'position_size_pct': self.position_size_pct,
                    'tp_pct': self.take_profit_pct,
                    'sl_pct': self.stop_loss_pct,
                })

        # スコア降順
        targets.sort(key=lambda x: x['score'], reverse=True)
        return targets

    def _calc_score(self, correlation: float, alpha: float) -> float:
        """Alpha銘柄スコア算出: 低相関ほど・高アルファほど高スコア"""
        corr_score = (1 - correlation) * 50  # 0~50
        alpha_score = min(alpha * 5, 50)  # 0~50
        return corr_score + alpha_score

    def generate_signal(self, activation: Dict, targets: List[Dict],
                        fear_greed: int) -> Optional[Dict]:
        """Bot-Alphaシグナル生成"""
        if not activation['activated'] or not targets:
            return None

        top = targets[0]
        return {
            'mode': 'bot_alpha',
            'label': '極限一撃モード',
            'timestamp': datetime.now().isoformat(),
            'fear_greed': fear_greed,
            'activation': activation,
            'target': top,
            'all_targets': targets[:5],  # Top 5
            'entry': {
                'symbol': top['symbol'],
                'side': 'long',
                'leverage': top['leverage'],
                'position_size_pct': top['position_size_pct'],
                'entry_price': top['price'],
                'take_profit_pct': top['tp_pct'],
                'stop_loss_pct': top['sl_pct'],
            }
        }
