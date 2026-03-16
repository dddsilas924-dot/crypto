"""Bot-LevBurn: レバレッジ焼き検知エンジン"""
import logging
from typing import Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger("empire")


class LevBurnEngine:
    """レバレッジ焼き銘柄の検知と売買シグナル生成"""

    def __init__(self, config: dict):
        params = config.get('params', config)
        self.fr_threshold = params.get('fr_threshold', 0.1)
        self.fr_extreme = params.get('fr_extreme', 0.3)
        self.oi_min_usd = params.get('oi_min_usd', 10_000_000)
        self.oi_change_spike = params.get('oi_change_spike', 20)
        self.oi_change_extreme = params.get('oi_change_extreme', 50)
        self.futures_spot_ratio_min = params.get('futures_spot_ratio_min', 5)
        self.futures_spot_ratio_high = params.get('futures_spot_ratio_high', 20)
        self.min_score = params.get('min_score', 60)
        self.leverage = config.get('leverage', 5)
        self.position_pct = config.get('position_pct', 3)
        self.tp_pct_normal = params.get('tp_pct_normal', 5.0)
        self.tp_pct_extreme = params.get('tp_pct_extreme', 8.0)
        self.sl_pct = params.get('sl_pct', 2.5)
        self.max_hold_hours = params.get('max_hold_hours', 48)

    def detect_burn_candidates(self, scan_results: list, regime: dict = None) -> list:
        """レバ焼き候補を検出"""
        if regime is None:
            regime = {}
        candidates = []
        for data in scan_results:
            score, direction, reasons = self._evaluate(data, regime)
            if score >= self.min_score:
                candidates.append({
                    "symbol": data["symbol"],
                    "direction": direction,
                    "burn_score": score,
                    "funding_rate": data["funding_rate"],
                    "oi_usd": data.get("open_interest", 0),
                    "oi_change_24h": data.get("oi_change_24h_pct", 0),
                    "futures_spot_ratio": data.get("futures_spot_ratio", 0),
                    "reasons": reasons,
                    "risk_level": "HIGH" if score >= 80 else "MEDIUM",
                })

        return sorted(candidates, key=lambda x: x["burn_score"], reverse=True)

    def _evaluate(self, data: dict, regime: dict) -> Tuple[int, str, list]:
        """レバ焼きスコア算出（0-100）"""
        score = 0
        reasons = []
        fr = data.get("funding_rate", 0)
        oi = data.get("open_interest", 0)
        oi_chg = data.get("oi_change_24h_pct", 0)
        ratio = data.get("futures_spot_ratio", 0)

        # === FR判定 ===
        abs_fr = abs(fr)
        if abs_fr >= self.fr_extreme:
            score += 30
            reasons.append(f"FR極端偏り ({fr:+.4f})")
        elif abs_fr >= self.fr_threshold:
            score += 20
            reasons.append(f"FR偏り ({fr:+.4f})")

        # 方向決定
        if fr > 0:
            direction = "SHORT"
            reasons.append("ロング過熱 → ショート候補")
        else:
            direction = "LONG"
            reasons.append("ショート過熱 → ロング候補")

        # === OI判定 ===
        if oi >= self.oi_min_usd:
            score += 10
            reasons.append(f"OI十分 (${oi / 1e6:.0f}M)")
        else:
            score -= 20
            reasons.append(f"OI不足 (${oi / 1e6:.0f}M)")

        abs_oi_chg = abs(oi_chg)
        if abs_oi_chg >= self.oi_change_extreme:
            score += 25
            reasons.append(f"OI急変 ({oi_chg:+.1f}%)")
        elif abs_oi_chg >= self.oi_change_spike:
            score += 15
            reasons.append(f"OI変動 ({oi_chg:+.1f}%)")

        # === 投機度判定 ===
        if ratio >= self.futures_spot_ratio_high:
            score += 20
            reasons.append(f"高投機 (先物/現物 {ratio:.0f}x)")
        elif ratio >= self.futures_spot_ratio_min:
            score += 10
            reasons.append(f"投機傾向 (先物/現物 {ratio:.0f}x)")

        # === Regime連携 ===
        fear = regime.get("fear_greed", 50)
        if fear < 25 and direction == "LONG":
            score += 10
            reasons.append("極度恐怖 + ロング = ショートスクイーズ高確率")
        elif fear > 75 and direction == "SHORT":
            score += 10
            reasons.append("極度強欲 + ショート = ロング清算高確率")

        score = min(100, max(0, score))
        return score, direction, reasons

    def generate_signal(self, candidate: dict) -> dict:
        """売買シグナル生成"""
        fr = candidate.get("funding_rate", 0)

        if abs(fr) >= self.fr_extreme:
            tp_pct = self.tp_pct_extreme
            sl_pct = self.sl_pct + 0.5
        elif abs(fr) >= self.fr_threshold:
            tp_pct = self.tp_pct_normal
            sl_pct = self.sl_pct
        else:
            tp_pct = 3.0
            sl_pct = 2.0

        return {
            "bot_name": "levburn",
            "symbol": candidate["symbol"],
            "direction": candidate["direction"],
            "side": candidate["direction"].lower(),
            "leverage": self.leverage,
            "position_pct": self.position_pct,
            "position_size_pct": self.position_pct,
            "tp_pct": tp_pct,
            "take_profit_pct": tp_pct,
            "sl_pct": sl_pct,
            "stop_loss_pct": sl_pct,
            "max_hold_hours": self.max_hold_hours,
            "burn_score": candidate["burn_score"],
            "reasons": candidate["reasons"],
            "risk_level": candidate["risk_level"],
            "funding_rate": fr,
            "oi_usd": candidate.get("oi_usd", 0),
            "oi_change_24h": candidate.get("oi_change_24h", 0),
            "futures_spot_ratio": candidate.get("futures_spot_ratio", 0),
        }
