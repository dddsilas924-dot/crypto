"""激アツ自動監視エンジン - Tier2通過上位銘柄の多時間足テクニカル分析"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger("empire")


@dataclass
class HotSignal:
    """激アツシグナル"""
    symbol: str
    direction: str  # 'long' or 'short'
    hot_score: int
    level: str  # '激アツ🔥🔥🔥', 'アツい🔥', '様子見👀', 'まだ早い⏳'
    entry_low: float = 0.0
    entry_high: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    sl: float = 0.0
    rr_ratio: float = 0.0
    rr_warning: bool = False
    tf_analysis: Dict = field(default_factory=dict)
    reasoning: List[str] = field(default_factory=list)
    tier2_score: float = 0.0
    sector: str = ""
    price: float = 0.0
    timestamp: str = ""


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    """RSI (Wilder method)"""
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_bb(closes: np.ndarray, period: int = 20, std_mult: float = 2.0):
    """ボリンジャーバンド (middle, upper, lower)"""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    ma = np.mean(window)
    std = np.std(window, ddof=1)
    return ma, ma + std_mult * std, ma - std_mult * std


def _calc_ema(closes: np.ndarray, period: int) -> float:
    """EMA"""
    if len(closes) < period:
        return closes[-1] if len(closes) > 0 else 0.0
    multiplier = 2 / (period + 1)
    ema = np.mean(closes[:period])
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """ATR"""
    if len(closes) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return np.mean(tr_list) if tr_list else 0.0
    atr = np.mean(tr_list[:period])
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
    return atr


def _calc_macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD (macd_line, signal_line, histogram)"""
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0

    def ema_series(data, period):
        result = [np.mean(data[:period])]
        mult = 2 / (period + 1)
        for p in data[period:]:
            result.append((p - result[-1]) * mult + result[-1])
        return np.array(result)

    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = ema_fast[-min_len:] - ema_slow[-min_len:]

    if len(macd_line) < signal:
        return macd_line[-1], 0.0, macd_line[-1]
    signal_line = ema_series(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return macd_line[-1], signal_line[-1], hist


class HotSignalMonitor:
    """激アツ自動監視エンジン"""

    def __init__(self, config: dict, fetcher, db):
        self.config = config
        self.fetcher = fetcher
        self.db = db
        self.watchlist: List[dict] = []
        self.last_watchlist_update: Optional[datetime] = None
        self.cooldown_map: Dict[str, Dict[str, datetime]] = {}  # {symbol: {level: last_time}}

        # 設定値
        self.watchlist_size = config.get('watchlist_size', 20)
        self.refresh_hours = config.get('watchlist_refresh_hours', 1)
        self.min_hot_score = config.get('min_hot_score', 60)
        self.super_hot_score = config.get('super_hot_score', 80)
        self.cooldown_super_hot = config.get('cooldown_super_hot_hours', 4)
        self.cooldown_hot = config.get('cooldown_hot_hours', 2)
        self.timeframes = config.get('timeframes', ['1h', '4h', '1d'])
        self.quiet_hours = config.get('quiet_hours', [0, 1, 2, 3, 4, 5])

        # Exit strategy
        exit_cfg = config.get('exit_strategy', {})
        self.tp1_mult = exit_cfg.get('tp1_atr_mult', 1.5)
        self.tp2_mult = exit_cfg.get('tp2_atr_mult', 2.5)
        self.tp3_mult = exit_cfg.get('tp3_atr_mult', 4.0)
        self.sl_mult = exit_cfg.get('sl_atr_mult', 1.0)
        self.min_rr = exit_cfg.get('min_rr_ratio', 1.5)

    def select_watchlist(self, tier2_results: List) -> List[dict]:
        """Tier2通過銘柄からスコア上位20銘柄を自動選定"""
        if not tier2_results:
            return []

        scored = []
        for s in tier2_results:
            total = s.tier1_score + s.tier2_score
            scored.append({
                'symbol': s.symbol,
                'tier2_score': total,
                'sector': s.sector or 'Unknown',
                'price': s.last_price,
                'tier1_details': s.tier1_details,
                'tier2_details': s.tier2_details,
            })

        scored.sort(key=lambda x: x['tier2_score'], reverse=True)

        # 上位20件 or スコア70以上、どちらか多い方
        top_n = scored[:self.watchlist_size]
        score_threshold = [s for s in scored if s['tier2_score'] >= 70]

        if len(score_threshold) > len(top_n):
            result = score_threshold
        else:
            result = top_n

        self.watchlist = result[:50]  # 安全上限
        self.last_watchlist_update = datetime.now()
        return self.watchlist

    def needs_watchlist_refresh(self) -> bool:
        """監視リスト更新が必要か"""
        if self.last_watchlist_update is None:
            return True
        elapsed = (datetime.now() - self.last_watchlist_update).total_seconds()
        return elapsed >= self.refresh_hours * 3600

    async def analyze_timeframes(self, symbol: str) -> Dict:
        """MEXC APIから1h/4h/1d足OHLCVを取得し、テクニカル分析"""
        import asyncio
        result = {}
        for tf in self.timeframes:
            try:
                ohlcv = await self.fetcher.fetch_ohlcv(symbol, tf, 50)
                if ohlcv is None or len(ohlcv) < 20:
                    result[tf] = self._empty_analysis()
                    continue
                result[tf] = self._analyze_single_tf(ohlcv)
                await asyncio.sleep(0.5)  # レート制限
            except Exception as e:
                logger.warning(f"[HotSignal] {symbol} {tf} analysis error: {e}")
                result[tf] = self._empty_analysis()
        return result

    def _empty_analysis(self) -> dict:
        return {
            'rsi': 50.0, 'rsi_state': '🟡中立',
            'bb_pos': 'inside', 'bb_upper': 0, 'bb_lower': 0, 'bb_mid': 0,
            'ema_cross': 'flat', 'ema5': 0, 'ema20': 0,
            'vol_ratio': 1.0,
            'atr_pct': 0.0, 'atr': 0.0,
            'macd_signal': 'flat',
        }

    def _analyze_single_tf(self, df: pd.DataFrame) -> dict:
        """単一時間足のテクニカル分析"""
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        price = closes[-1]

        # RSI
        rsi = _calc_rsi(closes, 14)
        if rsi < 30:
            rsi_state = '🟢売られすぎ'
        elif rsi > 70:
            rsi_state = '🔴買われすぎ'
        else:
            rsi_state = '🟡中立'

        # BB
        bb_mid, bb_upper, bb_lower = _calc_bb(closes, 20, 2.0)
        if bb_upper is None:
            bb_pos = 'N/A'
        elif price > bb_upper:
            bb_pos = '上限超え'
        elif price < bb_lower:
            bb_pos = '下限割れ'
        else:
            bb_pos = 'バンド内'

        # EMA cross
        ema5 = _calc_ema(closes, 5)
        ema20 = _calc_ema(closes, 20)
        if ema5 > ema20 * 1.001:
            ema_cross = 'GC'
        elif ema5 < ema20 * 0.999:
            ema_cross = 'DC'
        else:
            ema_cross = 'flat'

        # Volume ratio
        if len(volumes) >= 20:
            vol_avg = np.mean(volumes[-20:])
            vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
        else:
            vol_ratio = 1.0

        # ATR
        atr = _calc_atr(highs, lows, closes, 14)
        atr_pct = (atr / price * 100) if price > 0 else 0.0

        # MACD
        macd_line, signal_line, hist = _calc_macd(closes)
        if hist > 0 and macd_line > signal_line:
            macd_signal = 'bullish'
        elif hist < 0 and macd_line < signal_line:
            macd_signal = 'bearish'
        else:
            macd_signal = 'flat'

        return {
            'rsi': round(rsi, 1),
            'rsi_state': rsi_state,
            'bb_pos': bb_pos,
            'bb_upper': round(bb_upper or 0, 6),
            'bb_lower': round(bb_lower or 0, 6),
            'bb_mid': round(bb_mid or 0, 6),
            'ema_cross': ema_cross,
            'ema5': round(ema5, 6),
            'ema20': round(ema20, 6),
            'vol_ratio': round(vol_ratio, 2),
            'atr_pct': round(atr_pct, 2),
            'atr': round(atr, 6),
            'macd_signal': macd_signal,
        }

    def calculate_hot_score(self, symbol: str, tier2_score: float,
                            tf_analysis: Dict, regime: str, fear_greed: int) -> int:
        """激アツ度 0-100 を算出"""
        score = 0
        is_short_mode = fear_greed > 50  # MeanRevert/WeakShortゾーン

        # Tier2スコア加点
        if self.watchlist:
            scores = sorted([w['tier2_score'] for w in self.watchlist], reverse=True)
            rank_pct = next((i for i, s in enumerate(scores) if tier2_score >= s), len(scores))
            if rank_pct <= len(scores) * 0.1:
                score += 20
            elif rank_pct <= len(scores) * 0.2:
                score += 15

        a_1h = tf_analysis.get('1h', {})
        a_4h = tf_analysis.get('4h', {})
        a_1d = tf_analysis.get('1d', {})

        if not is_short_mode:
            # ロング候補
            if a_1h.get('rsi', 50) < 30:
                score += 15
            if a_4h.get('rsi', 50) < 35:
                score += 10
            if a_1h.get('vol_ratio', 1) >= 2.0:
                score += 15
            if a_4h.get('vol_ratio', 1) >= 1.5:
                score += 10
            if a_1h.get('ema_cross') == 'GC':
                score += 10
            if a_1h.get('bb_pos') == '下限割れ':
                score += 10
            if a_1d.get('ema_cross') == 'GC':
                score += 10
            if a_1h.get('macd_signal') == 'bullish' or a_4h.get('macd_signal') == 'bullish':
                score += 10
            # 減点
            if a_1d.get('rsi', 50) > 70:
                score -= 15
            if a_1h.get('vol_ratio', 1) < 0.5:
                score -= 10
        else:
            # ショート候補
            if a_1h.get('rsi', 50) > 70:
                score += 15
            if a_4h.get('rsi', 50) > 65:
                score += 10
            if a_1h.get('vol_ratio', 1) >= 2.0:
                score += 15
            if a_4h.get('vol_ratio', 1) >= 1.5:
                score += 10
            if a_1h.get('ema_cross') == 'DC':
                score += 10
            if a_1h.get('bb_pos') == '上限超え':
                score += 10
            if a_1d.get('ema_cross') == 'DC':
                score += 10
            if a_1h.get('macd_signal') == 'bearish' or a_4h.get('macd_signal') == 'bearish':
                score += 10
            # 減点
            if a_1d.get('rsi', 50) < 30:
                score -= 15
            if a_1h.get('vol_ratio', 1) < 0.5:
                score -= 10

        return max(0, min(100, score))

    def generate_signal(self, symbol: str, hot_score: int,
                        tf_analysis: Dict, tier2_data: dict,
                        fear_greed: int) -> Optional[HotSignal]:
        """激アツシグナル生成"""
        # レベル判定
        if hot_score >= self.super_hot_score:
            level = '激アツ🔥🔥🔥'
        elif hot_score >= self.min_hot_score:
            level = 'アツい🔥'
        elif hot_score >= 40:
            level = '様子見👀'
        else:
            level = 'まだ早い⏳'

        is_short = fear_greed > 50
        direction = 'short' if is_short else 'long'
        price = tier2_data.get('price', 0)
        if price <= 0:
            return None

        a_1h = tf_analysis.get('1h', {})
        atr = a_1h.get('atr', 0)
        bb_upper = a_1h.get('bb_upper', 0)
        bb_lower = a_1h.get('bb_lower', 0)

        # エントリーゾーン
        if direction == 'long':
            entry_low = bb_lower if bb_lower > 0 else price * 0.98
            entry_high = price
        else:
            entry_low = price
            entry_high = bb_upper if bb_upper > 0 else price * 1.02

        entry_mid = (entry_low + entry_high) / 2

        # TP/SL (ATRベース)
        if atr <= 0:
            atr = price * 0.02  # フォールバック: 価格の2%

        if direction == 'long':
            tp1 = entry_mid + self.tp1_mult * atr
            tp2 = entry_mid + self.tp2_mult * atr
            tp3 = entry_mid + self.tp3_mult * atr
            sl = entry_mid - self.sl_mult * atr
        else:
            tp1 = entry_mid - self.tp1_mult * atr
            tp2 = entry_mid - self.tp2_mult * atr
            tp3 = entry_mid - self.tp3_mult * atr
            sl = entry_mid + self.sl_mult * atr

        # RR比
        risk = abs(entry_mid - sl)
        reward = abs(tp1 - entry_mid)
        rr_ratio = reward / risk if risk > 0 else 0
        rr_warning = rr_ratio < self.min_rr

        # 根拠テキスト生成
        reasoning = self._build_reasoning(tf_analysis, direction, fear_greed, tier2_data)

        signal = HotSignal(
            symbol=symbol,
            direction=direction,
            hot_score=hot_score,
            level=level,
            entry_low=round(entry_low, 6),
            entry_high=round(entry_high, 6),
            tp1=round(tp1, 6),
            tp2=round(tp2, 6),
            tp3=round(tp3, 6),
            sl=round(sl, 6),
            rr_ratio=round(rr_ratio, 2),
            rr_warning=rr_warning,
            tf_analysis=tf_analysis,
            reasoning=reasoning,
            tier2_score=tier2_data.get('tier2_score', 0),
            sector=tier2_data.get('sector', ''),
            price=price,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        return signal

    def _build_reasoning(self, tf_analysis: Dict, direction: str,
                         fear_greed: int, tier2_data: dict) -> List[str]:
        """エントリー根拠テキスト自動生成"""
        reasons = []
        a_1h = tf_analysis.get('1h', {})
        a_4h = tf_analysis.get('4h', {})
        a_1d = tf_analysis.get('1d', {})

        reasons.append(f"Fear&Greed: {fear_greed} → {'ショート優位' if fear_greed > 50 else 'ロング優位'}環境")

        rsi_1h = a_1h.get('rsi', 50)
        if direction == 'long' and rsi_1h < 35:
            reasons.append(f"1h RSI {rsi_1h} → 売られすぎゾーン")
        elif direction == 'short' and rsi_1h > 65:
            reasons.append(f"1h RSI {rsi_1h} → 買われすぎゾーン")

        vol = a_1h.get('vol_ratio', 1)
        if vol >= 1.5:
            reasons.append(f"1h出来高 {vol:.1f}倍 → 流動性十分")

        bb = a_1h.get('bb_pos', '')
        if direction == 'long' and bb == '下限割れ':
            reasons.append("BB下限割れ → 反発期待")
        elif direction == 'short' and bb == '上限超え':
            reasons.append("BB上限超え → 反落期待")

        ema_1d = a_1d.get('ema_cross', 'flat')
        if ema_1d == 'GC':
            reasons.append("日足EMA GC → 上昇トレンド")
        elif ema_1d == 'DC':
            reasons.append("日足EMA DC → 下降トレンド")

        t2_score = tier2_data.get('tier2_score', 0)
        reasons.append(f"Tier2総合スコア: {t2_score:.0f}pt")

        return reasons[:5]

    def check_cooldown(self, symbol: str, level: str) -> bool:
        """クールダウンチェック。True=通知可能"""
        now = datetime.now()
        sym_cd = self.cooldown_map.get(symbol, {})
        last = sym_cd.get(level)
        if last is None:
            return True

        if level == '激アツ🔥🔥🔥':
            hours = self.cooldown_super_hot
        elif level == 'アツい🔥':
            hours = self.cooldown_hot
        else:
            return True

        return (now - last).total_seconds() >= hours * 3600

    def record_cooldown(self, symbol: str, level: str):
        """クールダウン記録"""
        if symbol not in self.cooldown_map:
            self.cooldown_map[symbol] = {}
        self.cooldown_map[symbol][level] = datetime.now()

    def is_quiet_hour(self) -> bool:
        """深夜通知抑制 (JST)"""
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        return now_jst.hour in self.quiet_hours

    async def run_analysis(self, tier2_passed: List, regime: str,
                           fear_greed: int) -> List[HotSignal]:
        """全監視銘柄の分析を実行し、シグナルリストを返す"""
        import asyncio
        signals = []

        # 監視リスト更新
        if self.needs_watchlist_refresh():
            self.select_watchlist(tier2_passed)

        for item in self.watchlist:
            try:
                symbol = item['symbol']
                tf_analysis = await self.analyze_timeframes(symbol)
                hot_score = self.calculate_hot_score(
                    symbol, item['tier2_score'], tf_analysis, regime, fear_greed
                )
                signal = self.generate_signal(
                    symbol, hot_score, tf_analysis, item, fear_greed
                )
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.warning(f"[HotSignal] {item['symbol']} error: {e}")

        # スコア順ソート
        signals.sort(key=lambda s: s.hot_score, reverse=True)
        return signals
