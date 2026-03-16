"""統合テスト v3.3: ペーパートレード + 安定性対策"""
import asyncio
import sys
import os
import html
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

class SystemTester:
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def log(self, test_name: str, passed: bool, detail: str = ""):
        status = "✅ PASS" if passed else "❌ FAIL"
        self.results.append(f"{status} | {test_name}: {detail}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  {status} {test_name}: {detail}")

    # ============================================
    # TEST 1-7: 既存テスト（v3互換）
    # ============================================

    async def test_env(self):
        print("\n[TEST 1] 環境変数チェック...")
        for key in ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'MEXC_API_KEY', 'MEXC_API_SECRET']:
            val = os.getenv(key)
            if val and len(val) > 5:
                self.log(f"ENV {key}", True, f"設定済み ({len(val)}文字)")
            else:
                self.log(f"ENV {key}", False, "未設定または短すぎる")

    async def test_telegram(self):
        print("\n[TEST 2] Telegram Bot接続テスト...")
        try:
            from src.execution.alert import TelegramAlert
            alert = TelegramAlert()
            success = await alert.send_message("🧪 <b>Empire Monitor v3.3 テスト送信</b>\n\nアラート体系改修テスト実行中...")
            self.log("Telegram送信", success, "送信完了" if success else "送信失敗")
            return alert
        except Exception as e:
            self.log("Telegram送信", False, str(e))
            return None

    async def test_mexc(self):
        print("\n[TEST 3] MEXC API接続テスト...")
        try:
            from src.fetchers.ohlcv import MEXCFetcher
            fetcher = MEXCFetcher()

            symbols = await fetcher.fetch_futures_symbols()
            self.log("先物銘柄取得", len(symbols) > 0, f"{len(symbols)}銘柄")

            ticker = await fetcher.fetch_ticker('BTC/USDT:USDT')
            if ticker and ticker.get('last'):
                self.log("BTCティッカー", True, f"${ticker['last']:,.2f}")
            else:
                self.log("BTCティッカー", False, "取得失敗")

            ohlcv = await fetcher.fetch_ohlcv('BTC/USDT:USDT', '1m', 10)
            self.log("1分足OHLCV", ohlcv is not None and len(ohlcv) > 0, f"{len(ohlcv) if ohlcv is not None else 0}本")

            ob = await fetcher.fetch_orderbook('BTC/USDT:USDT')
            self.log("板情報", ob is not None and ob.get('total_depth_usd', 0) > 0, f"${ob['total_depth_usd']:,.0f}" if ob else "N/A")

            fr = await fetcher.fetch_funding_rate('BTC/USDT:USDT')
            self.log("Funding Rate", fr is not None, f"{fr:.6f}" if fr else "N/A")

            all_t = await fetcher.fetch_all_tickers()
            self.log("全ティッカー", len(all_t) > 0, f"{len(all_t)}銘柄")

            await fetcher.close()
        except Exception as e:
            self.log("MEXC接続", False, traceback.format_exc())

    async def test_database(self):
        print("\n[TEST 4] データベーステスト...")
        try:
            from src.data.database import HistoricalDB
            db = HistoricalDB()
            self.log("DB初期化", True, "テーブル作成OK")

            count_1d = db.get_ohlcv_count('BTC/USDT:USDT', '1d')
            self.log("BTC日足レコード", True, f"{count_1d}件")

            db.set_sanctuary('TEST/USDT:USDT', 1.234, '2025-10-10', 'test')
            val = db.get_sanctuary('TEST/USDT:USDT')
            self.log("聖域価格 set/get", val == 1.234, f"{val}")

            db.set_sector('TEST/USDT:USDT', 'test-id', '["DeFi"]', 'DeFi', 100, 'Ethereum', 'DEX')
            detail = db.get_sector_detail('TEST/USDT:USDT')
            self.log("セクター Messari拡張", detail is not None and detail['chain'] == 'Ethereum',
                     f"sector={detail['sector']}, chain={detail['chain']}" if detail else "N/A")

            syms = db.get_symbols_by_sector('DeFi')
            self.log("セクター別銘柄取得", 'TEST/USDT:USDT' in syms, f"{len(syms)}銘柄")

            db.add_watchlist('TEST/USDT:USDT', 'テスト', 1)
            wl = db.get_watchlist()
            self.log("ウォッチリスト add/get", 'TEST/USDT:USDT' in wl, f"{len(wl)}件")
            db.remove_watchlist('TEST/USDT:USDT')

            db.add_position('TEST/USDT:USDT', 'long', 100.0, 1.0, 3.0, 95.0, 110.0, 'test')
            pos = db.get_open_positions()
            self.log("ポジション add/get", len(pos) > 0, f"{len(pos)}件")

            db.log_alert('TEST/USDT:USDT', 100.0, 50.0, 30.0, 'D', 8)
            self.log("アラートログ", True, "記録OK")

            conn = db._get_conn()
            conn.execute("DELETE FROM sanctuary WHERE symbol='TEST/USDT:USDT'")
            conn.execute("DELETE FROM sector WHERE symbol='TEST/USDT:USDT'")
            conn.execute("DELETE FROM positions WHERE symbol='TEST/USDT:USDT'")
            conn.execute("DELETE FROM alert_log WHERE symbol='TEST/USDT:USDT'")
            conn.commit()
            conn.close()

        except Exception as e:
            self.log("DB", False, traceback.format_exc())

    async def test_regime(self):
        print("\n[TEST 5] 市場環境判定テスト...")
        try:
            from src.signals.regime import RegimeDetector
            regime = RegimeDetector()

            gd = await regime.fetch_global_data()
            self.log("グローバルデータ", bool(gd), f"BTC.D: {gd.get('btc_dominance', 0):.1f}%" if gd else "N/A")

            fg = await regime.fetch_fear_greed()
            self.log("Fear&Greed", fg is not None, f"値: {fg}")

            # A-F全パターンテスト（DOM閾値=0.3, BTC/Total閾値=1.0）
            test_cases = [
                (5, 0.5, 3, 'A'),      # BTC↑ DOM↑ Total↑
                (3, -0.5, 4, 'B'),     # BTC↑ DOM↓ Total↑
                (-5, 0.5, -4, 'C'),    # BTC↓ DOM↑ Total↓
                (-3, -0.5, 0.5, 'D'),  # BTC↓ DOM↓ Total→
                (0.5, 0.5, 0.5, 'E'),  # BTC→ DOM↑ Total→
                (0.5, -0.5, 0.5, 'F'), # BTC→ DOM↓ Total→
            ]
            for btc, dom, total, exp in test_cases:
                r = regime.classify(btc, dom, total)
                self.log(f"パターン{exp}", r == exp, f"→{r}")

            # 該当なし → F（デフォルト）
            r = regime.classify(5, 0.5, -3)  # BTC↑ DOM↑ Total↓ → 定義なし → F
            self.log("パターンF(default)", r == 'F', f"→{r}")

            self.log("Extreme Fear判定", regime.is_extreme_fear() == (fg <= 20), f"FG={fg}, extreme={regime.is_extreme_fear()}")
        except Exception as e:
            self.log("市場環境", False, str(e))

    async def test_tier1(self):
        print("\n[TEST 6] Tier 1テスト...")
        try:
            from src.signals.tier1_engine import Tier1Engine
            from src.core.state import SymbolState
            from src.fetchers.ohlcv import MEXCFetcher

            engine = Tier1Engine({'volume_spike_ratio': 2.0, 'volatility_threshold': 5.0, 'correlation_threshold': 0.5, 'alpha_threshold': 3.0})
            fetcher = MEXCFetcher()

            state = SymbolState(symbol='BTC/USDT:USDT')
            state.ohlcv_1m = await fetcher.fetch_ohlcv('BTC/USDT:USDT', '1m', 30)
            state.ohlcv_1d = await fetcher.fetch_ohlcv('BTC/USDT:USDT', '1d', 210)
            if state.ohlcv_1d is not None:
                state.last_price = state.ohlcv_1d['close'].iloc[-1]

            results = engine.run(state)
            self.log("Tier1実行", True, f"Score:{state.tier1_score:.0f}")
            for k, v in results.items():
                self.log(f"  {k}", True, v.get('reason', 'N/A'))

            state2 = SymbolState(symbol='NEW/USDT:USDT')
            state2.last_price = 1.0
            r = engine.l02_alpha_sanctuary(state2, None)
            self.log("L02 聖域バイパス", r['passed'] and r['score'] == 5, r['reason'])

            await fetcher.close()
        except Exception as e:
            self.log("Tier1", False, traceback.format_exc())

    async def test_tier2(self):
        print("\n[TEST 7] Tier 2テスト...")
        try:
            from src.signals.tier2_engine import Tier2Engine
            from src.core.state import SymbolState
            from src.fetchers.ohlcv import MEXCFetcher

            engine = Tier2Engine({'min_orderbook_depth_usd': 100000, 'funding_rate_extreme': 0.05})
            fetcher = MEXCFetcher()

            state = SymbolState(symbol='BTC/USDT:USDT')
            ob = await fetcher.fetch_orderbook('BTC/USDT:USDT')
            if ob:
                state.orderbook_depth_usd = ob['total_depth_usd']
            fr = await fetcher.fetch_funding_rate('BTC/USDT:USDT')
            if fr is not None:
                state.funding_rate = fr

            results = engine.run(state)
            self.log("Tier2実行", True, f"Score:{state.tier2_score:.0f}")
            for k, v in results.items():
                self.log(f"  {k}", True, v.get('reason', 'N/A'))

            await fetcher.close()
        except Exception as e:
            self.log("Tier2", False, traceback.format_exc())

    # ============================================
    # TEST 8-10: v3テスト（Bot-Alpha/Surge/Sector）
    # ============================================

    async def test_sector_mapping(self):
        print("\n[TEST 8] Messariセクター分類テスト...")
        try:
            from config.sector_mapping import classify_sector, classify_chain

            r = classify_sector(['decentralized-finance-defi', 'yield-farming'])
            self.log("DeFi分類", r == 'DeFi', f"→{r}")

            r = classify_sector(['artificial-intelligence'])
            self.log("AI分類", r == 'AI', f"→{r}")

            r = classify_sector(['meme-token', 'dog-themed-coins'])
            self.log("Meme分類", r == 'Meme', f"→{r}")

            r = classify_sector(['gaming', 'play-to-earn'])
            self.log("Gaming分類", r == 'Gaming', f"→{r}")

            r = classify_sector([])
            self.log("空カテゴリ→Unknown", r == 'Unknown', f"→{r}")

            r = classify_chain([], {'solana': 'addr', 'ethereum': 'addr2'})
            self.log("チェーン分類(platform)", r in ['Solana', 'Ethereum'], f"→{r}")

            r = classify_chain(['solana-ecosystem'], None)
            self.log("チェーン分類(category)", r == 'Solana', f"→{r}")

        except Exception as e:
            self.log("セクター分類", False, traceback.format_exc())

    async def test_bot_alpha(self):
        print("\n[TEST 9] Bot-Alpha 極限一撃モード テスト...")
        try:
            from src.signals.bot_alpha_engine import BotAlphaEngine
            from src.data.database import HistoricalDB

            db = HistoricalDB()
            engine = BotAlphaEngine({
                'fear_threshold': 10,
                'btc_return_threshold': -1.0,
                'btc_d_drop_threshold': -0.5,
                'correlation_max': 0.5,
                'alpha_min': 3.0,
            }, db)

            r = engine.check_activation(50, 1.0, 0.5)
            self.log("Alpha不発火(FG=50)", not r['activated'], f"conditions={r['conditions']}")

            r = engine.check_activation(7, -2.0, -0.8)
            self.log("Alpha発火(FG=7)", r['activated'], f"conditions={r['conditions']}")

            test_data = [
                {'symbol': 'JTO/USDT:USDT', 'correlation': 0.17, 'alpha': 6.4, 'price': 2.5, 'sector': 'DeFi'},
                {'symbol': 'TAO/USDT:USDT', 'correlation': 0.35, 'alpha': 5.0, 'price': 300.0, 'sector': 'AI'},
                {'symbol': 'BTC/USDT:USDT', 'correlation': 1.0, 'alpha': 0.0, 'price': 80000, 'sector': 'Networks'},
            ]
            targets = engine.scan_targets(test_data)
            self.log("Alphaターゲットスキャン", len(targets) == 2, f"{len(targets)}件 (JTO, TAO)")

            signal = engine.generate_signal(r, targets, 7)
            self.log("Alphaシグナル生成", signal is not None and signal['mode'] == 'bot_alpha',
                     f"target={signal['entry']['symbol']}" if signal else "None")

        except Exception as e:
            self.log("Bot-Alpha", False, traceback.format_exc())

    async def test_bot_surge(self):
        print("\n[TEST 10] Bot-Surge 日常循環モード テスト...")
        try:
            from src.signals.bot_surge_engine import BotSurgeEngine
            from src.data.database import HistoricalDB

            db = HistoricalDB()
            engine = BotSurgeEngine({
                'fear_min': 25,
                'fear_max': 45,
                'divergence_threshold': 3.0,
                'rsi_min': 50,
            }, db)

            r = engine.check_activation(60, 2.0)
            self.log("Surge不発火(FG=60)", not r['activated'], f"conditions={r['conditions']}")

            r = engine.check_activation(35, -0.5)
            self.log("Surge発火(FG=35)", r['activated'], f"conditions={r['conditions']}")

            test_data = [
                {'symbol': 'SOL/USDT:USDT', 'btc_divergence': 5.2, 'price': 150.0, 'sector': 'Networks', 'rsi': 55},
                {'symbol': 'JUP/USDT:USDT', 'btc_divergence': 1.5, 'price': 0.8, 'sector': 'DeFi', 'rsi': 45},
                {'symbol': 'ETH/USDT:USDT', 'btc_divergence': -4.0, 'price': 3000.0, 'sector': 'Networks', 'rsi': 60},
            ]
            divergent = engine.detect_divergence(test_data)
            self.log("BTC乖離検出", len(divergent) == 2, f"{len(divergent)}件 (SOL, ETH)")

            self.log("セクターラグテーブル", len(engine.sector_lag) >= 5,
                     f"{len(engine.sector_lag)}セクター: {list(engine.sector_lag.keys())}")

            signal = engine.generate_signal(r, divergent, [], 35)
            has_entry = signal is not None and 'entry' in signal
            self.log("Surgeシグナル生成", has_entry,
                     f"target={signal['entry']['symbol']}" if has_entry else "None (RSIフィルタ)")

        except Exception as e:
            self.log("Bot-Surge", False, traceback.format_exc())

    # ============================================
    # TEST 11-17: v3.1 新規テスト（レポート体系）
    # ============================================

    async def test_report_startup(self):
        print("\n[TEST 11] 起動レポート送信テスト...")
        try:
            from src.execution.alert import TelegramAlert
            alert = TelegramAlert()

            # send_market_report をstartupモードでテスト
            test_data = {
                'btc_price': 70000,
                'btc_change_24h': -1.5,
                'fear_greed': 13,
                'btc_dominance': 56.9,
                'regime': 'D',
                'regime_action': '先行買い（本質Alpha）',
                'bot_alpha_status': 'near',
                'bot_alpha_last': None,
                'bot_surge_status': 'waiting',
                'tier1_passed': [],
                'tier2_passed': [],
                'tier2_top': [],
                'tier1_sector_breakdown': {'AI': 5, 'DeFi': 3, 'Meme': 2},
                'positions': [],
                'feedback_stats': {'avg_1h': 0.5, 'avg_24h': 1.2, 'win_rate_24h': 65},
            }
            success = await alert.send_market_report('startup', test_data)
            self.log("起動レポート送信", success, "startup形式送信OK")
        except Exception as e:
            self.log("起動レポート", False, traceback.format_exc())

    async def test_report_daily_format(self):
        print("\n[TEST 12] デイリーレポートフォーマット...")
        try:
            from src.execution.alert import TelegramAlert
            from src.core.state import SymbolState
            alert = TelegramAlert()

            # Tier2上位を含むデイリーレポートテスト
            mock_t2 = []
            for sym, sec, score in [('SOL/USDT:USDT', 'Networks', 85), ('TAO/USDT:USDT', 'AI', 78), ('JUP/USDT:USDT', 'DeFi', 65)]:
                s = SymbolState(symbol=sym)
                s.sector = sec
                s.tier1_score = score * 0.6
                s.tier2_score = score * 0.4
                mock_t2.append(s)

            test_data = {
                'btc_price': 69500,
                'btc_change_24h': 2.1,
                'fear_greed': 35,
                'btc_dominance': 57.2,
                'regime': 'B',
                'regime_action': '全力買い（アルト祭）',
                'bot_alpha_status': 'waiting',
                'bot_alpha_last': None,
                'bot_surge_status': 'active',
                'tier1_passed': mock_t2,
                'tier2_passed': mock_t2,
                'tier2_top': mock_t2,
                'tier1_sector_breakdown': {'Networks': 2, 'AI': 1, 'DeFi': 1},
                'positions': [{'symbol': 'SOL/USDT:USDT', 'unrealized_pnl_pct': 3.5}],
                'feedback_stats': {},
            }
            success = await alert.send_market_report('daily', test_data)
            self.log("デイリーレポート送信", success, "daily形式送信OK, Tier2上位3銘柄含む")
        except Exception as e:
            self.log("デイリーレポート", False, traceback.format_exc())

    async def test_emergency_btc_1h(self):
        print("\n[TEST 13] 緊急トリガー: BTC 1h ±5%...")
        try:
            from src.core.report_scheduler import ReportScheduler

            # ダミーengine/alert
            class MockEngine:
                class state:
                    fear_greed = 20
                    regime = 'C'
                    regime_data = {'btc_dominance': 55}
                    @staticmethod
                    def get_tier1_passed(): return []
                    @staticmethod
                    def get_tier2_passed(): return []
                class regime:
                    @staticmethod
                    def get_action(): return 'test'
                class fetcher:
                    @staticmethod
                    async def fetch_ticker(s): return {'last': 65000, 'percentage': -6}
                class bot_alpha:
                    activated = False
                    last_activation = None
                class bot_surge:
                    activated = False
                class db:
                    @staticmethod
                    def get_open_positions(): return []
                class feedback:
                    @staticmethod
                    def get_accuracy_stats(): return {}

            class MockAlert:
                sent_reports = []
                async def send_market_report(self, rtype, data):
                    self.sent_reports.append((rtype, data))
                    return True

            mock_alert = MockAlert()
            scheduler = ReportScheduler(MockEngine(), mock_alert, {
                'emergency': {'btc_1h_pct': 5.0, 'cooldown_seconds': 7200}
            })

            # 1時間前の価格を履歴に入れる
            now = datetime.now()
            scheduler.btc_price_history.append((now - timedelta(hours=1), 70000))

            # BTC -7.1% (70000→65000)
            await scheduler.check_emergency({'btc_price': 65000, 'fear': 20, 'btc_d': 55, 'total_oi': 0})

            fired = len(mock_alert.sent_reports) > 0
            self.log("BTC 1h -7.1%トリガー", fired,
                     f"送信回数={len(mock_alert.sent_reports)}" + (f", triggers={mock_alert.sent_reports[0][1].get('triggers', [])}" if fired else ""))

        except Exception as e:
            self.log("緊急BTC 1h", False, traceback.format_exc())

    async def test_emergency_fear(self):
        print("\n[TEST 14] 緊急トリガー: Fear 10pt変動...")
        try:
            from src.core.report_scheduler import ReportScheduler

            class MockEngine:
                class state:
                    fear_greed = 15
                    regime = 'D'
                    regime_data = {}
                    @staticmethod
                    def get_tier1_passed(): return []
                    @staticmethod
                    def get_tier2_passed(): return []
                class regime:
                    @staticmethod
                    def get_action(): return 'test'
                class fetcher:
                    @staticmethod
                    async def fetch_ticker(s): return {'last': 70000, 'percentage': 0}
                class bot_alpha:
                    activated = False
                    last_activation = None
                class bot_surge:
                    activated = False
                class db:
                    @staticmethod
                    def get_open_positions(): return []
                class feedback:
                    @staticmethod
                    def get_accuracy_stats(): return {}

            class MockAlert:
                sent_reports = []
                async def send_market_report(self, rtype, data):
                    self.sent_reports.append((rtype, data))
                    return True

            mock_alert = MockAlert()
            scheduler = ReportScheduler(MockEngine(), mock_alert, {
                'emergency': {'fear_change': 10, 'cooldown_seconds': 7200}
            })

            # 初回: last_fear設定
            await scheduler.check_emergency({'btc_price': 70000, 'fear': 30, 'btc_d': 55, 'total_oi': 0})
            # 2回目: 30→15 = -15pt → トリガー
            await scheduler.check_emergency({'btc_price': 70000, 'fear': 15, 'btc_d': 55, 'total_oi': 0})

            fired = len(mock_alert.sent_reports) > 0
            self.log("Fear -15ptトリガー", fired,
                     f"送信回数={len(mock_alert.sent_reports)}")

        except Exception as e:
            self.log("緊急Fear", False, traceback.format_exc())

    async def test_emergency_cooldown(self):
        print("\n[TEST 15] 緊急トリガー: クールダウン確認...")
        try:
            from src.core.report_scheduler import ReportScheduler

            class MockEngine:
                class state:
                    fear_greed = 20
                    regime = 'D'
                    regime_data = {}
                    @staticmethod
                    def get_tier1_passed(): return []
                    @staticmethod
                    def get_tier2_passed(): return []
                class regime:
                    @staticmethod
                    def get_action(): return 'test'
                class fetcher:
                    @staticmethod
                    async def fetch_ticker(s): return {'last': 65000, 'percentage': -6}
                class bot_alpha:
                    activated = False
                    last_activation = None
                class bot_surge:
                    activated = False
                class db:
                    @staticmethod
                    def get_open_positions(): return []
                class feedback:
                    @staticmethod
                    def get_accuracy_stats(): return {}

            class MockAlert:
                sent_count = 0
                async def send_market_report(self, rtype, data):
                    self.sent_count += 1
                    return True

            mock_alert = MockAlert()
            scheduler = ReportScheduler(MockEngine(), mock_alert, {
                'emergency': {'btc_1h_pct': 5.0, 'cooldown_seconds': 7200}
            })

            now = datetime.now()
            scheduler.btc_price_history.append((now - timedelta(hours=1), 70000))

            # 1回目: 発火
            await scheduler.check_emergency({'btc_price': 65000, 'fear': 20, 'btc_d': 55, 'total_oi': 0})
            first_count = mock_alert.sent_count

            # 2回目（即座）: クールダウン中なので発火しない
            await scheduler.check_emergency({'btc_price': 64000, 'fear': 20, 'btc_d': 55, 'total_oi': 0})
            second_count = mock_alert.sent_count

            self.log("クールダウン確認", first_count == 1 and second_count == 1,
                     f"1回目:{first_count}, 2回目:{second_count} (同一=クールダウン有効)")

        except Exception as e:
            self.log("クールダウン", False, traceback.format_exc())

    async def test_emergency_independent(self):
        print("\n[TEST 16] 緊急トリガー: 条件独立発火...")
        try:
            from src.core.report_scheduler import ReportScheduler

            class MockEngine:
                class state:
                    fear_greed = 20
                    regime = 'D'
                    regime_data = {}
                    @staticmethod
                    def get_tier1_passed(): return []
                    @staticmethod
                    def get_tier2_passed(): return []
                class regime:
                    @staticmethod
                    def get_action(): return 'test'
                class fetcher:
                    @staticmethod
                    async def fetch_ticker(s): return {'last': 65000, 'percentage': -6}
                class bot_alpha:
                    activated = False
                    last_activation = None
                class bot_surge:
                    activated = False
                class db:
                    @staticmethod
                    def get_open_positions(): return []
                class feedback:
                    @staticmethod
                    def get_accuracy_stats(): return {}

            class MockAlert:
                sent_count = 0
                async def send_market_report(self, rtype, data):
                    self.sent_count += 1
                    return True

            mock_alert = MockAlert()
            scheduler = ReportScheduler(MockEngine(), mock_alert, {
                'emergency': {
                    'btc_1h_pct': 5.0,
                    'fear_change': 10,
                    'cooldown_seconds': 7200,
                }
            })

            now = datetime.now()
            scheduler.btc_price_history.append((now - timedelta(hours=1), 70000))

            # BTC 1h トリガー
            await scheduler.check_emergency({'btc_price': 65000, 'fear': 30, 'btc_d': 55, 'total_oi': 0})
            after_btc = mock_alert.sent_count

            # Fearトリガー（BTC 1hはクールダウン中だがFearは独立）
            await scheduler.check_emergency({'btc_price': 65000, 'fear': 15, 'btc_d': 55, 'total_oi': 0})
            after_fear = mock_alert.sent_count

            self.log("独立発火確認", after_btc >= 1 and after_fear > after_btc,
                     f"BTC後:{after_btc}, Fear後:{after_fear} (異なる条件で独立発火)")

        except Exception as e:
            self.log("独立発火", False, traceback.format_exc())

    async def test_tier12_no_realtime_alert(self):
        print("\n[TEST 17] Tier1/2リアルタイム非送信確認...")
        try:
            from src.execution.alert import TelegramAlert
            from src.core.state import SymbolState

            # DB無しで初期化（ログ記録スキップ）
            alert = TelegramAlert(db=None)

            state = SymbolState(symbol='TEST/USDT:USDT')
            state.last_price = 100.0
            state.tier1_score = 50.0
            state.tier2_score = 30.0

            # send_tier2_alert は True を返すがTelegram送信しない
            result = await alert.send_tier2_alert(
                state, {'L02': {'reason': 'test'}}, {'L08': {'reason': 'test'}},
                'B', 'test', 35
            )
            self.log("Tier2アラート非送信", result is True, "ログのみ記録、Telegram送信なし")

            # send_regime_update も送信しない
            result = await alert.send_regime_update('B', 'test', 1.0, 0.5, 2.0, 35)
            self.log("Regime更新非送信", result is True, "ログのみ、Telegram送信なし")

        except Exception as e:
            self.log("非送信確認", False, traceback.format_exc())

    # ============================================
    # TEST 18: BTC.D / BTC価格 異常値ガードテスト
    # ============================================

    async def test_btc_d_sanity_check(self):
        print("\n[TEST 18] BTC.D異常値ガードテスト...")
        try:
            from src.signals.regime import RegimeDetector

            regime = RegimeDetector()

            # 正常値: 57%
            self.log("BTC.D正常値(57%)", regime._is_valid_btc_d(57.0), "range OK")

            # 異常値: 6% (今回のバグ)
            self.log("BTC.D異常値(6%)", not regime._is_valid_btc_d(6.0), "range外 → 拒否")

            # 異常値: 95%
            self.log("BTC.D異常値(95%)", not regime._is_valid_btc_d(95.0), "range外 → 拒否")

            # 境界値: 30%, 80%
            self.log("BTC.D境界(30%)", regime._is_valid_btc_d(30.0), "境界OK")
            self.log("BTC.D境界(80%)", regime._is_valid_btc_d(80.0), "境界OK")

            # _prev_btc_dに正常値をセット後、異常値が入ったら前回値が維持されることを確認
            regime._prev_btc_d = 57.0
            # 手動で異常値を受けた場合の挙動シミュレーション
            btc_d_raw = 6.0
            if regime._is_valid_btc_d(btc_d_raw):
                btc_d = btc_d_raw
            else:
                btc_d = regime._prev_btc_d
            self.log("異常値→前回値維持", btc_d == 57.0, f"入力=6.0% → 使用値={btc_d}%")

        except Exception as e:
            self.log("BTC.D異常値ガード", False, traceback.format_exc())

    async def test_emergency_false_trigger(self):
        print("\n[TEST 18b] 緊急トリガー誤発火防止テスト...")
        try:
            from src.core.report_scheduler import ReportScheduler

            class MockEngine:
                class state:
                    fear_greed = 20
                    regime = 'F'
                    regime_data = {}
                    @staticmethod
                    def get_tier1_passed(): return []
                    @staticmethod
                    def get_tier2_passed(): return []
                class regime:
                    @staticmethod
                    def get_action(): return 'test'
                class fetcher:
                    @staticmethod
                    async def fetch_ticker(s): return {'last': 70000, 'percentage': 0}
                class bot_alpha:
                    activated = False
                    last_activation = None
                class bot_surge:
                    activated = False
                class db:
                    @staticmethod
                    def get_open_positions(): return []
                class feedback:
                    @staticmethod
                    def get_accuracy_stats(): return {}

            class MockAlert:
                sent_count = 0
                async def send_market_report(self, rtype, data):
                    self.sent_count += 1
                    return True

            mock_alert = MockAlert()
            scheduler = ReportScheduler(MockEngine(), mock_alert, {
                'emergency': {'btc_d_daily_pct': 1.5, 'cooldown_seconds': 7200}
            })

            # 正常値をセット
            scheduler.last_btc_d = 57.0

            # BTC.D異常値6.0%が入力 → トリガー発火しないことを確認
            await scheduler.check_emergency({'btc_price': 70000, 'fear': 20, 'btc_d': 6.0, 'total_oi': 0})
            self.log("BTC.D異常値→トリガー不発火", mock_alert.sent_count == 0,
                     f"送信回数={mock_alert.sent_count} (0=正常)")

            # last_btc_dが上書きされていないことを確認
            self.log("BTC.D前回値維持", scheduler.last_btc_d == 57.0,
                     f"last_btc_d={scheduler.last_btc_d} (57.0のまま)")

            # BTC価格異常値テスト
            scheduler2 = ReportScheduler(MockEngine(), MockAlert(), {
                'emergency': {'btc_1h_pct': 5.0, 'cooldown_seconds': 7200}
            })
            self.log("BTC価格妥当性(70000)", scheduler2._is_valid_btc_price(70000), "正常")
            self.log("BTC価格異常値(0)", not scheduler2._is_valid_btc_price(0), "異常")
            self.log("BTC価格異常値(999999)", not scheduler2._is_valid_btc_price(999999), "異常")

            # Fear異常値テスト
            self.log("Fear妥当性(50)", scheduler2._is_valid_fear(50), "正常")
            self.log("Fear異常値(-5)", not scheduler2._is_valid_fear(-5), "異常")
            self.log("Fear異常値(150)", not scheduler2._is_valid_fear(150), "異常")

        except Exception as e:
            self.log("誤発火防止", False, traceback.format_exc())

    # ============================================
    # TEST 19: キャッシュマネージャーテスト
    # ============================================

    async def test_cache_manager(self):
        print("\n[TEST 19] キャッシュマネージャーテスト...")
        try:
            import time
            from src.data.cache_manager import CacheManager

            cm = CacheManager("data/cache_test")

            # メモリキャッシュ: set/get
            cm.set("fear_greed", 25)
            val = cm.get("fear_greed")
            self.log("メモリキャッシュ set/get", val == 25, f"val={val}")

            # メモリキャッシュ: sub_key
            cm.set("funding_rate", 0.001, "BTC/USDT:USDT")
            val = cm.get("funding_rate", "BTC/USDT:USDT")
            self.log("メモリキャッシュ sub_key", val == 0.001, f"val={val}")

            # メモリキャッシュ: 存在しないキー
            val = cm.get("nonexistent")
            self.log("メモリキャッシュ miss", val is None, f"val={val}")

            # ファイルキャッシュ: set/get
            cm.file_set("coingecko_id_map", {"BTC": "bitcoin", "ETH": "ethereum"})
            val = cm.file_get("coingecko_id_map")
            self.log("ファイルキャッシュ set/get", val is not None and val.get("BTC") == "bitcoin", f"keys={list(val.keys()) if val else 'None'}")

            # ファイルキャッシュ: 有効判定
            valid = cm.file_is_valid("coingecko_id_map")
            self.log("ファイルキャッシュ有効判定", valid, f"valid={valid}")

            # 手動無効化
            cm.invalidate("fear_greed")
            val = cm.get("fear_greed")
            self.log("手動無効化", val is None, f"val={val} (after invalidate)")

            # 統計
            stats = cm.stats()
            self.log("キャッシュ統計", stats['total'] > 0,
                     f"hits={stats['hits']}, misses={stats['misses']}, rate={stats['hit_rate_pct']}%")

            # テスト用キャッシュディレクトリ掃除
            import shutil
            shutil.rmtree("data/cache_test", ignore_errors=True)

        except Exception as e:
            self.log("キャッシュマネージャー", False, traceback.format_exc())

    # ============================================
    # TEST 20: バックテストエンジンテスト
    # ============================================

    async def test_backtest(self):
        print("\n[TEST 20] バックテストエンジンテスト...")
        try:
            from src.backtest.backtest_engine import BacktestEngine
            from src.data.database import HistoricalDB

            db = HistoricalDB()

            # 初期化テスト
            config_alpha = {'fear_threshold': 10, 'btc_return_threshold': -1.0,
                           'correlation_max': 0.5, 'alpha_min': 3.0,
                           'leverage': 3, 'position_size_pct': 30,
                           'take_profit_pct': 8.0, 'stop_loss_pct': 3.0}
            engine = BacktestEngine('alpha', config_alpha, db)
            self.log("BT初期化", engine.bot_type == 'alpha' and engine.initial_capital == 1_000_000,
                     f"type={engine.bot_type}, capital={engine.initial_capital}")

            # エントリーシミュレーション（コストは決済時一括控除方式）
            signal = {'symbol': 'TEST/USDT:USDT', 'price': 100.0, 'side': 'long'}
            trade = engine._simulate_entry(signal, 1_000_000, '2025-01-01')
            self.log("BTエントリー計算",
                     trade is not None and trade['position_value'] == 300_000
                     and trade['leverage'] == 3 and trade['entry_price'] == 100.0,
                     f"pos={trade['position_value']}, lev={trade['leverage']}, entry={trade['entry_price']:.4f}(raw)")

            # TP到達テスト（往復コスト0.22%一括控除: 8.0% - 0.22% = 7.78%）
            trade_tp = {
                'symbol': 'TEST/USDT:USDT', 'entry_date': '2025-01-01',
                'entry_price': 100.0, 'side': 'long', 'leverage': 3,
                'position_value': 300_000, 'tp_pct': 8.0, 'sl_pct': 3.0, 'max_holding_days': 14,
            }
            result_tp = engine._make_exit(trade_tp, 108.0, '2025-01-05', 4, 'TP')
            expected_tp_pnl = 8.0 - engine.ROUND_TRIP_COST_PCT  # 7.78%
            self.log("BTエグジットTP(コスト込)",
                     result_tp['raw_pnl_pct'] == 8.0
                     and result_tp['pnl_pct'] == expected_tp_pnl
                     and result_tp['pnl_leveraged_pct'] == round(expected_tp_pnl * 3, 2),
                     f"raw={result_tp['raw_pnl_pct']}%, net={result_tp['pnl_pct']}%, lev={result_tp['pnl_leveraged_pct']}%, cost={engine.ROUND_TRIP_COST_PCT}%/RT")

            # SL到達テスト（-3.0% - 0.22% = -3.22%）
            result_sl = engine._make_exit(trade_tp, 97.0, '2025-01-03', 2, 'SL')
            expected_sl_pnl = -3.0 - engine.ROUND_TRIP_COST_PCT  # -3.22%
            self.log("BTエグジットSL(コスト込)",
                     result_sl['raw_pnl_pct'] == -3.0
                     and result_sl['pnl_pct'] == expected_sl_pnl
                     and result_sl['pnl_leveraged_pct'] == round(expected_sl_pnl * 3, 2),
                     f"raw={result_sl['raw_pnl_pct']}%, net={result_sl['pnl_pct']}%, lev={result_sl['pnl_leveraged_pct']}%")

            # メトリクス計算テスト
            engine.trades = [
                {'symbol': 'A', 'entry_date': '2025-01', 'pnl_leveraged_pct': 24.0, 'pnl_amount': 72000, 'holding_days': 4},
                {'symbol': 'B', 'entry_date': '2025-02', 'pnl_leveraged_pct': -9.0, 'pnl_amount': -27000, 'holding_days': 2},
                {'symbol': 'C', 'entry_date': '2025-03', 'pnl_leveraged_pct': 15.0, 'pnl_amount': 45000, 'holding_days': 3},
            ]
            metrics = engine.calculate_metrics()
            self.log("BTメトリクス計算",
                     metrics['total_trades'] == 3 and metrics['win_rate'] == 66.7 and metrics['profit_factor'] == 4.33,
                     f"trades={metrics['total_trades']}, wr={metrics['win_rate']}%, pf={metrics['profit_factor']}")

            # Fear&Greedヒストリカル確認
            conn = db._get_conn()
            fg_count = conn.execute("SELECT COUNT(*) FROM fear_greed_history").fetchone()[0]
            conn.close()
            self.log("FG履歴データ", fg_count > 0, f"{fg_count}日分")

        except Exception as e:
            self.log("バックテスト", False, traceback.format_exc())

    # ============================================
    # TEST 21: ペーパートレーダーテスト
    # ============================================

    async def test_paper_tracker(self):
        print("\n[TEST 21] ペーパートレーダーテスト...")
        try:
            from src.core.paper_tracker import PaperTracker
            from src.data.database import HistoricalDB

            db = HistoricalDB()
            pt = PaperTracker(db)

            # シグナル記録
            sid = pt.record_signal('alpha', 'TEST/USDT:USDT', 'long', 100.0,
                                   leverage=3, take_profit_pct=8.0, stop_loss_pct=3.0)
            self.log("Paper記録", sid > 0, f"id={sid}")

            # オープン確認
            opens = pt.get_open_signals()
            self.log("Paperオープン取得", len(opens) > 0 and opens[0]['symbol'] == 'TEST/USDT:USDT',
                     f"{len(opens)}件")

            # 価格更新（TPには届かない）
            closed = pt.update_tracking({'TEST/USDT:USDT': 105.0})
            self.log("Paper更新(中間)", len(closed) == 0, "まだオープン")

            # TP到達
            closed = pt.update_tracking({'TEST/USDT:USDT': 108.5})
            self.log("PaperTP到達", len(closed) == 1 and closed[0]['exit_reason'] == 'TP',
                     f"PnL={closed[0]['realized_pnl_pct']:+.2f}%" if closed else "未クローズ")

            # サマリー
            summary = pt.get_summary()
            self.log("Paperサマリー", summary['closed'] >= 1,
                     f"total={summary['total_signals']} open={summary['open']} closed={summary['closed']}")

            # テストデータ削除
            conn = db._get_conn()
            conn.execute("DELETE FROM paper_signals WHERE symbol='TEST/USDT:USDT'")
            conn.commit()
            conn.close()

        except Exception as e:
            self.log("ペーパートレーダー", False, traceback.format_exc())

    # ============================================
    # TEST 22: ヘルスチェック・リトライテスト
    # ============================================

    async def test_retry_and_health(self):
        print("\n[TEST 22] リトライ・ヘルスチェックテスト...")
        try:
            from src.core.engine import retry_async

            # リトライテスト（成功ケース）
            call_count = [0]
            async def succeed_on_3rd():
                call_count[0] += 1
                if call_count[0] < 3:
                    raise Exception("temporary error")
                return "ok"

            result = await retry_async(succeed_on_3rd, max_retries=5, base_delay=0.1, label="test")
            self.log("リトライ成功", result == "ok" and call_count[0] == 3,
                     f"attempts={call_count[0]}")

            # リトライテスト（失敗ケース）
            async def always_fail():
                raise Exception("permanent error")

            try:
                await retry_async(always_fail, max_retries=2, base_delay=0.1, label="fail_test")
                self.log("リトライ失敗検知", False, "例外が発生すべき")
            except Exception:
                self.log("リトライ失敗検知", True, "max_retries超過で例外")

            # dry_runモード初期化
            from src.core.engine import EmpireMonitor
            monitor = EmpireMonitor(dry_run=True)
            self.log("DryRunモード", monitor.dry_run is True, f"dry_run={monitor.dry_run}")
            self.log("PaperTracker初期化", monitor.paper_tracker is not None, "PaperTracker ready")

        except Exception as e:
            self.log("リトライ・ヘルスチェック", False, traceback.format_exc())

    # ============================================
    # TEST 23: フルサイクル（v3.3統合）
    # ============================================

    async def test_full_cycle(self):
        print("\n[TEST 23] フルサイクルテスト...")
        try:
            from src.core.engine import EmpireMonitor
            monitor = EmpireMonitor()
            await monitor.initialize()
            self.log("初期化(v3.1)", True, f"{len(monitor.symbols)}銘柄, ReportScheduler統合")

            self.log("CacheManager統合", monitor.cache is not None, "CacheManager初期化OK")
            self.log("ReportScheduler初期化", monitor.report_scheduler is not None,
                     f"startup_sent={monitor.report_scheduler.startup_sent}")
            self.log("BotAlpha初期化", monitor.bot_alpha is not None, f"fear_threshold={monitor.bot_alpha.fear_threshold}")
            self.log("BotSurge初期化", monitor.bot_surge is not None, f"fear_range={monitor.bot_surge.fear_min}-{monitor.bot_surge.fear_max}")

            await monitor.scan_cycle()
            self.log("スキャンサイクル完了", True, f"T1:{monitor.daily_tier1_count} T2:{monitor.daily_tier2_count}")

            await monitor.fetcher.close()
        except Exception as e:
            self.log("フルサイクル", False, traceback.format_exc())

    # ============================================
    # 実行
    # ============================================

    async def run_all(self):
        print("=" * 60)
        print("🧪 Empire Monitor v3.3 システムテスト")
        print("   アラート体系改修 + ReportScheduler + 緊急トリガー")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        await self.test_env()
        alert = await self.test_telegram()
        await self.test_mexc()
        await self.test_database()
        await self.test_regime()
        await self.test_tier1()
        await self.test_tier2()
        await self.test_sector_mapping()
        await self.test_bot_alpha()
        await self.test_bot_surge()
        await self.test_report_startup()
        await self.test_report_daily_format()
        await self.test_emergency_btc_1h()
        await self.test_emergency_fear()
        await self.test_emergency_cooldown()
        await self.test_emergency_independent()
        await self.test_tier12_no_realtime_alert()
        await self.test_btc_d_sanity_check()
        await self.test_emergency_false_trigger()
        await self.test_cache_manager()
        await self.test_backtest()
        await self.test_paper_tracker()
        await self.test_retry_and_health()
        await self.test_full_cycle()

        print("\n" + "=" * 60)
        total = self.passed + self.failed
        pct = self.passed / total * 100 if total > 0 else 0
        print(f"📊 結果: {self.passed}/{total} テスト通過 ({pct:.0f}%)")
        print("=" * 60)

        if alert:
            report = f"🧪 <b>Empire Monitor v3.3 テスト結果</b>\n\n📊 {self.passed}/{total} ({pct:.0f}%)\n\n"
            for r in self.results:
                report += f"{html.escape(r)}\n"
            report += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            if len(report) > 4000:
                await alert.send_message(report[:4000] + "\n...(truncated)")
            else:
                await alert.send_message(report)
            print("📱 Telegram送信完了")

        return self.failed == 0

async def main():
    tester = SystemTester()
    success = await tester.run_all()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
