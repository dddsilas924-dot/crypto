"""Botマネージャー - 全Bot統括制御"""
import threading
import logging
from typing import Dict, Optional
from src.core.bot_worker import BotWorker, BotMode
from src.core.config_manager import ConfigManager

logger = logging.getLogger("empire")

# 全Bot定義（名前 → settings.yamlキー）
BOT_REGISTRY = {
    'alpha': 'bot_alpha',
    'surge': 'bot_surge',
    'momentum': 'bot_momentum',
    'rebound': 'bot_rebound',
    'stability': 'bot_stability',
    'trend': 'bot_trend',
    'cascade': 'bot_cascade',
    'meanrevert': 'bot_meanrevert',
    'meanrevert_adaptive': 'bot_meanrevert_adaptive',
    'meanrevert_tight': 'bot_meanrevert_tight',
    'meanrevert_hybrid': 'bot_meanrevert_hybrid',
    'meanrevert_newlist': 'bot_meanrevert_newlist',
    'meanrevert_tuned': 'bot_meanrevert_tuned',
    'meanrevert_strict_a': 'bot_meanrevert_strict_a',
    'meanrevert_strict_b': 'bot_meanrevert_strict_b',
    # Evolved全部盛り版
    'levburn_sec_evo_agg': 'bot_levburn_sec_evo_agg',
    'levburn_sec_evo_micro': 'bot_levburn_sec_evo_micro',
    'levburn_sec_evo_lev1': 'bot_levburn_sec_evo_lev1',
    'alpha_r7': 'bot_alpha_r7',
    # Aggressive最適化版 (BT Sharpe上位)
    'levburn_sec_agg_lev1': 'bot_levburn_sec_agg_lev1',
    'levburn_sec_agg_lev3_ls': 'bot_levburn_sec_agg_lev3_ls',
    'levburn_sec_agg_lev1_fr': 'bot_levburn_sec_agg_lev1_fr',
    'levburn_sec_agg_lev3_fr': 'bot_levburn_sec_agg_lev3_fr',
    'levburn_sec_agg_7x': 'bot_levburn_sec_agg_7x',
    'levburn_sec_agg_7x_so': 'bot_levburn_sec_agg_7x_so',
    'levburn_sec_agg_7x_fr': 'bot_levburn_sec_agg_7x_fr',
    'breakout': 'bot_breakout',
    'btcfollow': 'bot_btcfollow',
    'weakshort': 'bot_weakshort',
    'volexhaust': 'bot_volexhaust',
    'fearflat': 'bot_fearflat',
    'domshift': 'bot_domshift',
    'gaptrap': 'bot_gaptrap',
    'sectorsync': 'bot_sectorsync',
    'feardip': 'bot_feardip',
    'sectorlead': 'bot_sectorlead',
    'shortsqueeze': 'bot_shortsqueeze',
    'sniper': 'bot_sniper',
    'scalp': 'bot_scalp',
    'event': 'bot_event',
    'ico_meanrevert': 'bot_ico_meanrevert',
    'ico_rebound': 'bot_ico_rebound',
    'ico_surge': 'bot_ico_surge',
    'hf_meanrevert': 'bot_hf_meanrevert',
    'hf_momentum': 'bot_hf_momentum',
    'hf_spread': 'bot_hf_spread',
    'hf_break': 'bot_hf_break',
    'hf_frarb': 'bot_hf_frarb',
    'levburn': 'bot_levburn',
    'levburn_sec': 'bot_levburn_sec',
    'levburn_sec_aggressive': 'bot_levburn_sec_aggressive',
    'levburn_sec_conservative': 'bot_levburn_sec_conservative',
    'levburn_sec_scalp_micro': 'bot_levburn_sec_scalp_micro',
    'levburn_sec_fr_extreme': 'bot_levburn_sec_fr_extreme',
    # レバ1x固定版
    'levburn_sec_lev1': 'bot_levburn_sec_lev1',
    'levburn_sec_aggressive_lev1': 'bot_levburn_sec_aggressive_lev1',
    'levburn_sec_conservative_lev1': 'bot_levburn_sec_conservative_lev1',
    'levburn_sec_scalp_micro_lev1': 'bot_levburn_sec_scalp_micro_lev1',
    'levburn_sec_fr_extreme_lev1': 'bot_levburn_sec_fr_extreme_lev1',
    # レバ3x固定版
    'levburn_sec_lev3': 'bot_levburn_sec_lev3',
    'levburn_sec_aggressive_lev3': 'bot_levburn_sec_aggressive_lev3',
    'levburn_sec_conservative_lev3': 'bot_levburn_sec_conservative_lev3',
    'levburn_sec_scalp_micro_lev3': 'bot_levburn_sec_scalp_micro_lev3',
    'levburn_sec_fr_extreme_lev3': 'bot_levburn_sec_fr_extreme_lev3',
}


