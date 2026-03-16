"""Bot-Surge: 日常循環モード - 乖離・セクター波及を常時監視"""
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from src.data.database import HistoricalDB


# セクター波及テーブル（alpha_logic.txt実証データ）
DEFAULT_SECTOR_LAG = {
    'Solana': {
        'leader': 'SOL/USDT:USDT',
        'followers': {
            'JUP/USDT:USDT': 2.0,
            'JTO/USDT:USDT': 4.75,
        }
    },
    'AI': {
        'leader': 'TAO/USDT:USDT',
        'followers': {
            'FIL/USDT:USDT': 1.75,
            'AR/USDT:USDT': 2.0,
        }
    },
    'BTCeco': {
        'leader': 'PUPS/USDT:USDT',
        'followers': {
            'ORDI/USDT:USDT': 0.75,
            'DOG/USDT:USDT': 1.0,
        }
    },
    'DeFi': {
        'leader': 'ONDO/USDT:USDT',
        'followers': {
            'OM/USDT:USDT': 3.0,
        }
    },
    'Gaming': {
        'leader': 'FLOKI/USDT:USDT',
        'followers': {
            'PENGU/USDT:USDT': 1.0,
        }
    },
}


class BotSurgeEngine:
    """日常循環モード - 乖離・セクター波及を常時監視"""

    def __init__(self, config: dict, db: HistoricalDB):
        self.fear_min = config.get('fear_min', 25)
        self.fear_max = config.get('fear_max', 45)
        self.divergence_threshold = config.get('divergence_threshold', 3.0)
        self.rsi_min = config.get('rsi_min', 50)
        self.leverage = config.get('leverage', 2)
        self.position_size_pct = config.get('position_size_pct', 20)
        self.take_profit_pct = config.get('take_profit_pct', 5.0)
        self.stop_loss_pct = config.get('stop_loss_pct', 2.0)
        self.db = db
        self.activated = False
        self.sector_lag = self._load_sector_lag(config)
        # リーダー乖離イベント記録: {leader_symbol: (timestamp, divergence_pct)}
        self.leader_events: Dict[str, tuple] = {}

    def _load_sector_lag(self, config: dict) -> dict:
        """settings.yamlのsector_lagをマージ"""
        lag = dict(DEFAULT_SECTOR_LAG)
        yaml_lag = config.get('sector_lag', {})
        for sector_key, data in yaml_lag.items():
            leader = data.get('leader', '')
            followers = data.get('followers', {})
            if leader and followers:
                leader_sym = f"{leader}/USDT:USDT"
                follower_map = {f"{k}/USDT:USDT": v for k, v in followers.items()}
                # 既存セクターにマージ or 新規追加
                found = False
                for sec_name, sec_data in lag.items():
                    if sec_data['leader'] == leader_sym:
                        sec_data['followers'].update(follower_map)
                        found = True
                        break
                if not found:
                    lag[sector_key] = {'leader': leader_sym, 'followers': follower_map}
        return lag

    def check_activation(self, fear_greed: int, btc_daily_return: float) -> Dict:
        """発動条件チェック: Fear 25-45 & BTC ≤ 0%"""
        result = {
            'activated': False,
            'fear_greed': fear_greed,
            'btc_return': btc_daily_return,
            'conditions': {
                'fear_in_range': self.fear_min <= fear_greed <= self.fear_max,
                'btc_non_positive': btc_daily_return <= 0,
            }
        }

        all_met = all(result['conditions'].values())
        result['activated'] = all_met
        self.activated = all_met
        return result

    def detect_divergence(self, symbols_data: List[Dict]) -> List[Dict]:
        """BTC乖離 > 3% の銘柄を検出し、リーダー銘柄をイベント記録"""
        if not self.activated:
            return []

        divergent = []
        now = datetime.now()

        for sd in symbols_data:
            symbol = sd['symbol']
            btc_divergence = sd.get('btc_divergence', 0.0)  # 対BTC騰落率差

            if abs(btc_divergence) > self.divergence_threshold:
                divergent.append({
                    'symbol': symbol,
                    'btc_divergence': btc_divergence,
                    'price': sd.get('price', 0),
                    'sector': sd.get('sector', 'Unknown'),
                    'rsi': sd.get('rsi', 0),
                })

                # リーダー銘柄のイベント記録
                for sec_name, sec_data in self.sector_lag.items():
                    if symbol == sec_data['leader']:
                        self.leader_events[symbol] = (now, btc_divergence)

        return divergent

    def check_sector_cascade(self) -> List[Dict]:
        """セクター波及チェック: リーダー乖離からラグ日数経過のフォロワーを抽出"""
        if not self.activated:
            return []

        cascades = []
        now = datetime.now()

        for sec_name, sec_data in self.sector_lag.items():
            leader = sec_data['leader']
            if leader not in self.leader_events:
                continue

            event_time, divergence = self.leader_events[leader]

            for follower, lag_days in sec_data['followers'].items():
                elapsed = (now - event_time).total_seconds() / 86400
                # ラグ日数の80%~120%範囲でシグナル
                if lag_days * 0.8 <= elapsed <= lag_days * 1.2:
                    cascades.append({
                        'sector': sec_name,
                        'leader': leader,
                        'leader_divergence': divergence,
                        'follower': follower,
                        'lag_days': lag_days,
                        'elapsed_days': round(elapsed, 1),
                        'leverage': self.leverage,
                        'position_size_pct': self.position_size_pct,
                        'tp_pct': self.take_profit_pct,
                        'sl_pct': self.stop_loss_pct,
                    })

        return cascades

    def generate_signal(self, activation: Dict, divergent: List[Dict],
                        cascades: List[Dict], fear_greed: int) -> Optional[Dict]:
        """Bot-Surgeシグナル生成"""
        if not activation['activated']:
            return None
        if not divergent and not cascades:
            return None

        signal = {
            'mode': 'bot_surge',
            'label': '日常循環モード',
            'timestamp': datetime.now().isoformat(),
            'fear_greed': fear_greed,
            'activation': activation,
            'divergent_symbols': divergent[:10],
            'sector_cascades': cascades,
        }

        # カスケードがあれば最優先エントリー
        if cascades:
            top = cascades[0]
            signal['entry'] = {
                'symbol': top['follower'],
                'side': 'long',
                'leverage': top['leverage'],
                'position_size_pct': top['position_size_pct'],
                'take_profit_pct': top['tp_pct'],
                'stop_loss_pct': top['sl_pct'],
                'reason': f"セクター波及: {top['leader']}→{top['follower']} (lag {top['lag_days']}d)",
            }
        elif divergent:
            # RSI > 50 フィルタ
            filtered = [d for d in divergent if d.get('rsi', 0) > self.rsi_min]
            if filtered:
                top = max(filtered, key=lambda x: abs(x['btc_divergence']))
                signal['entry'] = {
                    'symbol': top['symbol'],
                    'side': 'long' if top['btc_divergence'] > 0 else 'short',
                    'leverage': self.leverage,
                    'position_size_pct': self.position_size_pct,
                    'take_profit_pct': self.take_profit_pct,
                    'stop_loss_pct': self.stop_loss_pct,
                    'reason': f"BTC乖離: {top['btc_divergence']:+.1f}%",
                }

        return signal if 'entry' in signal else None
