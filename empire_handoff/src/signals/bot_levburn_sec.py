"""Bot-LevBurn-Sec: FR偏り + 1秒足リアルタイムスキャルピング

戦略:
1. FR偏りで方向を決定（LevBurnと同じ）
2. WebSocketの1秒足・約定・板で「焼きの初動」を検知
3. 初動に乗って短期利確（TP +0.5〜3%, SL -0.2〜1%）
"""

import time
import logging
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

logger = logging.getLogger("empire")


@dataclass
class SecSignal:
    symbol: str
    direction: str          # LONG / SHORT
    entry_price: float
    tp_price: float
    sl_price: float
    tp_pct: float
    sl_pct: float
    leverage: int
    position_pct: float
    burn_score: int         # FRスコア（0-50）
    trigger_score: int      # リアルタイムトリガースコア（0-70）
    combined_score: int     # 合計スコア
    reasons: list = field(default_factory=list)
    fr_value: float = 0.0
    price_change_1s: float = 0.0
    price_change_5s: float = 0.0
    volume_ratio: float = 0.0
    buy_sell_ratio: float = 0.5
    max_hold_seconds: int = 1800
    variant: str = "standard"
    timestamp: str = ""


# トリガー閾値
TRIGGERS = {
    "price_1s_threshold": 0.3,
    "price_5s_threshold": 0.8,
    "price_10s_threshold": 1.5,
    "volume_ratio_min": 3.0,
    "volume_spike_ratio": 5.0,
    "buy_ratio_long": 0.7,
    "buy_ratio_short": 0.3,
    "buy_ratio_extreme": 0.85,
    "book_imbalance_threshold": 3.0,
    "fr_min": 0.0005,       # 0.05% (MEXC WS raw decimal)
    "fr_strong": 0.0015,    # 0.15%
    "fr_extreme": 0.003,    # 0.3%
}

# バリエーション定義
VARIANTS = {
    "standard": {
        "tp_pct": 1.5,
        "sl_pct": 0.5,
        "leverage": 10,
        "position_pct": 2,
        "max_hold_seconds": 1800,
        "min_trigger_score": 60,
        "price_threshold_mult": 1.0,
    },
    "aggressive": {
        "tp_pct": 3.0,
        "sl_pct": 1.0,
        "leverage": 15,
        "position_pct": 1,
        "max_hold_seconds": 900,
        "min_trigger_score": 50,
        "price_threshold_mult": 0.7,
    },
    "conservative": {
        "tp_pct": 1.0,
        "sl_pct": 0.3,
        "leverage": 7,
        "position_pct": 2,
        "max_hold_seconds": 600,
        "min_trigger_score": 75,
        "price_threshold_mult": 1.3,
    },
    "scalp_micro": {
        "tp_pct": 0.5,
        "sl_pct": 0.2,
        "leverage": 20,
        "position_pct": 1,
        "max_hold_seconds": 300,
        "min_trigger_score": 70,
        "price_threshold_mult": 0.5,
    },
    "fr_extreme_only": {
        "tp_pct": 2.0,
        "sl_pct": 0.8,
        "leverage": 10,
        "position_pct": 3,
        "max_hold_seconds": 1800,
        "min_trigger_score": 60,
        "price_threshold_mult": 1.0,
        "fr_min_override": 0.002,  # 0.2% (raw decimal)
    },
}


