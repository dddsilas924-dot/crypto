"""L01: ドミナンス・マトリクス + Fear&Greed（キャッシュ統合）"""
import asyncio
import aiohttp
import aiohttp.resolver
from typing import Dict, Optional

def _create_session():
    connector = aiohttp.TCPConnector(resolver=aiohttp.resolver.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector)

class RegimeDetector:
    PATTERNS = {
        'A': {'btc': 'up', 'dominance': 'up', 'total': 'up', 'action': '静観（BTC独走）'},
        'B': {'btc': 'up', 'dominance': 'down', 'total': 'up', 'action': '全力買い（アルト祭）'},
        'C': {'btc': 'down', 'dominance': 'up', 'total': 'down', 'action': '全切り（全面安）'},
        'D': {'btc': 'down', 'dominance': 'down', 'total': 'flat', 'action': '先行買い（本質Alpha）'},
        'E': {'btc': 'flat', 'dominance': 'up', 'total': 'flat', 'action': '静観（じわ下げ）'},
        'F': {'btc': 'flat', 'dominance': 'down', 'total': 'flat', 'action': '短期狙い（アルト循環）'},
    }

    # 閾値: BTC/Totalは24h変化率%、BTC.Dは絶対値変化（0.3%が日次で大きな動き）
    THRESHOLD_BTC = 1.0
    THRESHOLD_TOTAL = 1.0
    THRESHOLD_DOM = 0.3  # BTC.Dは日次0.1-0.5%変動が典型

    def __init__(self, cache=None):
        self.current_pattern = 'F'  # デフォルトはレンジ判定
        self.fear_greed = 50
        self.cache = cache
        self._prev_btc_d = None  # 前回BTC.D（差分計算用）

    # データ妥当性チェック範囲
    VALID_BTC_D_MIN = 30.0   # BTC.D 30%未満は異常
    VALID_BTC_D_MAX = 80.0   # BTC.D 80%超は異常
    VALID_BTC_PRICE_MIN = 1000.0
    VALID_BTC_PRICE_MAX = 500000.0
    VALID_FG_MIN = 0
    VALID_FG_MAX = 100

    def _is_valid_btc_d(self, value: float) -> bool:
        """BTC.Dの妥当性チェック"""
        return self.VALID_BTC_D_MIN <= value <= self.VALID_BTC_D_MAX

    async def fetch_global_data(self) -> Dict:
        # メモリキャッシュチェック
        if self.cache:
            cached = self.cache.get("global_data")
            if cached is not None:
                return cached

        url = "https://api.coingecko.com/api/v3/global"
        for attempt in range(3):
            try:
                async with _create_session() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            gd = data.get('data', {})
                            btc_d_raw = gd.get('market_cap_percentage', {}).get('btc', 0)

                            # BTC.D妥当性チェック: 30-80%の範囲外なら前回値を維持
                            if self._is_valid_btc_d(btc_d_raw):
                                btc_d = btc_d_raw
                            else:
                                print(f"[Regime] BTC.D異常値検出: {btc_d_raw:.1f}%, 前回値{self._prev_btc_d}%を維持")
                                btc_d = self._prev_btc_d if self._prev_btc_d is not None else 0

                            # BTC.D変化率: 前回値との差分（初回はflatとして0）
                            if self._prev_btc_d is not None and btc_d > 0:
                                btc_d_change = btc_d - self._prev_btc_d
                            else:
                                btc_d_change = 0.0

                            # 正常値のみ prev に保存
                            if self._is_valid_btc_d(btc_d):
                                self._prev_btc_d = btc_d

                            result = {
                                'btc_dominance': btc_d,
                                'btc_d_change': btc_d_change,
                                'total_market_cap_usd': gd.get('total_market_cap', {}).get('usd', 0),
                                'market_cap_change_24h': gd.get('market_cap_change_percentage_24h_usd', 0),
                            }
                            if self.cache:
                                self.cache.set("global_data", result)
                            return result
                        elif resp.status == 429:
                            print(f"[Regime] CoinGecko rate limited, retry {attempt+1}/3...")
                            await asyncio.sleep(10 * (attempt + 1))
                            continue
            except Exception as e:
                print(f"[Regime Error] {e}")
        return {}

    async def fetch_fear_greed(self) -> int:
        # メモリキャッシュチェック
        if self.cache:
            cached = self.cache.get("fear_greed")
            if cached is not None:
                self.fear_greed = cached
                return cached

        url = "https://api.alternative.me/fng/"
        try:
            async with _create_session() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        value = int(data['data'][0]['value'])
                        self.fear_greed = value
                        if self.cache:
                            self.cache.set("fear_greed", value)
                        return value
        except Exception:
            pass
        return self.fear_greed

    def classify(self, btc_change_pct: float, dominance_change_pct: float, total_mc_change_pct: float) -> str:
        """3変数の方向からパターン判定。該当なしはF（レンジ）"""
        def direction(val, threshold):
            if val > threshold: return 'up'
            elif val < -threshold: return 'down'
            return 'flat'

        btc_dir = direction(btc_change_pct, self.THRESHOLD_BTC)
        dom_dir = direction(dominance_change_pct, self.THRESHOLD_DOM)
        total_dir = direction(total_mc_change_pct, self.THRESHOLD_TOTAL)

        for pattern, cond in self.PATTERNS.items():
            if cond['btc'] == btc_dir and cond['dominance'] == dom_dir and cond['total'] == total_dir:
                self.current_pattern = pattern
                return pattern

        # 該当なし → F（レンジ・様子見）をデフォルト
        self.current_pattern = 'F'
        return 'F'

    def get_action(self) -> str:
        return self.PATTERNS.get(self.current_pattern, {}).get('action', '判定不能')

    def should_trade(self) -> bool:
        return self.current_pattern in ['B', 'D', 'F']

    def is_emergency_exit(self) -> bool:
        return self.current_pattern == 'C'

    def is_extreme_fear(self) -> bool:
        return self.fear_greed <= 20
