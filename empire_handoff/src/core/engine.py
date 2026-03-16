"""メインエンジン - DB統合・ポジション管理・デイリーサマリー対応・ペーパートレード"""
import asyncio
import gc
import logging
import time
import threading
import yaml
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler
from src.core.state import StateManager
from src.fetchers.ohlcv import MEXCFetcher
from src.signals.regime import RegimeDetector
from src.signals.tier1_engine import Tier1Engine
from src.signals.tier2_engine import Tier2Engine
from src.execution.alert import TelegramAlert
from src.signals.bot_alpha_engine import BotAlphaEngine
from src.signals.bot_surge_engine import BotSurgeEngine
from src.core.report_scheduler import ReportScheduler
from src.execution.position_manager import PositionManager
from src.execution.feedback import FeedbackLoop
from src.data.database import HistoricalDB
from src.data.cache_manager import CacheManager
from src.core.paper_tracker import PaperTracker
from src.core.veto import VetoSystem
from src.core.hot_signal_monitor import HotSignalMonitor
from src.data.funding_rate import FundingRateCollector
from src.signals.bot_levburn_engine import LevBurnEngine
from src.signals.bot_levburn_sec import LevBurnSecEngine
from src.execution.order_executor import OrderExecutor
from src.execution.live_position_manager import LivePositionManager
from src.core.api_manager import APIManager

