"""Bot個別ワーカー - 状態管理専用（スキャンはengine.pyが実行）"""
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("empire")


class BotMode(Enum):
    LIVE = "live"
    PAPER = "paper"
    DISABLED = "disabled"


class BotWorker:
    """各Botの状態管理。モード切替・ステータス更新・統計保持を担当。
    スキャンロジックはengine.pyが実行し、結果をこのWorkerに記録する。
    """

    def __init__(self, name: str, config: dict, mode: BotMode = BotMode.PAPER):
        self.name = name
        self.config = config
        self.mode = mode
        self._running = False

        # ステータス（engine.pyから更新）
        self.status: str = "waiting"  # waiting/approaching/active/fired/disabled
        self.last_signal = None
        self.last_signal_time: Optional[datetime] = None
        self.start_time: Optional[datetime] = None

        # 統計
        self.stats = {
            "cycles": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "paper_trades": 0,
            "errors": 0,
            "pnl_total": 0.0,
            "win_count": 0,
            "loss_count": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        """起動（状態をactiveに。スレッドは起動しない）"""
        if self.mode == BotMode.DISABLED:
            logger.info(f"[BotWorker] {self.name}: disabled, skip start")
            return
        self._running = True
        self.start_time = datetime.now()
        logger.info(f"[BotWorker] {self.name}: started (mode={self.mode.value})")

    def stop(self):
        """停止"""
        if self._running:
            self._running = False
            logger.info(f"[BotWorker] {self.name}: stopped")

    def switch_mode(self, new_mode: BotMode):
        """モード切替（GUIから呼ばれる）"""
        old_mode = self.mode
        self.mode = new_mode
        logger.info(f"[BotWorker] {self.name}: mode {old_mode.value} -> {new_mode.value}")

        if new_mode == BotMode.DISABLED:
            self._running = False
            self.status = "disabled"
        elif not self._running:
            self._running = True
            self.start_time = datetime.now()
            self.status = "waiting"

    def record_signal(self, signal=None):
        """シグナル発火を記録"""
        self.stats["signals_generated"] += 1
        self.last_signal_time = datetime.now()
        if signal:
            self.last_signal = signal

    def record_error(self, error: str):
        """エラーを記録"""
        self.stats["errors"] += 1

    def get_state(self) -> dict:
        """現在状態を辞書で返す"""
        uptime = None
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()
        return {
            'name': self.name,
            'mode': self.mode.value,
            'running': self._running,
            'status': self.status,
            'signal_count': self.stats["signals_generated"],
            'error_count': self.stats["errors"],
            'last_signal': self.last_signal,
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'cycle_count': self.stats["cycles"],
            'uptime_seconds': uptime,
            'stats': self.stats.copy(),
        }
