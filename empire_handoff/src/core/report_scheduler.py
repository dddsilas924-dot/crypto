"""レポートスケジューラー - 3トリガー管理（startup / daily / emergency）"""
import asyncio
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
import pytz


class ReportScheduler:
    """レポートスケジューラー - 3トリガー管理 + Bot活動レポート"""

    JST = pytz.timezone('Asia/Tokyo')
    DAILY_TIMES = [time(9, 0), time(21, 0)]  # 朝9時 + 夜21時 JST

    def __init__(self, engine, alert, config: dict = None):
        self.engine = engine
        self.alert = alert
        config = config or {}

        # 緊急トリガー閾値
        emergency = config.get('emergency', {})
        self.triggers = {
            'btc_1h_pct': emergency.get('btc_1h_pct', 5.0),
            'btc_4h_pct': emergency.get('btc_4h_pct', 8.0),
            'fear_change': emergency.get('fear_change', 10),
            'btc_d_daily_pct': emergency.get('btc_d_daily_pct', 1.5),
            'oi_1h_change_pct': emergency.get('oi_1h_change_pct', 15.0),
        }
        self.cooldown_sec = emergency.get('cooldown_seconds', 7200)
        self.tier2_top_n = config.get('tier2_top_n', 20)

        # 状態
        self.last_triggered: Dict[str, datetime] = {}
        self.last_fear: Optional[int] = None
        self.last_btc_d: Optional[float] = None
        self.startup_sent = False
        self.last_daily_date: Optional[str] = None
        self._last_activity_report_key: Optional[str] = None

        # BTC/OI価格履歴 [(datetime, value), ...]
        self.btc_price_history: list = []
        self.oi_history: list = []

    async def on_startup(self):
        """起動時レポート"""
        report_data = await self._gather_report_data()
        await self.alert.send_market_report('startup', report_data)
        self.startup_sent = True

    async def check_daily(self):
        """毎スキャンサイクルで呼び出し - 9:00/21:00 JST判定"""
        now = datetime.now(self.JST)
        report_key = now.strftime('%Y-%m-%d_%H')

        for target_time in self.DAILY_TIMES:
            if now.hour == target_time.hour and now.minute < 2:
                if self.last_daily_date == report_key:
                    return
                # 市場レポート
                report_data = await self._gather_report_data()
                await self.alert.send_market_report('daily', report_data)
                self.last_daily_date = report_key

                # Bot活動レポート（Telegram + HTMLファイル保存）
                await self._send_activity_report(hours=12)
                break

    async def _send_activity_report(self, hours: int = 12):
        """Bot活動レポートをTelegram送信 + HTMLファイル保存"""
        activity_logger = getattr(self.engine, 'activity_logger', None)
        if not activity_logger:
            return

        report_key = datetime.now(self.JST).strftime('%Y-%m-%d_%H')
        if self._last_activity_report_key == report_key:
            return
        self._last_activity_report_key = report_key

        # Telegramサマリー送信
        tg_text = activity_logger.generate_telegram_summary(hours=hours)
        if tg_text:
            await self.alert.send_message(tg_text)

        # HTML保存
        try:
            from pathlib import Path
            report_dir = Path('vault/reports')
            report_dir.mkdir(parents=True, exist_ok=True)
            html = activity_logger.generate_html_report(hours=hours)
            filename = f'bot_activity_{datetime.now().strftime("%Y%m%d_%H%M")}.html'
            (report_dir / filename).write_text(html, encoding='utf-8')
        except Exception as e:
            print(f"[ReportScheduler] HTML保存エラー: {e}")

    # データ妥当性チェック範囲
    VALID_BTC_PRICE_MIN = 1000.0
    VALID_BTC_PRICE_MAX = 500000.0
    VALID_BTC_D_MIN = 30.0
    VALID_BTC_D_MAX = 80.0
    VALID_FG_MIN = 0
    VALID_FG_MAX = 100

    def _is_valid_btc_price(self, price: float) -> bool:
        return self.VALID_BTC_PRICE_MIN < price < self.VALID_BTC_PRICE_MAX

    def _is_valid_btc_d(self, btc_d: float) -> bool:
        return self.VALID_BTC_D_MIN < btc_d < self.VALID_BTC_D_MAX

    def _is_valid_fear(self, fg: int) -> bool:
        return self.VALID_FG_MIN <= fg <= self.VALID_FG_MAX

    async def check_emergency(self, current_data: dict):
        """毎スキャンサイクルで呼び出し - 5条件チェック（妥当性ガード付き）"""
        now = datetime.now()
        triggers_fired = []

        btc_price = current_data.get('btc_price', 0)
        fear = current_data.get('fear', 50)
        btc_d = current_data.get('btc_d', 0)
        total_oi = current_data.get('total_oi', 0)

        # === BTC価格の妥当性チェック ===
        btc_price_valid = self._is_valid_btc_price(btc_price)
        if btc_price > 0 and not btc_price_valid:
            print(f"[Emergency] BTC価格異常値: ${btc_price:,.0f} (範囲外), トリガー除外")

        # BTC価格履歴に追加（正常値のみ）
        if btc_price_valid:
            self.btc_price_history.append((now, btc_price))
        # 古い履歴削除（5時間分保持）
        cutoff = now - timedelta(hours=5)
        self.btc_price_history = [(t, p) for t, p in self.btc_price_history if t > cutoff]

        # 1. BTC 1h +-5%（正常価格のみ）
        if btc_price_valid:
            price_1h = self._get_history_at(self.btc_price_history, 3600)
            if price_1h and price_1h > 0:
                change_1h = (btc_price - price_1h) / price_1h * 100
                if abs(change_1h) >= self.triggers['btc_1h_pct']:
                    if self._can_trigger('btc_1h_pct', now):
                        triggers_fired.append(f"BTC 1h {change_1h:+.1f}%")

        # 2. BTC 4h +-8%（正常価格のみ）
        if btc_price_valid:
            price_4h = self._get_history_at(self.btc_price_history, 14400)
            if price_4h and price_4h > 0:
                change_4h = (btc_price - price_4h) / price_4h * 100
                if abs(change_4h) >= self.triggers['btc_4h_pct']:
                    if self._can_trigger('btc_4h_pct', now):
                        triggers_fired.append(f"BTC 4h {change_4h:+.1f}%")

        # 3. Fear & Greed 10pt変動（正常値のみ）
        if self._is_valid_fear(fear):
            if self.last_fear is not None:
                fear_change = abs(fear - self.last_fear)
                if fear_change >= self.triggers['fear_change']:
                    if self._can_trigger('fear_change', now):
                        triggers_fired.append(f"Fear {self.last_fear}→{fear} ({fear_change:+d}pt)")
            self.last_fear = fear
        else:
            print(f"[Emergency] Fear異常値: {fear} (範囲外), トリガー除外")

        # 4. BTC.D 日次 +-1.5%（正常値のみ）
        if self._is_valid_btc_d(btc_d):
            if self.last_btc_d is not None and self.last_btc_d > 0:
                btc_d_change = btc_d - self.last_btc_d
                if abs(btc_d_change) >= self.triggers['btc_d_daily_pct']:
                    if self._can_trigger('btc_d_daily_pct', now):
                        triggers_fired.append(f"BTC.D {btc_d_change:+.1f}%")
            self.last_btc_d = btc_d
        else:
            if btc_d > 0:
                print(f"[Emergency] BTC.D異常値: {btc_d:.1f}% (範囲外), 前回値{self.last_btc_d}%を維持")

        # 5. OI 1h +-15%
        if total_oi > 0:
            self.oi_history.append((now, total_oi))
        cutoff_oi = now - timedelta(hours=5)
        self.oi_history = [(t, v) for t, v in self.oi_history if t > cutoff_oi]

        oi_1h = self._get_history_at(self.oi_history, 3600)
        if oi_1h and oi_1h > 0 and total_oi > 0:
            oi_change = (total_oi - oi_1h) / oi_1h * 100
            if abs(oi_change) >= self.triggers['oi_1h_change_pct']:
                if self._can_trigger('oi_1h_change_pct', now):
                    triggers_fired.append(f"OI 1h {oi_change:+.1f}%")

        # トリガー発火 → 緊急レポート送信
        if triggers_fired:
            report_data = await self._gather_report_data()
            report_data['triggers'] = triggers_fired
            await self.alert.send_market_report('emergency', report_data)

    def _can_trigger(self, trigger_name: str, now: datetime) -> bool:
        """クールダウン判定（条件ごとに独立）"""
        last = self.last_triggered.get(trigger_name)
        if last is None or (now - last).total_seconds() >= self.cooldown_sec:
            self.last_triggered[trigger_name] = now
            return True
        return False

    def _get_history_at(self, history: list, seconds_ago: int) -> Optional[float]:
        """X秒前の値を履歴から取得（最も近いタイムスタンプ）"""
        if not history:
            return None
        now = datetime.now()
        target = now - timedelta(seconds=seconds_ago)
        # 対象時刻前後30秒以内のデータを探す
        best = None
        best_diff = float('inf')
        for t, v in history:
            diff = abs((t - target).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best = v
        # 30分以上乖離したデータは使わない
        if best_diff > 1800:
            return None
        return best

    async def _gather_report_data(self) -> dict:
        """レポート用データ収集"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'btc_price': 0,
            'btc_change_24h': 0,
            'fear_greed': self.engine.state.fear_greed,
            'btc_dominance': 0,
            'regime': self.engine.state.regime,
            'regime_action': self.engine.regime.get_action(),
            'tier1_passed': [],
            'tier2_passed': [],
            'tier2_top': [],
            'bot_alpha_status': 'waiting',
            'bot_alpha_last': None,
            'bot_surge_status': 'waiting',
            'bot_surge_last': None,
            'positions': [],
            'feedback_stats': {},
        }

        # BTC価格
        try:
            btc_ticker = await self.engine.fetcher.fetch_ticker('BTC/USDT:USDT')
            if btc_ticker:
                data['btc_price'] = btc_ticker.get('last', 0)
                data['btc_change_24h'] = btc_ticker.get('percentage', 0) or 0
        except Exception:
            pass

        # BTC.D
        regime_data = getattr(self.engine.state, 'regime_data', {}) or {}
        data['btc_dominance'] = regime_data.get('btc_dominance', 0)

        # Bot状態
        if self.engine.bot_alpha.activated:
            data['bot_alpha_status'] = 'fired'
        elif self.engine.state.fear_greed < 15:
            data['bot_alpha_status'] = 'near'
        data['bot_alpha_last'] = self.engine.bot_alpha.last_activation

        if self.engine.bot_surge.activated:
            data['bot_surge_status'] = 'active'

        # Tier1/2通過銘柄
        t1_list = self.engine.state.get_tier1_passed()
        t2_list = self.engine.state.get_tier2_passed()
        data['tier1_passed'] = t1_list
        data['tier2_passed'] = t2_list

        # Tier2上位N件（スコア順）
        t2_sorted = sorted(t2_list, key=lambda s: s.tier1_score + s.tier2_score, reverse=True)
        data['tier2_top'] = t2_sorted[:self.tier2_top_n]

        # 新規上場フラグ
        try:
            new_listings = set()
            for s in t2_sorted[:self.tier2_top_n]:
                if self.engine.db.is_new_listing(s.symbol):
                    new_listings.add(s.symbol)
            data['new_listings'] = new_listings
        except Exception:
            data['new_listings'] = set()

        # セクター別内訳
        sector_counts = {}
        for s in t1_list:
            sec = s.sector or 'Unknown'
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
        data['tier1_sector_breakdown'] = sector_counts

        # ポジション
        try:
            data['positions'] = self.engine.db.get_open_positions()
        except Exception:
            pass

        # フィードバック
        try:
            data['feedback_stats'] = self.engine.feedback.get_accuracy_stats()
        except Exception:
            pass

        return data