def _setup_logger():
    """ファイルログ設定（10MB × 5ローテーション）"""
    Path("logs").mkdir(exist_ok=True)
    logger = logging.getLogger("empire")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = RotatingFileHandler(
            "logs/empire_monitor.log", maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(sh)
    return logger


async def retry_async(coro_func, *args, max_retries=5, base_delay=2.0, logger=None, label=""):
    """指数バックオフリトライ（2/4/8/16/32秒）"""
    for attempt in range(max_retries):
        try:
            return await coro_func(*args)
        except Exception as e:
            delay = base_delay * (2 ** attempt)
            msg = f"[Retry] {label} attempt {attempt+1}/{max_retries} failed: {e}. Waiting {delay}s"
            if logger:
                logger.warning(msg)
            else:
                print(msg)
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
            else:
                raise


class EmpireMonitor:
    def __init__(self, config_path: str = "config/settings.yaml", dry_run: bool = False,
                 bot_manager=None):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.dry_run = dry_run or self.config.get('dry_run', False)
        self.bot_manager = bot_manager
        self.logger = _setup_logger()

        self.cache = CacheManager()
        self.db = HistoricalDB()
        self.state = StateManager()
        # データ取得は常にMEXC公開API（認証不要）
        # 注文実行は settings.yaml の exchange で指定した取引所を使用
        self._data_exchange_config = {'name': 'mexc'}
        self._trading_exchange_config = self.config.get('exchange', {'name': 'mexc'})
        self.fetcher = MEXCFetcher(cache=self.cache, exchange_config=self._data_exchange_config)

        # 注文実行用取引所（認証あり、ライブ実行時のみ使用）
        self._trading_exchange = None

        # PNL管理: TradeRecorder + RiskManager
        from src.core.trade_recorder import TradeRecorder
        from src.core.risk_manager import RiskManager
        from src.core.portfolio_manager import PortfolioManager
        self.trade_recorder = TradeRecorder(self.db)
        self.risk_manager = RiskManager(self.db, self.config.get('risk_management', {}))
        self.portfolio_manager = PortfolioManager(self.db)
        self.regime = RegimeDetector(cache=self.cache)
        self.tier1 = Tier1Engine(self.config.get('tier1_params', {}))
        self.tier2 = Tier2Engine(self.config.get('tier2_params', {}))
        self.alert = TelegramAlert(db=self.db)
        self.bot_alpha = BotAlphaEngine(self.config.get('bot_alpha', {}), self.db)
        self.bot_surge = BotSurgeEngine(self.config.get('bot_surge', {}), self.db)
        self.position_mgr = PositionManager(self.db, self.alert, self.config.get('trade_params', {}))
        self.feedback = FeedbackLoop(self.db, self.fetcher)
        self.report_scheduler = ReportScheduler(self, self.alert, self.config.get('report', {}))

        # Bot活動ログ
        from src.core.bot_activity_logger import BotActivityLogger
        self.activity_logger = BotActivityLogger(self.db)
        self._session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.activity_logger.log_event('system', 'start', details='Engine起動',
                                        session_id=self._session_id)
        self.paper_tracker = PaperTracker(self.db, trade_recorder=self.trade_recorder,
                                              portfolio_manager=self.portfolio_manager)
        self.veto = VetoSystem(self.config)
        hot_cfg = self.config.get('hot_signal', {})
        self.hot_monitor = HotSignalMonitor(hot_cfg, self.fetcher, self.db) if hot_cfg.get('enabled', False) else None
        levburn_cfg = self.config.get('leverage_burn', {})
        if levburn_cfg.get('enabled', False):
            self.fr_collector = FundingRateCollector(self.fetcher.exchange, self.cache, db=self.db)
            self.levburn_engine = LevBurnEngine(levburn_cfg)
            self.levburn_interval = levburn_cfg.get('scan_interval_minutes', 30) * 60
            self.levburn_max_symbols = levburn_cfg.get('max_scan_symbols', 50)
        else:
            self.fr_collector = None
            self.levburn_engine = None
            self.levburn_interval = 1800
            self.levburn_max_symbols = 50
        # ============================================================
        # データソース優先ルール (REST / WebSocket)
        # ------------------------------------------------------------
        # WS enabled かつ connected → WS ticker データを使用
        #   - _collect_fr_data_for_sec() で WS ticker FR を最優先参照
        #   - LevBurn-Sec エンジンは WS 1秒足を直接利用
        # WS disabled または未接続 → REST (MEXCFetcher) へフォールバック
        #   - Tier1/Tier2 スキャンは常に REST OHLCV を使用
        #   - FR データは CacheManager 経由の REST 結果を参照
        # ============================================================
        # WebSocket リアルタイムフィード
        ws_cfg = self.config.get('websocket', {})
        if ws_cfg.get('enabled', False):
            from src.data.websocket_feed import create_ws_feed
            exchange_name = self._data_exchange_config.get('name', 'mexc')
            self.ws_feed = create_ws_feed(
                symbols=[],
                callbacks={},
                config=ws_cfg,
                exchange_name=exchange_name,
            )
        else:
            self.ws_feed = None

        # LevBurn-Sec エンジン初期化 (2段階アーキテクチャ)
        # 第1段階: WS ticker FR → ホットリスト (ws_feed内で自動判定)
        # 第2段階: ホットリスト銘柄のみ独立スレッドで秒スキャン
        self._levburn_sec_engines = {}
        self._levburn_sec_interval = 5  # 秒スキャ間隔
        self._levburn_sec_stop = threading.Event()
        self._levburn_sec_thread = None
        self._main_loop = None  # run()でセット、LevBurn-Secスレッドからのディスパッチ用
        _SEC_VARIANT_MAP = {
            "standard": "bot_levburn_sec",
            "aggressive": "bot_levburn_sec_aggressive",
            "conservative": "bot_levburn_sec_conservative",
            "scalp_micro": "bot_levburn_sec_scalp_micro",
            "fr_extreme_only": "bot_levburn_sec_fr_extreme",
            # レバ1x固定版
            "standard_lev1": "bot_levburn_sec_lev1",
            "aggressive_lev1": "bot_levburn_sec_aggressive_lev1",
            "conservative_lev1": "bot_levburn_sec_conservative_lev1",
            "scalp_micro_lev1": "bot_levburn_sec_scalp_micro_lev1",
            "fr_extreme_only_lev1": "bot_levburn_sec_fr_extreme_lev1",
            # レバ3x固定版
            "standard_lev3": "bot_levburn_sec_lev3",
            "aggressive_lev3": "bot_levburn_sec_aggressive_lev3",
            "conservative_lev3": "bot_levburn_sec_conservative_lev3",
            "scalp_micro_lev3": "bot_levburn_sec_scalp_micro_lev3",
            "fr_extreme_only_lev3": "bot_levburn_sec_fr_extreme_lev3",
            # Aggressive最適化版
            "agg_lev1": "bot_levburn_sec_agg_lev1",
            "agg_lev3_ls": "bot_levburn_sec_agg_lev3_ls",
            "agg_lev1_fr": "bot_levburn_sec_agg_lev1_fr",
            "agg_lev3_fr": "bot_levburn_sec_agg_lev3_fr",
            "agg_7x": "bot_levburn_sec_agg_7x",
            "agg_7x_so": "bot_levburn_sec_agg_7x_so",
            "agg_7x_fr": "bot_levburn_sec_agg_7x_fr",
            # Evolved全部盛り版
            "evo_agg": "bot_levburn_sec_evo_agg",
            "evo_micro": "bot_levburn_sec_evo_micro",
            "evo_lev1": "bot_levburn_sec_evo_lev1",
        }
        _SEC_BOTKEY_MAP = {
            "standard": "levburn_sec",
            "aggressive": "levburn_sec_aggressive",
            "conservative": "levburn_sec_conservative",
            "scalp_micro": "levburn_sec_scalp_micro",
            "fr_extreme_only": "levburn_sec_fr_extreme",
            # レバ1x固定版
            "standard_lev1": "levburn_sec_lev1",
            "aggressive_lev1": "levburn_sec_aggressive_lev1",
            "conservative_lev1": "levburn_sec_conservative_lev1",
            "scalp_micro_lev1": "levburn_sec_scalp_micro_lev1",
            "fr_extreme_only_lev1": "levburn_sec_fr_extreme_lev1",
            # レバ3x固定版
            "standard_lev3": "levburn_sec_lev3",
            "aggressive_lev3": "levburn_sec_aggressive_lev3",
            "conservative_lev3": "levburn_sec_conservative_lev3",
            "scalp_micro_lev3": "levburn_sec_scalp_micro_lev3",
            "fr_extreme_only_lev3": "levburn_sec_fr_extreme_lev3",
            # Aggressive最適化版
            "agg_lev1": "levburn_sec_agg_lev1",
            "agg_lev3_ls": "levburn_sec_agg_lev3_ls",
            "agg_lev1_fr": "levburn_sec_agg_lev1_fr",
            "agg_lev3_fr": "levburn_sec_agg_lev3_fr",
            "agg_7x": "levburn_sec_agg_7x",
            "agg_7x_so": "levburn_sec_agg_7x_so",
            "agg_7x_fr": "levburn_sec_agg_7x_fr",
            # Evolved全部盛り版
            "evo_agg": "levburn_sec_evo_agg",
            "evo_micro": "levburn_sec_evo_micro",
            "evo_lev1": "levburn_sec_evo_lev1",
        }
        if self.ws_feed:
            for variant_name, config_key in _SEC_VARIANT_MAP.items():
                bot_key = _SEC_BOTKEY_MAP[variant_name]
                sec_config = self.config.get(config_key, {})
                self._levburn_sec_engines[bot_key] = LevBurnSecEngine(
                    self.ws_feed, fr_collector=self.fr_collector,
                    variant=variant_name, config=sec_config,
                )

        # ============================================================
        # ライブ注文実行レイヤー
        # ============================================================
        self.api_manager = APIManager(self.config)
        self.order_executor = None
        self.live_pos_mgr = None
        self._live_exec_config_path = config_path
        self._live_exec_mtime = 0  # yaml更新日時追跡
        self._live_exec_lock = threading.RLock()  # order_executor保護用ロック
        self._reload_live_execution(force=True)

        self.last_levburn_scan: datetime = None
        self.last_watchlist_report: datetime = None
        self.symbols: list = []
        self.running = False
        self.last_regime_update = None
        self.last_data_update = None
        self.last_daily_summary = None
        self.last_health_check = None
        self.daily_tier1_count = 0
        self.daily_tier2_count = 0
        self.daily_alert_count = 0
        self.daily_top_symbols = []
        self.cycle_count = 0
        self.error_count = 0
        self.start_time = None

    def _lookup_trade_serial(self, bot_name: str, symbol: str) -> str:
        """直近のtrade_recordsからシリアル番号を取得"""
        try:
            conn = self.db._get_conn()
            row = conn.execute(
                "SELECT trade_serial FROM trade_records WHERE bot_name=? AND symbol=? ORDER BY id DESC LIMIT 1",
                (bot_name, symbol)
            ).fetchone()
            conn.close()
            return row[0] if row and row[0] else ''
        except Exception:
            return ''

    def _get_bot_config(self, bot_name: str) -> dict:
        """settings.yamlからBot設定を取得"""
        return self.config.get(f'bot_{bot_name}', {})

    def _should_run_bot(self, bot_name: str) -> str:
        """BotManagerからモードを取得。BotManagerなしなら後方互換でpaper実行"""
        if self.bot_manager is None:
            return "paper"
        worker = self.bot_manager.workers.get(bot_name)
        if worker is None:
            return "disabled"
        return worker.mode.value

    def _update_bot_status(self, bot_name: str, status: str, last_signal=None):
        """BotWorkerの状態を更新（GUI表示用）"""
        if self.bot_manager is None:
            return
        worker = self.bot_manager.workers.get(bot_name)
        if worker:
            worker.status = status
            worker.stats["cycles"] += 1
            if last_signal:
                worker.record_signal(last_signal)

    def _reload_live_execution(self, force: bool = False):
        """settings.yamlからlive_execution設定を再読込し、Executor/PosMgrを再初期化。
        ファイル更新日時が変わった場合のみ読込（毎サイクルの無駄I/Oを回避）。
        _live_exec_lock で保護し、levburn_secスレッドとの競合を防止。"""
        import os
        try:
            mtime = os.path.getmtime(self._live_exec_config_path)
            if not force and mtime == self._live_exec_mtime:
                return  # 変更なし
            self._live_exec_mtime = mtime

            with open(self._live_exec_config_path, 'r') as f:
                fresh_config = yaml.safe_load(f)
            live_cfg = fresh_config.get('live_execution', {})
        except Exception as e:
            self.logger.error(f"[Engine] live_execution config reload failed: {e}")
            return

        with self._live_exec_lock:
            now_enabled = live_cfg.get('enabled', False)
            was_enabled = self.order_executor is not None

            if now_enabled and not was_enabled:
                # OFF → ON: 注文用取引所を生成（認証付き）
                if self._trading_exchange is None:
                    from src.exchange.exchange_factory import create_exchange as _create_ex
                    self._trading_exchange = _create_ex(self._trading_exchange_config)
                    self.logger.info(f"[Engine] 注文用取引所: {self._trading_exchange_config.get('name', 'mexc')}")
                self.order_executor = OrderExecutor(
                    self._trading_exchange, live_cfg, self.db, self.alert,
                    api_manager=self.api_manager,
                    trade_recorder=self.trade_recorder,
                )
                # DBからTP/SL注文IDを復元 (H2)
                self.order_executor.restore_active_orders()
                self.live_pos_mgr = LivePositionManager(
                    self._trading_exchange, self.db, self.alert, live_cfg,
                    order_executor=self.order_executor
                )
                self.logger.info("[Engine] ライブ注文実行レイヤー有効化（ホットリロード）")

            elif now_enabled and was_enabled:
                # ON → ON: 設定値だけ更新（Executorインスタンスは維持）
                self.order_executor.config = live_cfg
                self.order_executor.max_positions = live_cfg.get('max_positions', 3)
                self.order_executor.max_daily_loss_pct = live_cfg.get('max_daily_loss_pct', 5.0)
                self.order_executor.min_balance_usd = live_cfg.get('min_balance_usd', 50.0)
                self.order_executor.position_size_cap_usd = live_cfg.get('position_size_cap_usd', 500.0)
                self.order_executor.default_margin_type = live_cfg.get('default_margin_type', 'cross')
                self.order_executor.slippage_tolerance_pct = live_cfg.get('slippage_tolerance_pct', 0.5)
                self.order_executor.dry_run_first = live_cfg.get('dry_run_first', True)
                self.order_executor.allowed_bots = live_cfg.get('allowed_bots', [])
                self.order_executor._max_consecutive_losses = live_cfg.get('max_consecutive_losses', 5)
                self.live_pos_mgr._sync_interval = live_cfg.get('sync_interval_seconds', 60)

            elif not now_enabled and was_enabled:
                # ON → OFF: 停止 (I-1: オープンポジション警告)
                open_positions = self.db.get_open_positions()
                live_positions = [p for p in open_positions
                                  if p.get('notes', '').startswith('LIVE')]
                if live_positions:
                    n = len(live_positions)
                    syms = ', '.join(p['symbol'] for p in live_positions[:5])
                    msg = (f"⚠️ live_execution無効化。オープンポジション{n}件あり。\n"
                           f"銘柄: {syms}\n"
                           f"取引所側のTP/SLは有効ですが、監視が停止します。")
                    self.logger.warning(f"[Engine] {msg}")
                    # asyncイベントループからの通知（syncコンテキストなのでrun_coroutine_threadsafe使用）
                    if self._main_loop:
                        import asyncio
                        asyncio.run_coroutine_threadsafe(
                            self.alert.send_message(msg), self._main_loop
                        )
                self.order_executor = None
                self.live_pos_mgr = None
                self.logger.info("[Engine] ライブ注文実行レイヤー無効化（ホットリロード）")

    async def _execute_live_signal(self, bot_name: str, entry: dict) -> bool:
        """ライブモードの共通実行メソッド。全Botから呼ばれる。
        _live_exec_lock で保護し、reload中のExecutor差し替えと競合しない。

        Args:
            bot_name: Bot名 ("alpha", "surge", "levburn" 等)
            entry: シグナルのentryデータ

        Returns:
            True if execution succeeded
        """
        # リスクリミットチェック
        if self.risk_manager and self.risk_manager.is_order_stopped:
            self.logger.warning(f"[LIVE] {bot_name}: リスクリミット超過により新規注文停止中")
            await self.alert.send_message(
                f"⚠️ {bot_name} リスクリミット超過のため新規注文をブロックしました。"
                f"Settings画面でRisk Managementを確認してください。"
            )
            return False

        with self._live_exec_lock:
            executor = self.order_executor
        if not executor:
            self.logger.warning(f"[LIVE] {bot_name}: live_execution が settings.yaml で無効です")
            await self.alert.send_message(
                f"⚠️ {bot_name} がLIVEモードですが live_execution.enabled=false のため実注文は送信されません。"
                f"Settings画面でLive Executionを有効化してください。"
            )
            return False

        # シグナルを標準フォーマットに正規化
        signal = {
            'symbol': entry.get('symbol'),
            'side': entry.get('side', 'long'),
            'entry_price': entry.get('entry_price', entry.get('price', 0)),
            'leverage': entry.get('leverage', 3),
            'position_size_pct': entry.get('position_size_pct', entry.get('position_pct', 20)),
            'take_profit_pct': entry.get('take_profit_pct', entry.get('tp_pct', 5.0)),
            'stop_loss_pct': entry.get('stop_loss_pct', entry.get('sl_pct', 2.0)),
        }

        result = await executor.execute_entry(bot_name, signal)

        if result['success']:
            tp_pct = signal['take_profit_pct']
            sl_pct = signal['stop_loss_pct']
            lev = signal['leverage']
            fill_price = result['entry_order'].get('average') or result['entry_order'].get('price') or signal['entry_price']
            msg = (f"✅ <b>LIVE FILL: {bot_name.upper()}</b>\n"
                   f"  銘柄: {signal['symbol']}\n"
                   f"  方向: {signal['side'].upper()} {lev}x\n"
                   f"  約定: ${fill_price:,.6f}\n"
                   f"  TP: +{tp_pct}% / SL: -{sl_pct}%\n"
                   f"  TP/SL注文: {'✅' if result['tp_order'] and result['sl_order'] else '⚠️要確認'}")
            await self.alert.send_message(msg)
            self.logger.info(f"[LIVE] {bot_name} ENTRY: {signal['symbol']} {signal['side']} @ {fill_price}")
            self.activity_logger.log_signal(
                bot_name, signal['symbol'], signal['side'], signal['leverage'],
                fill_price, signal['take_profit_pct'], signal['stop_loss_pct'], mode='live')
        else:
            msg = (f"❌ <b>LIVE FAIL: {bot_name.upper()}</b>\n"
                   f"  銘柄: {signal['symbol']}\n"
                   f"  エラー: {result['error']}")
            await self.alert.send_message(msg)
            self.logger.warning(f"[LIVE] {bot_name} FAILED: {signal['symbol']} - {result['error']}")

        # ペーパーにも並行記録（比較用）
        self.paper_tracker.record_signal(
            bot_name, signal['symbol'], signal['side'],
            signal['entry_price'], signal['leverage'],
            signal['position_size_pct'],
            signal['take_profit_pct'], signal['stop_loss_pct'],
            notes=f'LIVE {bot_name} {"OK" if result["success"] else "FAIL:" + result["error"]}'
        )

        return result['success']

    def _is_risk_blocked(self, bot_name: str) -> bool:
        """リスクリミットチェック。ペーパー含む全シグナルで呼ぶ。"""
        if not self.risk_manager:
            return False
        if self.risk_manager.is_order_stopped:
            self.logger.warning(f"[Risk] {bot_name}: リスクリミット超過 — 新規シグナルをブロック")
            return True
        # ポートフォリオ別リミットチェック
        if self.portfolio_manager:
            pid = self.portfolio_manager.get_portfolio_for_bot(bot_name)
            if pid:
                portfolio = self.portfolio_manager.get(pid)
                if portfolio:
                    self.risk_manager.check_limits(pid, portfolio['initial_capital'])
                    if self.risk_manager.is_order_stopped:
                        self.logger.warning(f"[Risk] {bot_name}: portfolio {pid} リミット超過")
                        return True
        return False

    # エンジン実装済みBot（これ以外はステータス一括更新対象）
    _ENGINE_IMPLEMENTED_BOTS = {
        "alpha", "surge", "levburn",
        "levburn_sec", "levburn_sec_aggressive", "levburn_sec_conservative",
        "levburn_sec_scalp_micro", "levburn_sec_fr_extreme",
        # レバ1x固定版
        "levburn_sec_lev1", "levburn_sec_aggressive_lev1", "levburn_sec_conservative_lev1",
        "levburn_sec_scalp_micro_lev1", "levburn_sec_fr_extreme_lev1",
        # レバ3x固定版
        "levburn_sec_lev3", "levburn_sec_aggressive_lev3", "levburn_sec_conservative_lev3",
        "levburn_sec_scalp_micro_lev3", "levburn_sec_fr_extreme_lev3",
        # Aggressive最適化版
        "levburn_sec_agg_lev1", "levburn_sec_agg_lev3_ls",
        "levburn_sec_agg_lev1_fr", "levburn_sec_agg_lev3_fr",
        "levburn_sec_agg_7x", "levburn_sec_agg_7x_so", "levburn_sec_agg_7x_fr",
        # Evolved全部盛り版
        "levburn_sec_evo_agg", "levburn_sec_evo_micro", "levburn_sec_evo_lev1",
    }

    def _update_unimplemented_bots(self, fg: int):
        """エンジン未実装Botのステータスを設定（GUI表示用）。
        disabled → disabled, それ以外 → waiting（シグナルエンジン未実装のため）。
        """
        if self.bot_manager is None:
            return
        for bot_name, worker in self.bot_manager.workers.items():
            if bot_name in self._ENGINE_IMPLEMENTED_BOTS:
                continue  # 実装済みBotはスキップ
            mode = self._should_run_bot(bot_name)
            if mode == "disabled":
                worker.status = "disabled"
            else:
                worker.status = "waiting"
            worker.stats["cycles"] += 1

    def _get_db_stats(self) -> dict:
        conn = self.db._get_conn()
        c = conn.cursor()
        stats = {}
        stats['ohlcv_1d'] = c.execute("SELECT COUNT(*) FROM ohlcv WHERE timeframe='1d'").fetchone()[0]
        stats['ohlcv_1h'] = c.execute("SELECT COUNT(*) FROM ohlcv WHERE timeframe='1h'").fetchone()[0]
        stats['sanctuary'] = c.execute("SELECT COUNT(*) FROM sanctuary").fetchone()[0]
        stats['sector'] = c.execute("SELECT COUNT(*) FROM sector WHERE primary_sector != 'Unknown'").fetchone()[0]
        stats['watchlist'] = c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        stats['positions'] = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
        conn.close()
        return stats

    async def initialize(self):
        print("[Init] 銘柄リスト取得中...")
        self.symbols = await self.fetcher.fetch_futures_symbols()
        print(f"[Init] {len(self.symbols)} 銘柄を監視対象に設定")

        print("[Init] 市場環境判定中...")
        await self.update_regime()

        db_stats = self._get_db_stats()
        print(f"[Init] 完了。パターン: {self.state.regime}, F&G: {self.state.fear_greed}")
        print(f"[Init] DB: 日足{db_stats['ohlcv_1d']:,}件, 1h足{db_stats['ohlcv_1h']:,}件, 聖域{db_stats['sanctuary']}件")

        # 起動レポート送信
        await self.report_scheduler.on_startup()

    async def update_regime(self):
        global_data = await self.regime.fetch_global_data()
        fg = await self.regime.fetch_fear_greed()
        self.state.fear_greed = fg

        if not global_data:
            return

        btc_ticker = await self.fetcher.fetch_ticker('BTC/USDT:USDT')
        btc_change = btc_ticker.get('percentage', 0) if btc_ticker else 0
        dom_change = global_data.get('btc_d_change', 0)
        total_change = global_data.get('market_cap_change_24h', 0)

        pattern = self.regime.classify(btc_change, dom_change, total_change)
        old_pattern = self.state.regime
        self.state.regime = pattern
        self.state.regime_data = global_data

        # パターンC遷移 → 全ポジション警告（リアルタイムアラート）
        if pattern == 'C' and old_pattern != 'C':
            positions = self.db.get_open_positions()
            if positions:
                await self.alert.send_pattern_c_alert(len(positions))

        self.last_regime_update = datetime.now()

    async def update_historical_data(self):
        """定期的にヒストリカルデータを更新（1時間ごと）"""
        print("[Data] ヒストリカルデータ更新中...")
        count = 0
        for symbol in self.symbols[:200]:  # レート制限考慮で上位200銘柄
            try:
                df_1h = await self.fetcher.fetch_ohlcv(symbol, '1h', 50)
                if df_1h is not None:
                    self.db.upsert_ohlcv(symbol, '1h', df_1h)
                    count += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        print(f"[Data] {count}銘柄の1h足を更新")
        self.last_data_update = datetime.now()

    async def scan_cycle(self):
        # GUI設定変更をホットリロード
        self._reload_live_execution()

        interval = self.config['monitoring']['regime_update_interval']
        if (self.last_regime_update is None or
            datetime.now() - self.last_regime_update > timedelta(seconds=interval)):
            await self.update_regime()

        # ヒストリカルデータ更新（毎時）
        if (self.last_data_update is None or
            datetime.now() - self.last_data_update > timedelta(hours=1)):
            await self.update_historical_data()

        tickers = await self.fetcher.fetch_all_tickers()
        if not tickers:
            print("[Scan] ティッカー取得失敗")
            return

        # ポジション監視
        current_prices = {s: t.get('last', 0) for s, t in tickers.items()}
        await self.position_mgr.check_positions(current_prices)

        # BTC基準データ（メモリキャッシュ: 5分）
        cached_btc_1h = self.cache.get("btc_ohlcv_1h")
        if cached_btc_1h is not None:
            btc_closes = cached_btc_1h
        else:
            btc_ohlcv = await self.fetcher.fetch_ohlcv('BTC/USDT:USDT', '1h', 168)
            btc_closes = btc_ohlcv['close'].tolist() if btc_ohlcv is not None else []
            if btc_closes:
                self.cache.set("btc_ohlcv_1h", btc_closes)

        # 一括読込（ループ内で毎回DB呼出しない）
        cached_sector_map = self.cache.get("sector_map")
        if cached_sector_map is not None:
            sector_map = cached_sector_map
        else:
            conn = self.db._get_conn()
            sector_map = {r[0]: r[1] for r in conn.execute("SELECT symbol, primary_sector FROM sector WHERE is_crypto = 1").fetchall()}
            conn.close()
            self.cache.set("sector_map", sector_map)

        # 非クリプト銘柄セット（スキャン除外用）
        cached_non_crypto = self.cache.get("non_crypto_set")
        if cached_non_crypto is not None:
            non_crypto_set = cached_non_crypto
        else:
            conn = self.db._get_conn()
            non_crypto_set = {r[0] for r in conn.execute("SELECT symbol FROM sector WHERE is_crypto = 0").fetchall()}
            conn.close()
            self.cache.set("non_crypto_set", non_crypto_set)

        cached_watchlist = self.cache.get("watchlist")
        if cached_watchlist is not None:
            watchlist_set = cached_watchlist
        else:
            watchlist_set = set(self.db.get_watchlist())
            self.cache.set("watchlist", watchlist_set)

        cached_sanctuary = self.cache.get("sanctuary_map")
        if cached_sanctuary is not None:
            sanctuary_map = cached_sanctuary
        else:
            conn = self.db._get_conn()
            sanctuary_map = {r[0]: r[1] for r in conn.execute("SELECT symbol, sanctuary_price FROM sanctuary").fetchall()}
            conn.close()
            self.cache.set("sanctuary_map", sanctuary_map)

        tier1_passed = []
        scan_count = 0

        for symbol, ticker in tickers.items():
            # 非クリプト銘柄はスキャン対象外
            if symbol in non_crypto_set:
                continue

            state = self.state.get_or_create(symbol)
            state.last_price = ticker.get('last', 0)
            state.last_updated = datetime.now()

            # セクター情報（一括読込済み）
            sector = sector_map.get(symbol)
            if sector:
                state.sector = sector

            vol = ticker.get('quoteVolume', 0) or 0
            change_pct = ticker.get('percentage', 0) or 0

            is_watched = symbol in watchlist_set

            if abs(change_pct) >= 3.0 or vol > 1000000 or is_watched:
                # DBからヒストリカルデータ取得（APIコール削減）
                db_1d = self.db.get_ohlcv(symbol, '1d', 210)
                if db_1d is not None and len(db_1d) >= 200:
                    state.ohlcv_1d = db_1d
                else:
                    ohlcv_1d = await self.fetcher.fetch_ohlcv(symbol, '1d', 210)
                    if ohlcv_1d is not None:
                        state.ohlcv_1d = ohlcv_1d
                        self.db.upsert_ohlcv(symbol, '1d', ohlcv_1d)

                ohlcv_1m = await self.fetcher.fetch_ohlcv(symbol, '1m', 30)
                if ohlcv_1m is not None:
                    state.ohlcv_1m = ohlcv_1m

                # BTC相関・アルファ（キャッシュ: 1時間有効）
                cached_corr = self.cache.get("btc_correlation", symbol) if self.cache else None
                if cached_corr is not None:
                    state.btc_correlation = cached_corr['corr']
                    state.btc_alpha = cached_corr['alpha']
                else:
                    db_1h = self.db.get_ohlcv(symbol, '1h', 168)
                    if db_1h is not None and len(db_1h) >= 20:
                        sym_closes = db_1h['close'].tolist()
                    else:
                        ohlcv_1h = await self.fetcher.fetch_ohlcv(symbol, '1h', 168)
                        sym_closes = ohlcv_1h['close'].tolist() if ohlcv_1h is not None else []

                    if len(btc_closes) >= 20 and len(sym_closes) >= 20:
                        import numpy as np
                        btc_ret = np.diff(btc_closes[-21:]) / btc_closes[-21:-1]
                        sym_ret = np.diff(sym_closes[-21:]) / sym_closes[-21:-1]
                        if len(btc_ret) == len(sym_ret):
                            corr = np.corrcoef(btc_ret, sym_ret)[0, 1]
                            state.btc_correlation = float(corr) if not np.isnan(corr) else 1.0
                            state.btc_alpha = (sym_ret[-1] - btc_ret[-1]) * 100
                            self.cache.set("btc_correlation", {
                                'corr': state.btc_correlation,
                                'alpha': state.btc_alpha,
                            }, symbol)

                # 聖域価格（一括読込済み）
                sanctuary = sanctuary_map.get(symbol)

                # Tier 1実行（聖域価格をDBから渡す）
                t1_results = self.tier1.run(state)
                if sanctuary:
                    t1_results['L02'] = self.tier1.l02_alpha_sanctuary(state, sanctuary)
                    if not t1_results['L02']['passed']:
                        state.tier1_passed = False

                if state.tier1_passed:
                    tier1_passed.append((state, t1_results))

                scan_count += 1
                await asyncio.sleep(0.05)

        self.daily_tier1_count = len(tier1_passed)
        self.logger.info(f"[Tier1] {len(tier1_passed)}/{scan_count}スキャン中 通過")

        # Tier1スコア上位50銘柄のみTier2に送る（レートリミット対策）
        tier1_passed.sort(key=lambda x: x[0].tier1_score, reverse=True)
        tier1_top = tier1_passed[:50]
        if len(tier1_passed) > 50:
            print(f"[Tier2] Tier1通過{len(tier1_passed)}件 → 上位50件に絞り込み")

        tier2_passed = []
        for state, t1_results in tier1_top:
            ob = await self.fetcher.fetch_orderbook(state.symbol)
            if ob:
                state.orderbook_depth_usd = ob['total_depth_usd']

            fr = await self.fetcher.fetch_funding_rate(state.symbol)
            if fr is not None:
                state.funding_rate = fr

            t2_results = self.tier2.run(state)
            if state.tier2_passed:
                tier2_passed.append((state, t1_results, t2_results))
            await asyncio.sleep(1.0)  # MEXC 510対策: 1秒間隔

        self.daily_tier2_count = len(tier2_passed)
        self.logger.info(f"[Tier2] {len(tier2_passed)}/{len(tier1_passed)} 通過")

        for state, t1_results, t2_results in tier2_passed:
            # Tier2通過はログ記録のみ（リアルタイムアラート送信しない）
            await self.alert.send_tier2_alert(
                state, t1_results, t2_results,
                self.state.regime, self.regime.get_action(),
                self.state.fear_greed
            )
            self.daily_alert_count += 1
            self.daily_top_symbols.append({
                'symbol': state.symbol,
                'score': state.tier1_score + state.tier2_score
            })

        # === Bot-Alpha / Bot-Surge スキャン ===
        await self._run_bot_engines(tickers, btc_closes)

        # === レバ焼きスキャン（30分間隔） ===
        if self.fr_collector and self.levburn_engine:
            if (self.last_levburn_scan is None or
                (datetime.now() - self.last_levburn_scan).total_seconds() >= self.levburn_interval):
                await self._run_levburn_scan(tier1_passed, tickers)

        # LevBurn-Sec は独立スレッドで5秒間隔実行（_levburn_sec_loop）

        # === 激アツ自動監視 ===
        if self.hot_monitor:
            await self._run_hot_signal_monitor(tier2_passed)

        # フィードバック更新（毎サイクル、負荷軽微）
        try:
            updated = await self.feedback.update_feedback()
            if updated > 0:
                print(f"[Feedback] {updated}件のアラート精度を更新")
        except Exception:
            pass

        # レポートスケジューラー
        await self.report_scheduler.check_daily()

        # 緊急レポートチェック
        btc_ticker = tickers.get('BTC/USDT:USDT', {})
        btc_price = btc_ticker.get('last', 0) or 0
        regime_data = getattr(self.state, 'regime_data', {}) or {}
        await self.report_scheduler.check_emergency({
            'btc_price': btc_price,
            'fear': self.state.fear_greed,
            'btc_d': regime_data.get('btc_dominance', 0),
            'total_oi': 0,  # OI集計は将来実装
        })

        # キャッシュ統計
        cs = self.cache.stats()
        if cs['total'] > 0:
            print(f"[Cache] hits:{cs['hits']} misses:{cs['misses']} rate:{cs['hit_rate_pct']}%")

    async def _run_bot_engines(self, tickers: dict, btc_closes: list):
        """Bot-Alpha & Bot-Surge エンジン実行"""
        fg = self.state.fear_greed

        # BTC日次リターン
        btc_ticker = tickers.get('BTC/USDT:USDT', {})
        btc_daily_return = btc_ticker.get('percentage', 0) or 0

        # BTC.D変化（regime_dataから取得 — btc_d_changeは前回値との実差分）
        btc_d_change = 0
        if hasattr(self.state, 'regime_data') and self.state.regime_data:
            btc_d_change = self.state.regime_data.get('btc_d_change', 0)

        # 銘柄データ構築（Bot用）
        symbols_data = []
        for symbol, ticker in tickers.items():
            state = self.state.get_or_create(symbol)
            symbols_data.append({
                'symbol': symbol,
                'correlation': state.btc_correlation,
                'alpha': state.btc_alpha,
                'btc_divergence': state.btc_alpha,  # 対BTC騰落率差
                'price': ticker.get('last', 0),
                'sector': state.sector or 'Unknown',
                'rsi': getattr(state, 'rsi_14', 0) or 0,
            })

        # Bot-Alpha: 極限一撃モード
        alpha_mode = self._should_run_bot("alpha")
        if alpha_mode == "disabled":
            self._update_bot_status("alpha", "disabled")
        else:
            try:
                alpha_activation = self.bot_alpha.check_activation(fg, btc_daily_return, btc_d_change)
                if alpha_activation['activated']:
                    self.logger.info(f"[Bot-Alpha] 極限一撃モード発火! FG={fg}")
                    self._update_bot_status("alpha", "fired")
                    targets = self.bot_alpha.scan_targets(symbols_data)
                    signal = self.bot_alpha.generate_signal(alpha_activation, targets, fg)
                    if signal:
                        entry = signal['entry']
                        self._update_bot_status("alpha", "active", last_signal=entry)
                        if self._is_risk_blocked('alpha'):
                            self.logger.info("[Bot-Alpha] リスクリミットによりシグナルをスキップ")
                        elif alpha_mode == "paper":
                            result = self.paper_tracker.record_signal(
                                'alpha', entry['symbol'], entry['side'],
                                entry['entry_price'], entry['leverage'],
                                entry['position_size_pct'],
                                entry['take_profit_pct'], entry['stop_loss_pct'],
                                notes='Bot-Alpha signal'
                            )
                            sid, serial = result if isinstance(result, tuple) else (result, '')
                            if sid == -1:
                                self.logger.info(f"[Bot-Alpha] 同一BOT銘柄上限: {entry['symbol']} スキップ")
                            else:
                                await self.alert.send_paper_signal('alpha', entry, trade_serial=serial)
                                self.activity_logger.log_signal(
                                    'alpha', entry['symbol'], entry['side'], entry['leverage'],
                                    entry['entry_price'], entry['take_profit_pct'], entry['stop_loss_pct'])
                                self.logger.info(f"[Bot-Alpha] ペーパー記録: {entry['symbol']}")
                        elif alpha_mode == "live":
                            await self.alert.send_bot_alpha_alert(signal)
                            await self._execute_live_signal('alpha', entry)
                else:
                    # 発火していない → 接近 or 待機
                    if fg <= 20:
                        self._update_bot_status("alpha", "approaching")
                    else:
                        self._update_bot_status("alpha", "waiting")
            except Exception as e:
                self.logger.error(f"[Bot-Alpha Error] {e}")
                if self.bot_manager:
                    worker = self.bot_manager.workers.get("alpha")
                    if worker:
                        worker.record_error(str(e))

        # Bot-Surge: 日常循環モード
        surge_mode = self._should_run_bot("surge")
        if surge_mode == "disabled":
            self._update_bot_status("surge", "disabled")
        else:
            try:
                surge_activation = self.bot_surge.check_activation(fg, btc_daily_return)
                if surge_activation['activated']:
                    self._update_bot_status("surge", "fired")
                    divergent = self.bot_surge.detect_divergence(symbols_data)
                    cascades = self.bot_surge.check_sector_cascade()
                    signal = self.bot_surge.generate_signal(surge_activation, divergent, cascades, fg)
                    if signal:
                        entry = signal.get('entry', {})
                        if entry:
                            self._update_bot_status("surge", "active", last_signal=entry)
                            if self._is_risk_blocked('surge'):
                                self.logger.info("[Bot-Surge] リスクリミットによりシグナルをスキップ")
                            elif surge_mode == "paper":
                                _result = self.paper_tracker.record_signal(
                                    'surge', entry['symbol'], entry['side'],
                                    entry.get('entry_price', entry.get('price', 0)),
                                    entry.get('leverage', 2),
                                    entry.get('position_size_pct', 20),
                                    entry.get('take_profit_pct', 5.0),
                                    entry.get('stop_loss_pct', 2.0),
                                    notes='Bot-Surge signal'
                                )
                                sid, serial = _result if isinstance(_result, tuple) else (_result, '')
                                if sid == -1:
                                    self.logger.info(f"[Bot-Surge] 同一BOT銘柄上限: {entry['symbol']} スキップ")
                                else:
                                    await self.alert.send_paper_signal('surge', entry, trade_serial=serial)
                                    self.activity_logger.log_signal(
                                        'surge', entry['symbol'], entry['side'],
                                        entry.get('leverage', 2), entry.get('entry_price', entry.get('price', 0)),
                                        entry.get('take_profit_pct', 5.0), entry.get('stop_loss_pct', 2.0))
                                    self.logger.info(f"[Bot-Surge] [{serial}] ペーパー記録: {entry['symbol']}")
                            elif surge_mode == "live":
                                await self.alert.send_bot_surge_alert(signal)
                                await self._execute_live_signal('surge', entry)
                    if divergent:
                        self.logger.info(f"[Bot-Surge] BTC乖離銘柄: {len(divergent)}件")
                    if cascades:
                        self.logger.info(f"[Bot-Surge] セクター波及: {len(cascades)}件")
                else:
                    if 25 <= fg <= 45:
                        self._update_bot_status("surge", "approaching")
                    else:
                        self._update_bot_status("surge", "waiting")
            except Exception as e:
                self.logger.error(f"[Bot-Surge Error] {e}")
                if self.bot_manager:
                    worker = self.bot_manager.workers.get("surge")
                    if worker:
                        worker.record_error(str(e))

        # エンジン未実装Botのステータスを一括更新
        self._update_unimplemented_bots(fg)

        # ライブポジション同期（live_execution有効時）
        if self.live_pos_mgr and self.live_pos_mgr.should_sync():
            try:
                await self.live_pos_mgr.sync_positions()
            except Exception as e:
                self.logger.error(f"[Live Position Sync Error] {e}")

        # TP/SLヘルスチェック（live_execution有効時、5分間隔）(H2)
        if self.live_pos_mgr and self.live_pos_mgr.should_health_check():
            try:
                await self.live_pos_mgr.check_tp_sl_health()
            except Exception as e:
                self.logger.error(f"[TP/SL Health Check Error] {e}")

        # ペーパートレード価格追跡（paper/live両方で実行）
        try:
            current_prices = {s: t.get('last', 0) for s, t in tickers.items()}
            closed = self.paper_tracker.update_tracking(current_prices)
            for sig in closed:
                # シリアル番号をtrade_recordsから取得
                _serial = self._lookup_trade_serial(sig.get('bot_type', ''), sig.get('symbol', ''))
                await self.alert.send_paper_exit(sig, trade_serial=_serial)
                self.logger.info(f"[Paper] [{_serial}] {sig['bot_type']} {sig['symbol']} {sig['exit_reason']} PnL={sig['realized_pnl_pct']:+.2f}%")
                # Activity log: 決済記録
                try:
                    self.activity_logger.log_exit(
                        sig['bot_type'], sig['symbol'], sig.get('side', ''),
                        sig.get('entry_price', 0), sig.get('current_price', 0),
                        sig.get('realized_pnl_pct', 0), exit_reason=sig.get('exit_reason', ''),
                        leverage=sig.get('leverage', 0))
                except Exception:
                    pass
        except Exception as e:
            self.logger.error(f"[Paper Tracking Error] {e}")

    def _any_levburn_sec_enabled(self) -> bool:
        """LevBurn-Secバリアントが1つでも有効か"""
        for bot_key in self._levburn_sec_engines:
            if self._should_run_bot(bot_key) != "disabled":
                return True
        return False

    async def _run_levburn_scan(self, tier1_passed: list, tickers: dict):
        """レバ焼きスキャン実行（30分間隔）"""
        levburn_mode = self._should_run_bot("levburn")
        # LevBurn本体が disabled でも、LevBurn-Secバリアントが有効ならFRスキャンは実行
        any_sec_enabled = self._any_levburn_sec_enabled()
        if levburn_mode == "disabled" and not any_sec_enabled:
            self._update_bot_status("levburn", "disabled")
            return

        try:
            # Tier1通過の上位N銘柄を対象
            symbols = [s.symbol for s, _ in tier1_passed[:self.levburn_max_symbols]]
            if not symbols:
                self._update_bot_status("levburn", "waiting")
                return

            # WebSocket に対象銘柄を登録
            if self.ws_feed:
                for sym in symbols[:self.ws_feed._max_symbols]:
                    self.ws_feed.add_symbol(sym)

            self.logger.info(f"[LevBurn] FR/OIスキャン開始: {len(symbols)}銘柄")
            self._update_bot_status("levburn", "approaching")
            scan_results = await self.fr_collector.scan_symbols(symbols, tickers)
            self.last_levburn_scan = datetime.now()
            self.logger.info(f"[LevBurn] スキャン完了: {len(scan_results)}件の結果")

            # REST FRデータをホットリストに注入（ccxt-pro WS FR非対応取引所向け）
            if self.ws_feed and scan_results:
                for result in scan_results:
                    fr_val = result.get("funding_rate", 0)
                    sym = result.get("symbol", "")
                    if fr_val and fr_val != 0 and sym:
                        self.ws_feed._check_fr_hot(sym, fr_val)
                injected = len([r for r in scan_results if r.get("funding_rate", 0) != 0])
                if injected:
                    self.logger.info(f"[LevBurn] FR→ホットリスト注入: {injected}銘柄")

            if not scan_results:
                self.logger.info("[LevBurn] スキャン結果なし")
                self._update_bot_status("levburn", "waiting")
                return

            # LevBurn本体が disabled ならシグナル生成はスキップ（FRスキャン+ホットリスト注入のみ）
            if levburn_mode == "disabled":
                self.logger.info("[LevBurn] 本体disabled — FRスキャン完了、シグナル生成スキップ")
                self._update_bot_status("levburn", "disabled")
                return

            regime_info = {
                "fear_greed": self.state.fear_greed,
                "regime": self.state.regime,
            }
            candidates = self.levburn_engine.detect_burn_candidates(scan_results, regime_info)
            self.logger.info(f"[LevBurn] {len(candidates)}件の焼き候補検出")

            for candidate in candidates[:3]:  # 上位3件のみ通知
                signal = self.levburn_engine.generate_signal(candidate)
                price = tickers.get(candidate['symbol'], {}).get('last', 0)

                self._update_bot_status("levburn", "active", last_signal=signal)

                if self._is_risk_blocked('levburn'):
                    self.logger.info("[LevBurn] リスクリミットによりシグナルをスキップ")
                elif levburn_mode == "paper":
                    _result = self.paper_tracker.record_signal(
                        'levburn', signal['symbol'], signal['side'],
                        price, signal['leverage'],
                        signal['position_pct'],
                        signal['tp_pct'], signal['sl_pct'],
                        notes=f"LevBurn score={signal['burn_score']} FR={signal['funding_rate']:+.4f}"
                    )
                    sid, serial = _result if isinstance(_result, tuple) else (_result, '')
                    if sid == -1:
                        self.logger.info(f"[LevBurn] 同一BOT銘柄上限: {signal['symbol']} スキップ")
                    else:
                        await self.alert.send_paper_signal('levburn', {
                            'symbol': signal['symbol'],
                            'side': signal['side'],
                            'entry_price': price,
                            'leverage': signal['leverage'],
                            'take_profit_pct': signal['tp_pct'],
                            'stop_loss_pct': signal['sl_pct'],
                        })
                        self.activity_logger.log_signal(
                            'levburn', signal['symbol'], signal['side'], signal['leverage'],
                            price, signal['tp_pct'], signal['sl_pct'])
                        self.logger.info(f"[LevBurn] ペーパー記録: {signal['symbol']} {signal['direction']} score={signal['burn_score']}")
                elif levburn_mode == "live":
                    await self.alert.send_levburn_alert(signal, price)
                    await self._execute_live_signal('levburn', {
                        'symbol': signal['symbol'],
                        'side': signal['side'],
                        'entry_price': price,
                        'leverage': signal['leverage'],
                        'position_size_pct': signal['position_pct'],
                        'take_profit_pct': signal['tp_pct'],
                        'stop_loss_pct': signal['sl_pct'],
                    })

            if not candidates:
                self._update_bot_status("levburn", "waiting")

        except Exception as e:
            self.logger.error(f"[LevBurn Error] {e}")
            if self.bot_manager:
                worker = self.bot_manager.workers.get("levburn")
                if worker:
                    worker.record_error(str(e))

    def _collect_fr_data_for_sec(self) -> dict:
        """LevBurn-Sec用FRデータ収集。
        優先順: (1) WS ticker FR → (2) CacheManager fr_levburn → (3) 空
        """
        fr_data = {}

        # (1) WebSocket ticker — fundingRate フィールドから取得
        if self.ws_feed:
            all_tickers = self.ws_feed.get_all_tickers()
            for sym, ticker in all_tickers.items():
                fr_val = ticker.get("funding_rate", 0)
                if fr_val and fr_val != 0:
                    fr_data[sym] = {"funding_rate": fr_val}

        # (2) CacheManager fallback — fr_collectorの直近REST結果
        if not fr_data and self.fr_collector and self.fr_collector.cache:
            cache = self.fr_collector.cache
            fr_bucket = cache._memory.get("fr_levburn", {})
            for sub_key, entry in fr_bucket.items():
                if sub_key == "__default__":
                    continue
                ts, value = entry
                ttl = cache.MEMORY_CONFIGS.get("fr_levburn", {}).get("ttl", 300)
                if time.time() - ts <= ttl and value:
                    sym = value.get("symbol", sub_key)
                    fr_data[sym] = {"funding_rate": value.get("funding_rate", 0)}

        if fr_data:
            self.logger.info(f"[LevBurn-Sec] FR data: {len(fr_data)} symbols")
        return fr_data

    def _levburn_sec_loop(self):
        """LevBurn-Sec 独立スキャンスレッド（ホットリスト銘柄のみ秒スキャン）
        asyncコルーチンはメインイベントループにディスパッチ（ccxt aiohttp session互換性のため）。"""
        print("[LevBurn-Sec] 秒スキャスレッド開始")

        while not self._levburn_sec_stop.is_set():
            try:
                hot = self.ws_feed.get_hot_symbols() if self.ws_feed else {}

                if not hot:
                    # ホットリスト空 → REST FRデータでフォールバック
                    fr_data = self._collect_fr_data_for_sec()
                    if not fr_data:
                        self._levburn_sec_stop.wait(5.0)
                        continue
                    # REST FRデータをホットリストに注入（WS FR非対応取引所向け）
                    if self.ws_feed:
                        for sym, fr_info in fr_data.items():
                            self.ws_feed._check_fr_hot(sym, fr_info["funding_rate"])
                    hot = self.ws_feed.get_hot_symbols() if self.ws_feed else {}
                    if not hot:
                        # FR値が閾値未満だった場合
                        self._levburn_sec_stop.wait(5.0)
                        continue

                # タイムアウト銘柄をクリーンアップ
                expired = self.ws_feed.cleanup_hot_timeout()
                for sym in expired:
                    print(f"[LevBurn-Sec] TIMEOUT: {sym} — 30分経過、ホットリストから削除")

                # ホットリストからFRデータを構築
                fr_data = {}
                for sym, info in hot.items():
                    fr_data[sym] = {"funding_rate": info["fr"]}

                if not fr_data:
                    self._levburn_sec_stop.wait(self._levburn_sec_interval)
                    continue

                symbols_str = ", ".join(f"{s}({info['fr_level']})" for s, info in hot.items())
                print(f"[LevBurn-Sec] Scanning {len(fr_data)} hot symbols: [{symbols_str}]")

                regime_info = {
                    "fear_greed": self.state.fear_greed,
                    "regime": self.state.regime,
                }

                # メインイベントループにディスパッチ（ccxt exchange sessionはメインループに紐づくため）
                if self._main_loop and self._main_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._run_levburn_sec_scan(fr_data, regime_info),
                        self._main_loop
                    )
                    try:
                        future.result(timeout=30)  # 最大30秒待機
                    except Exception as e:
                        self.logger.error(f"[LevBurn-Sec] Scan dispatch error: {e}")
                else:
                    self.logger.warning("[LevBurn-Sec] Main event loop not available, skipping scan")

            except Exception as e:
                self.logger.error(f"[LevBurn-Sec] Loop error: {e}")

            self._levburn_sec_stop.wait(self._levburn_sec_interval)

        print("[LevBurn-Sec] 秒スキャスレッド停止")

    def _on_hot_symbol_add(self, symbol: str, info: dict):
        """ホットリスト追加コールバック — deal購読開始"""
        print(f"[LevBurn-Sec] HOT: {symbol} FR={info['fr']:+.6f} ({info['fr_level']}) — deal購読開始")
        if self.ws_feed:
            self.ws_feed.subscribe_deal(symbol)

    def _on_hot_symbol_remove(self, symbol: str):
        """ホットリスト削除コールバック — deal購読解除"""
        print(f"[LevBurn-Sec] COOL: {symbol} FR normalized — deal購読解除")
        if self.ws_feed:
            self.ws_feed.unsubscribe_deal(symbol)

    async def _run_levburn_sec_scan(self, fr_data: dict, regime: dict):
        """LevBurn-Sec スキャン（ホットリスト銘柄のみ）"""
        if not self._levburn_sec_engines or not self.ws_feed:
            return

        for bot_key, engine in self._levburn_sec_engines.items():
            mode = self._should_run_bot(bot_key)
            if mode == "disabled":
                self._update_bot_status(bot_key, "disabled")
                continue

            try:
                signals = engine.scan(fr_data, regime)
                if not signals:
                    self._update_bot_status(bot_key, "waiting")
                    continue

                # direction_filter 適用
                dir_filter = self._get_bot_config(bot_key).get('direction_filter', 'none')
                if dir_filter == 'short_only':
                    signals = [s for s in signals if s.direction.upper() == 'SHORT']
                elif dir_filter == 'fr':
                    filtered = []
                    for s in signals:
                        # FR > 0 → SHORTのみ、FR < 0 → LONGのみ
                        if s.fr_value > 0 and s.direction.upper() == 'SHORT':
                            filtered.append(s)
                        elif s.fr_value < 0 and s.direction.upper() == 'LONG':
                            filtered.append(s)
                        # FR方向と不一致 → スキップ
                    signals = filtered

                for signal in signals[:2]:  # 上位2件のみ
                    self._update_bot_status(bot_key, "active", last_signal={
                        'symbol': signal.symbol, 'side': signal.direction.lower(),
                        'entry_price': signal.entry_price,
                    })

                    if self._is_risk_blocked(bot_key):
                        self.logger.info(f"[LevBurn-Sec] {bot_key} リスクリミットによりシグナルをスキップ")
                    elif mode == "paper":
                        _result = self.paper_tracker.record_signal(
                            bot_key, signal.symbol, signal.direction.lower(),
                            signal.entry_price, signal.leverage,
                            signal.position_pct,
                            signal.tp_pct, signal.sl_pct,
                            notes=f"LevBurn-Sec {signal.variant} score={signal.combined_score} FR={signal.fr_value:+.4f}"
                        )
                        sid, serial = _result if isinstance(_result, tuple) else (_result, '')
                        if sid == -1:
                            self.logger.info(f"[LevBurn-Sec] 同一BOT銘柄上限: {signal.symbol} {bot_key} スキップ")
                        else:
                            await self.alert.send_paper_signal(bot_key, {
                                'symbol': signal.symbol,
                                'side': signal.direction.lower(),
                                'entry_price': signal.entry_price,
                                'leverage': signal.leverage,
                                'take_profit_pct': signal.tp_pct,
                                'stop_loss_pct': signal.sl_pct,
                            }, trade_serial=serial)
                            self.activity_logger.log_signal(
                                bot_key, signal.symbol, signal.direction.lower(), signal.leverage,
                                signal.entry_price, signal.tp_pct, signal.sl_pct)
                            self.logger.info(f"[LevBurn-Sec] [{serial}] ペーパー記録: {signal.symbol} {signal.direction} {signal.variant} score={signal.combined_score}")
                    elif mode == "live":
                        await self.alert.send_levburn_sec_alert(signal)
                        await self._execute_live_signal(bot_key, {
                            'symbol': signal.symbol,
                            'side': signal.direction.lower(),
                            'entry_price': signal.entry_price,
                            'leverage': signal.leverage,
                            'position_size_pct': signal.position_pct,
                            'take_profit_pct': signal.tp_pct,
                            'stop_loss_pct': signal.sl_pct,
                        })

            except Exception as e:
                self.logger.error(f"[LevBurn-Sec Error] {bot_key}: {e}")
                if self.bot_manager:
                    worker = self.bot_manager.workers.get(bot_key)
                    if worker:
                        worker.record_error(str(e))

        self._last_levburn_sec_scan = datetime.now()

    async def _run_hot_signal_monitor(self, tier2_passed: list):
        """激アツ自動監視エンジン実行"""
        try:
            t2_states = [s for s, _, _ in tier2_passed]
            fg = self.state.fear_greed
            regime = self.state.regime

            signals = await self.hot_monitor.run_analysis(t2_states, regime, fg)

            for sig in signals:
                if sig.hot_score >= self.hot_monitor.super_hot_score:
                    if (self.hot_monitor.check_cooldown(sig.symbol, sig.level)
                            and not self.hot_monitor.is_quiet_hour()):
                        await self.alert.send_hot_signal_alert(sig)
                        self.hot_monitor.record_cooldown(sig.symbol, sig.level)
                        self.logger.info(f"[HotSignal] 激アツ通知: {sig.symbol} score={sig.hot_score}")
                elif sig.hot_score >= self.hot_monitor.min_hot_score:
                    if (self.hot_monitor.check_cooldown(sig.symbol, sig.level)
                            and not self.hot_monitor.is_quiet_hour()):
                        await self.alert.send_hot_signal_alert(sig)
                        self.hot_monitor.record_cooldown(sig.symbol, sig.level)
                        self.logger.info(f"[HotSignal] アツい通知: {sig.symbol} score={sig.hot_score}")

            # 定期監視レポート（1時間ごと）
            hot_cfg = self.config.get('hot_signal', {})
            report_hours = hot_cfg.get('report_interval_hours', 1)
            if (self.last_watchlist_report is None or
                    (datetime.now() - self.last_watchlist_report).total_seconds() >= report_hours * 3600):
                if not self.hot_monitor.is_quiet_hour() and signals:
                    btc_ticker = await self.fetcher.fetch_ticker('BTC/USDT:USDT')
                    btc_price = btc_ticker.get('last', 0) if btc_ticker else 0
                    btc_chg = btc_ticker.get('percentage', 0) if btc_ticker else 0
                    await self.alert.send_watchlist_report({
                        'signals': signals,
                        'btc_price': btc_price,
                        'btc_change': btc_chg,
                        'fear_greed': fg,
                        'regime': regime,
                        'interval': f'{report_hours}h',
                    })
                    self.last_watchlist_report = datetime.now()

        except Exception as e:
            self.logger.error(f"[HotSignal Error] {e}")

    async def _check_daily_summary(self):
        now = datetime.now()
        if now.hour == 9 and now.minute < 2:
            if self.last_daily_summary and self.last_daily_summary.date() == now.date():
                return

            yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
            top = sorted(self.daily_top_symbols, key=lambda x: x['score'], reverse=True)[:10]
            feedback_stats = self.feedback.get_accuracy_stats()

            await self.alert.send_daily_summary(
                yesterday, self.daily_alert_count,
                self.daily_tier1_count, self.daily_tier2_count,
                self.state.regime, self.state.fear_greed,
                top, feedback_stats
            )

            self.db.save_daily_summary(
                yesterday, self.daily_alert_count,
                self.daily_tier1_count, self.daily_tier2_count,
                self.state.regime, self.state.fear_greed,
                str([s['symbol'] for s in top[:5]])
            )

            self.daily_alert_count = 0
            self.daily_tier1_count = 0
            self.daily_tier2_count = 0
            self.daily_top_symbols = []
            self.last_daily_summary = now

    async def _send_health_check(self):
        """毎時ヘルスチェック Telegram送信"""
        import psutil
        import os

        uptime = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)

        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / 1024 / 1024

        paper_summary = self.paper_tracker.get_summary()
        mode_str = "🧪 DRY RUN" if self.dry_run else "🔴 LIVE"

        text = (
            f"💚 <b>ヘルスチェック {mode_str}</b>\n"
            f"  稼働: {hours}h{mins:02d}m\n"
            f"  サイクル: {self.cycle_count}回\n"
            f"  エラー: {self.error_count}回\n"
            f"  メモリ: {mem_mb:.0f}MB\n"
            f"  Paper: {paper_summary['total_signals']}件 "
            f"(Open:{paper_summary['open']} Closed:{paper_summary['closed']} "
            f"WR:{paper_summary['win_rate']:.0f}%)\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.alert.send_message(text)
        self.last_health_check = datetime.now()

    async def run(self):
        self.running = True
        self.start_time = datetime.now()
        self._main_loop = asyncio.get_running_loop()  # LevBurn-Secスレッドからのディスパッチ用
        await self.initialize()

        # Telegram対話ボット起動
        try:
            from src.execution.telegram_handler import TelegramBotHandler
            self.telegram_handler = TelegramBotHandler(db=self.db, engine=self)
            await self.telegram_handler.start()
            self.logger.info("[Engine] Telegram対話ボット起動")
        except Exception as e:
            self.logger.warning(f"[Engine] Telegram対話ボット起動失敗: {e}")
            self.telegram_handler = None

        # 取引所起動チェック (ポジションモード + FR検証)
        try:
            from src.exchange.exchange_utils import ensure_one_way_mode, validate_funding_rates
            ok = await ensure_one_way_mode(self.fetcher.exchange)
            if not ok:
                self.logger.warning("[Engine] Position mode check failed — continuing with caution")
            fr_result = await validate_funding_rates(self.fetcher.exchange)
            if not fr_result['valid']:
                self.logger.warning(f"[Engine] FR validation issues: {fr_result['error_count']} errors")
            else:
                self.logger.info("[Engine] FR validation passed")
        except Exception as e:
            self.logger.warning(f"[Engine] Startup exchange checks failed: {e}")

        # WebSocket開始
        if self.ws_feed:
            self.ws_feed.start()
            self.logger.info("[Engine] WebSocket feed started")

            # LevBurn-Sec 2段階アーキテクチャ: ホットリスト設定 + 秒スキャスレッド起動
            from src.signals.bot_levburn_sec import TRIGGERS
            self.ws_feed.configure_hot_list(
                fr_min=TRIGGERS["fr_min"],
                fr_strong=TRIGGERS["fr_strong"],
                fr_extreme=TRIGGERS["fr_extreme"],
                timeout=1800,
                on_add=self._on_hot_symbol_add,
                on_remove=self._on_hot_symbol_remove,
            )
            self._levburn_sec_stop.clear()
            self._levburn_sec_thread = threading.Thread(
                target=self._levburn_sec_loop,
                name="levburn-sec-scan",
                daemon=True,
            )
            self._levburn_sec_thread.start()
            self.logger.info("[Engine] LevBurn-Sec 秒スキャスレッド開始")

        # dry_run時はscan_interval_secondsを使用（デフォルト120秒）
        if self.dry_run:
            interval = self.config.get('paper_trade', {}).get('scan_interval_seconds', 120)
            self.logger.info(f"[Engine] DRY RUNモード（{interval}秒間隔）")
        else:
            interval = self.config['monitoring']['interval_seconds']
            self.logger.info(f"[Engine] メインループ開始（{interval}秒間隔）")

        while self.running:
            try:
                start = datetime.now()
                await self.scan_cycle()
                self.cycle_count += 1
                elapsed = (datetime.now() - start).total_seconds()
                sleep_time = max(0, interval - elapsed)
                self.logger.info(f"[Engine] サイクル完了: {elapsed:.1f}秒 / 次回まで{sleep_time:.0f}秒")

                # 毎時ヘルスチェック
                if (self.last_health_check is None or
                    datetime.now() - self.last_health_check > timedelta(hours=1)):
                    try:
                        await self._send_health_check()
                    except Exception as e:
                        self.logger.error(f"[HealthCheck Error] {e}")

                # GC実行
                gc.collect()

                await asyncio.sleep(sleep_time)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.error_count += 1
                self.logger.error(f"[Engine Error] {traceback.format_exc()}")
                try:
                    await self.alert.send_error(str(e)[:500])
                except Exception:
                    pass  # アラート送信自体が失敗してもクラッシュしない
                await asyncio.sleep(30)

        # LevBurn-Sec スレッド停止
        if self._levburn_sec_thread:
            self._levburn_sec_stop.set()
            self._levburn_sec_thread.join(timeout=10)

        if self.ws_feed:
            self.ws_feed.stop()
        await self.fetcher.close()
        self.logger.info("[Engine] 停止完了")

    def stop(self):
        self.running = False