class LevBurnSecEngine:
    """1秒足リアルタイムスキャルピングエンジン"""

    def __init__(self, ws_feed, fr_collector=None, variant: str = "standard",
                 config: dict = None):
        self.ws_feed = ws_feed
        self.fr_collector = fr_collector
        # VARIANTS をデフォルトにし、config で上書き
        # _lev1/_lev3 等のサフィックス付きバリアントはベース名でVARIANTS参照
        base_variant = variant.replace("_lev1", "").replace("_lev3", "")
        defaults = VARIANTS.get(variant, VARIANTS.get(base_variant, VARIANTS["standard"])).copy()
        if config:
            for key in defaults:
                if key in config:
                    defaults[key] = config[key]
            # config独自キー（fr_min_override等）も取り込む
            for key in config:
                if key not in defaults and key not in ("variant", "mode"):
                    defaults[key] = config[key]
        self.variant = defaults
        self.variant_name = variant
        self._cooldowns = {}
        self._stats = {
            "scans": 0,
            "triggers_detected": 0,
            "signals_generated": 0,
            "signals_filtered": 0,
        }

    def scan(self, fr_data: dict, regime: dict = None) -> List[SecSignal]:
        """
        メインスキャン: FR偏り銘柄に対して1秒足トリガーを判定

        fr_data: {symbol: {funding_rate, ...}}
        regime: {fear_greed, ...}
        """
        self._stats["scans"] += 1
        regime = regime or {}
        signals = []

        for symbol, fr in fr_data.items():
            if self._is_cooldown(symbol):
                continue

            fr_score, direction = self._evaluate_fr(fr, regime)
            if fr_score == 0:
                continue

            trigger_score, reasons = self._evaluate_realtime(symbol, direction)

            if trigger_score < self.variant["min_trigger_score"]:
                self._stats["signals_filtered"] += 1
                continue

            combined = min(100, fr_score + trigger_score)
            signal = self._create_signal(
                symbol, direction, fr, combined,
                fr_score, trigger_score, reasons,
            )

            if signal:
                # === Evolved追加フィルター ===
                if self.variant.get("evolve_all", False):
                    filtered = self._evolved_filter(signal, symbol, fr, direction, regime)
                    if filtered is None:
                        self._stats["signals_filtered"] += 1
                        continue
                    signal = filtered

                signals.append(signal)
                self._set_cooldown(symbol, 60)
                self._stats["signals_generated"] += 1
                self._stats["triggers_detected"] += 1

        return signals

    def _evolved_filter(self, signal, symbol, fr_data, direction, regime):
        """Evolved全部盛りフィルター — リアルタイム1秒足データで判定

        追加候補1: OI方向分類 (価格×出来高変化で清算前/後を識別)
        追加候補2: 板消失速度 (上位板のキャンセル検出)
        追加候補3: 滑りやすさ係数 (スプレッド/板厚)
        追加候補4: メタvariant (FR極端度で動的調整)
        追加候補5: WeakShort統合 (BTC比で弱い+ロング蓄積)
        追加候補6: 過熱多重確認 (FR+vol+約定偏り+板)
        """
        candles = self.ws_feed.get_1s_candles(symbol, 120)
        orderbook = self.ws_feed.get_orderbook(symbol)
        trades = self.ws_feed.get_recent_trades(symbol, 500)

        if len(candles) < 30:
            return signal  # データ不足時はそのまま通す

        score_adjust = 0
        notes = []

        # --- 追加候補1: OI方向分類 (出来高変化をOIプロキシ) ---
        vol_recent_30s = sum(c.get("volume", 0) for c in candles[-30:])
        vol_prev_30s = sum(c.get("volume", 0) for c in candles[-60:-30]) if len(candles) >= 60 else vol_recent_30s
        price_now = candles[-1].get("close", 0)
        price_30s_ago = candles[-30].get("close", price_now) if len(candles) >= 30 else price_now

        price_up = price_now > price_30s_ago
        vol_up = vol_recent_30s > vol_prev_30s * 1.2

        if direction == "SHORT":
            if price_up and vol_up:
                score_adjust += 10  # 新規ロング蓄積 → これから焼かれる = 好機
                notes.append("OI:new_long_acc")
            elif price_up and not vol_up:
                score_adjust -= 5  # ショートカバー → 焼かれた後 = 遅い
                notes.append("OI:short_cover")
        elif direction == "LONG":
            if not price_up and vol_up:
                score_adjust += 10  # 新規ショート蓄積 → 好機
                notes.append("OI:new_short_acc")
            elif not price_up and not vol_up:
                score_adjust -= 5  # ロング投げ → 遅い
                notes.append("OI:long_liq")

        # --- 追加候補2: 板消失速度 (スナップショット比較プロキシ) ---
        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            if bids and asks:
                try:
                    bid_depth = sum(float(b[1]) for b in bids[:5]) if isinstance(bids[0], (list, tuple)) else 0
                    ask_depth = sum(float(a[1]) for a in asks[:5]) if isinstance(asks[0], (list, tuple)) else 0
                    total_depth = bid_depth + ask_depth

                    # 板が極端に薄い = 見せ板がキャンセルされた可能性
                    if total_depth > 0:
                        recent_vol_10s = sum(c.get("volume", 0) for c in candles[-10:])
                        depth_vol_ratio = total_depth / (recent_vol_10s + 1)
                        if depth_vol_ratio < 0.1:
                            score_adjust -= 10  # 板薄すぎ = 見せ板消失後
                            notes.append("book:thin_post_cancel")
                        elif depth_vol_ratio > 5.0 and direction == "SHORT":
                            score_adjust += 5  # 板厚い + SHORT = 壁がある
                            notes.append("book:wall_support")
                except (TypeError, ValueError, IndexError):
                    pass

        # --- 追加候補3: 滑りやすさ係数 ---
        if len(candles) >= 20:
            spreads = []
            for c in candles[-20:]:
                h, l, cl = c.get("high", 0), c.get("low", 0), c.get("close", 1)
                if cl > 0:
                    spreads.append((h - l) / cl * 100)
            if spreads:
                avg_spread = float(np.mean(spreads))
                if avg_spread > 1.5:
                    score_adjust -= 8  # 高スプレッド = 滑りやすい
                    notes.append(f"slip:high({avg_spread:.2f}%)")
                elif avg_spread < 0.3:
                    score_adjust += 3  # 低スプレッド = 有利
                    notes.append(f"slip:low({avg_spread:.2f}%)")

        # --- 追加候補5: WeakShort統合 (SHORT方向のみ) ---
        if direction == "SHORT" and trades:
            recent_buys = [t for t in trades[-100:] if t.get("side") == "buy"]
            recent_sells = [t for t in trades[-100:] if t.get("side") == "sell"]
            if recent_buys and recent_sells:
                buy_amount = sum(t.get("amount", 0) for t in recent_buys)
                sell_amount = sum(t.get("amount", 0) for t in recent_sells)
                if buy_amount > sell_amount * 1.5:
                    score_adjust += 8  # 買いが多いのに下がってる = 弱い → SHORT好機
                    notes.append("weak:buy_but_weak")

        # --- 追加候補6: 過熱多重確認 ---
        confirmations = 0
        fr_value = fr_data.get("funding_rate", 0)
        if abs(fr_value) >= TRIGGERS["fr_strong"]:
            confirmations += 1
        vol_ratio_check = vol_recent_30s / (vol_prev_30s + 1)
        if vol_ratio_check > 2.0:
            confirmations += 1
        if trades:
            recent_10s = [t for t in trades if time.time() - t.get("timestamp", 0) < 10]
            if recent_10s:
                buy_vol = sum(t.get("amount", 0) for t in recent_10s if t.get("side") == "buy")
                total_vol = sum(t.get("amount", 0) for t in recent_10s)
                buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5
                if direction == "SHORT" and buy_ratio < 0.3:
                    confirmations += 1
                elif direction == "LONG" and buy_ratio > 0.7:
                    confirmations += 1

        if confirmations >= 3:
            score_adjust += 10
            notes.append(f"multi:{confirmations}conf")
        elif confirmations < 1:
            score_adjust -= 10
            notes.append("multi:weak")

        # --- 追加候補4: メタvariant (FR極端度で動的TP/SL調整) ---
        # signal自体のTP/SLは変えられないが、score調整で通過/フィルターを制御
        if abs(fr_value) >= TRIGGERS["fr_extreme"]:
            score_adjust += 5  # FR極端 → 高確信度
            notes.append("meta:extreme_fr")

        # --- 最終判定 ---
        if score_adjust <= -15:
            logger.info(f"[Evolved] {symbol} {direction} BLOCKED: adjust={score_adjust} {','.join(notes)}")
            return None  # フィルターで除外

        # notesをsignalに付加
        if hasattr(signal, 'variant'):
            if notes:
                logger.info(f"[Evolved] {symbol} {direction} adjust={score_adjust:+d} {','.join(notes)}")

        return signal

    def _evaluate_fr(self, fr: dict, regime: dict) -> Tuple[int, Optional[str]]:
        """FR偏り評価"""
        score = 0
        fr_value = fr.get("funding_rate", 0)

        fr_min = self.variant.get("fr_min_override", TRIGGERS["fr_min"])
        if abs(fr_value) < fr_min:
            return 0, None

        if abs(fr_value) >= TRIGGERS["fr_extreme"]:
            score += 40
        elif abs(fr_value) >= TRIGGERS["fr_strong"]:
            score += 25
        else:
            score += 15

        direction = "SHORT" if fr_value > 0 else "LONG"

        fear = regime.get("fear_greed", 50)
        if fear < 25 and direction == "LONG":
            score += 10
        elif fear > 75 and direction == "SHORT":
            score += 10

        return min(50, score), direction

    def _evaluate_realtime(self, symbol: str, direction: str) -> Tuple[int, list]:
        """1秒足リアルタイムトリガー評価"""
        score = 0
        reasons = []
        mult = self.variant["price_threshold_mult"]

        candles = self.ws_feed.get_1s_candles(symbol, 60)
        if len(candles) < 10:
            return 0, ["data_insufficient"]

        recent_trades = self.ws_feed.get_recent_trades(symbol, 200)
        orderbook = self.ws_feed.get_orderbook(symbol)

        # 価格急変
        if len(candles) >= 2:
            c1s = abs(candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100
            if c1s >= TRIGGERS["price_1s_threshold"] * mult:
                score += 20
                reasons.append(f"1s:{c1s:.2f}%")

        if len(candles) >= 6:
            c5s = abs(candles[-1]["close"] - candles[-6]["close"]) / candles[-6]["close"] * 100
            if c5s >= TRIGGERS["price_5s_threshold"] * mult:
                score += 15
                reasons.append(f"5s:{c5s:.2f}%")

        if len(candles) >= 11:
            c10s = abs(candles[-1]["close"] - candles[-11]["close"]) / candles[-11]["close"] * 100
            if c10s >= TRIGGERS["price_10s_threshold"] * mult:
                score += 10
                reasons.append(f"10s:{c10s:.2f}%")

        # 出来高急増
        vol_recent = sum(c["volume"] for c in candles[-10:])
        vol_avg = sum(c["volume"] for c in candles[-60:]) / 6 if len(candles) >= 60 else vol_recent
        vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1.0

        if vol_ratio >= TRIGGERS["volume_spike_ratio"]:
            score += 20
            reasons.append(f"vol:{vol_ratio:.1f}x")
        elif vol_ratio >= TRIGGERS["volume_ratio_min"]:
            score += 10
            reasons.append(f"vol:{vol_ratio:.1f}x")

        # 約定偏り
        if recent_trades:
            recent_10s = [t for t in recent_trades if time.time() - t["timestamp"] < 10]
            if recent_10s:
                buy_vol = sum(t["amount"] for t in recent_10s if t["side"] == "buy")
                total_vol = sum(t["amount"] for t in recent_10s)
                buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5

                if direction == "LONG" and buy_ratio >= TRIGGERS["buy_ratio_extreme"]:
                    score += 20
                    reasons.append(f"buy:{buy_ratio:.0%}")
                elif direction == "LONG" and buy_ratio >= TRIGGERS["buy_ratio_long"]:
                    score += 10
                    reasons.append(f"buy:{buy_ratio:.0%}")
                elif direction == "SHORT" and buy_ratio <= (1 - TRIGGERS["buy_ratio_extreme"]):
                    score += 20
                    reasons.append(f"sell:{1 - buy_ratio:.0%}")
                elif direction == "SHORT" and buy_ratio <= TRIGGERS["buy_ratio_short"]:
                    score += 10
                    reasons.append(f"sell:{1 - buy_ratio:.0%}")

                # 方向逆行
                if direction == "LONG" and buy_ratio < 0.3:
                    score -= 15
                    reasons.append("conflict:sell")
                elif direction == "SHORT" and buy_ratio > 0.7:
                    score -= 15
                    reasons.append("conflict:buy")

        # 板偏り
        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            if bids and asks:
                try:
                    bid_depth = sum(float(b[1]) for b in bids[:5]) if isinstance(bids[0], (list, tuple)) else 0
                    ask_depth = sum(float(a[1]) for a in asks[:5]) if isinstance(asks[0], (list, tuple)) else 0

                    if bid_depth > 0 and ask_depth > 0:
                        book_ratio = bid_depth / ask_depth
                        if direction == "LONG" and book_ratio >= TRIGGERS["book_imbalance_threshold"]:
                            score += 15
                            reasons.append(f"book:bid{book_ratio:.1f}x")
                        elif direction == "SHORT" and (1 / book_ratio) >= TRIGGERS["book_imbalance_threshold"]:
                            score += 15
                            reasons.append(f"book:ask{1 / book_ratio:.1f}x")
                except (TypeError, ValueError, IndexError):
                    pass

        return min(70, max(0, score)), reasons

    def _create_signal(self, symbol, direction, fr, combined_score,
                       fr_score, trigger_score, reasons) -> Optional[SecSignal]:
        """シグナル生成"""
        price = self.ws_feed.get_price(symbol)
        if not price or price <= 0:
            return None

        tp_pct = self.variant["tp_pct"]
        sl_pct = self.variant["sl_pct"]

        if direction == "LONG":
            tp_price = price * (1 + tp_pct / 100)
            sl_price = price * (1 - sl_pct / 100)
        else:
            tp_price = price * (1 - tp_pct / 100)
            sl_price = price * (1 + sl_pct / 100)

        candles = self.ws_feed.get_1s_candles(symbol, 10)
        change_1s = 0.0
        change_5s = 0.0
        if len(candles) >= 2:
            change_1s = (candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100
        if len(candles) >= 6:
            change_5s = (candles[-1]["close"] - candles[-6]["close"]) / candles[-6]["close"] * 100

        return SecSignal(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            leverage=self.variant["leverage"],
            position_pct=self.variant["position_pct"],
            burn_score=fr_score,
            trigger_score=trigger_score,
            combined_score=combined_score,
            reasons=reasons,
            fr_value=fr.get("funding_rate", 0),
            price_change_1s=change_1s,
            price_change_5s=change_5s,
            max_hold_seconds=self.variant["max_hold_seconds"],
            variant=self.variant_name,
            timestamp=datetime.now().isoformat(),
        )

    def _is_cooldown(self, symbol: str) -> bool:
        if symbol in self._cooldowns:
            return time.time() < self._cooldowns[symbol]
        return False

    def _set_cooldown(self, symbol: str, seconds: int):
        self._cooldowns[symbol] = time.time() + seconds

    def get_stats(self) -> dict:
        return self._stats.copy()