class BotManager:
    """全Botの起動・停止・モード切替を統括するオーケストレーター"""

    def __init__(self, config: dict):
        self.config = config
        self._lock = threading.Lock()
        self.workers: Dict[str, BotWorker] = {}

    def initialize(self):
        """settings.yamlからBot一覧を読み込み、BotWorkerを作成"""
        bots_section = self.config.get('bots', {})

        for bot_name, config_key in BOT_REGISTRY.items():
            bot_config = self.config.get(config_key, {})
            if not bot_config:
                continue

            # bots:セクションからモード読み込み（フォールバック: paper）
            mode_str = bots_section.get(bot_name, {}).get('mode', 'paper') if bots_section else 'paper'
            # 旧形式フォールバック: bots:セクションがない場合はdry_runから推定
            if not bots_section:
                mode_str = 'paper' if self.config.get('dry_run', False) else 'paper'

            try:
                mode = BotMode(mode_str)
            except ValueError:
                mode = BotMode.PAPER

            worker = BotWorker(bot_name, bot_config, mode)
            self.workers[bot_name] = worker

        logger.info(f"[BotManager] {len(self.workers)} bots initialized")

    def start_all(self):
        """全有効Botを起動（disabled はスキップ）"""
        started = 0
        disabled = 0
        for worker in self.workers.values():
            if worker.mode == BotMode.DISABLED:
                disabled += 1
                continue
            worker.start()
            started += 1
        logger.info(f"[BotManager] Starting {started} bots ({disabled} disabled, skipped)")

    def stop_all(self):
        """起動中のBotのみ停止"""
        stopped = 0
        for worker in self.workers.values():
            if worker.is_running:
                worker.stop()
                stopped += 1
        logger.info(f"[BotManager] All {stopped} bots stopped")

    def switch_bot_mode(self, bot_name: str, new_mode: str) -> bool:
        """指定Botのモード切替 + yaml永続化。成功: True, Bot不存在: False"""
        worker = self.workers.get(bot_name)
        if not worker:
            return False
        try:
            mode = BotMode(new_mode)
        except ValueError:
            return False
        worker.switch_mode(mode)
        # yaml永続化（再起動後も維持）
        try:
            ConfigManager().update_bot_mode(bot_name, new_mode)
        except Exception as e:
            logger.error(f"[BotManager] Failed to persist mode to yaml: {e}")
        return True

    def get_bot_state(self, bot_name: str) -> Optional[dict]:
        """指定Botの状態取得"""
        worker = self.workers.get(bot_name)
        if not worker:
            return None
        return worker.get_state()

    def get_all_states(self) -> list:
        """全Bot状態を一覧取得"""
        return [w.get_state() for w in self.workers.values()]

    def get_dashboard_summary(self) -> dict:
        """ダッシュボード用サマリー"""
        states = self.get_all_states()
        live_count = sum(1 for s in states if s['mode'] == 'live')
        paper_count = sum(1 for s in states if s['mode'] == 'paper')
        disabled_count = sum(1 for s in states if s['mode'] == 'disabled')
        total_signals = sum(s['signal_count'] for s in states)
        total_errors = sum(s['error_count'] for s in states)

        return {
            'total_bots': len(states),
            'live': live_count,
            'paper': paper_count,
            'disabled': disabled_count,
            'total_signals': total_signals,
            'total_errors': total_errors,
            'bots': states,
        }
