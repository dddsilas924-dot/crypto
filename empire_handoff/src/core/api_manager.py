"""APIマネージャー - レートリミット・シンボルロック・Bot間衝突防止・競合検知"""
import hashlib
import threading
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("empire")


class APIManager:
    """取引所API呼び出しの安全管理。レートリミット・シンボルロック・競合検知を提供。"""

    def __init__(self, config: dict):
        safety_cfg = config.get('api_safety', {})
        self.rate_limit_per_sec = safety_cfg.get('rate_limit_per_sec', 10)
        self.max_concurrent = safety_cfg.get('max_concurrent_requests', 5)
        self.symbol_lock_timeout = safety_cfg.get('symbol_lock_timeout_sec', 300)

        self._semaphore = threading.Semaphore(self.max_concurrent)
        self._rate_lock = threading.Lock()
        self._symbol_locks: Dict[str, threading.Lock] = {}
        self._symbol_lock_map_lock = threading.Lock()
        self._locked_symbols: Dict[str, datetime] = {}
        self._call_times: list = []

        # API競合グループ管理
        self._api_groups: Dict[str, List[str]] = {}  # key_hash → [bot_names]
        self._group_semaphores: Dict[str, threading.Semaphore] = {}
        self._bot_positions: Dict[str, Dict[str, str]] = {}  # bot → {symbol: side}
        self._reserved_balance: Dict[str, float] = {}  # bot → reserved amount

    def acquire_rate_limit(self, timeout: float = 10.0) -> bool:
        """レートリミットを取得。取得できたらTrue。"""
        if not self._semaphore.acquire(timeout=timeout):
            return False

        with self._rate_lock:
            now = time.time()
            # 1秒以内の呼び出し履歴だけ保持
            self._call_times = [t for t in self._call_times if now - t < 1.0]
            if len(self._call_times) >= self.rate_limit_per_sec:
                self._semaphore.release()
                return False
            self._call_times.append(now)

        return True

    def release_rate_limit(self):
        """レートリミット解放"""
        self._semaphore.release()

    def lock_symbol(self, symbol: str, bot_name: str = '') -> bool:
        """シンボルをロック（同一銘柄への重複操作防止）"""
        lock = self._get_symbol_lock(symbol)
        acquired = lock.acquire(blocking=False)
        if acquired:
            with self._symbol_lock_map_lock:
                self._locked_symbols[symbol] = datetime.now()
            logger.debug(f"[APIManager] Symbol locked: {symbol} by {bot_name}")
        return acquired

    def unlock_symbol(self, symbol: str):
        """シンボルロック解放"""
        lock = self._get_symbol_lock(symbol)
        try:
            lock.release()
            with self._symbol_lock_map_lock:
                self._locked_symbols.pop(symbol, None)
        except RuntimeError:
            pass  # already unlocked

    def is_symbol_locked(self, symbol: str) -> bool:
        """シンボルがロック中かチェック"""
        with self._symbol_lock_map_lock:
            if symbol not in self._locked_symbols:
                return False
            # タイムアウトチェック
            locked_at = self._locked_symbols[symbol]
            if (datetime.now() - locked_at).total_seconds() > self.symbol_lock_timeout:
                self._locked_symbols.pop(symbol, None)
                return False
            return True

    def get_locked_symbols(self) -> Dict[str, str]:
        """ロック中シンボル一覧"""
        with self._symbol_lock_map_lock:
            now = datetime.now()
            # タイムアウト分を除外
            active = {}
            for sym, locked_at in list(self._locked_symbols.items()):
                if (now - locked_at).total_seconds() <= self.symbol_lock_timeout:
                    active[sym] = locked_at.isoformat()
                else:
                    self._locked_symbols.pop(sym, None)
            return active

    def get_stats(self) -> dict:
        """統計情報"""
        return {
            'rate_limit_per_sec': self.rate_limit_per_sec,
            'max_concurrent': self.max_concurrent,
            'locked_symbols': len(self.get_locked_symbols()),
            'symbol_lock_timeout': self.symbol_lock_timeout,
        }

    def _get_symbol_lock(self, symbol: str) -> threading.Lock:
        """シンボル用ロックを取得（なければ作成）"""
        with self._symbol_lock_map_lock:
            if symbol not in self._symbol_locks:
                self._symbol_locks[symbol] = threading.Lock()
            return self._symbol_locks[symbol]

    # ========================================
    # API競合グループ管理
    # ========================================

    @staticmethod
    def _hash_key(api_key: str) -> str:
        """APIキーのハッシュ（グルーピング用）"""
        return hashlib.md5((api_key or "default").encode()).hexdigest()[:8]

    def register_bot(self, bot_name: str, api_key: str = ''):
        """BotをAPIグループに登録"""
        key_hash = self._hash_key(api_key)
        if key_hash not in self._api_groups:
            self._api_groups[key_hash] = []
            self._group_semaphores[key_hash] = threading.Semaphore(2)
        if bot_name not in self._api_groups[key_hash]:
            self._api_groups[key_hash].append(bot_name)
        logger.debug(f"[APIManager] Bot {bot_name} registered to group {key_hash}")

    def check_position_conflict(self, bot_name: str, symbol: str, side: str,
                                 api_key: str = '') -> Optional[dict]:
        """同じAPIキー内で逆ポジションがないかチェック"""
        key_hash = self._hash_key(api_key)
        for other_bot in self._api_groups.get(key_hash, []):
            if other_bot == bot_name:
                continue
            other_pos = self._bot_positions.get(other_bot, {})
            if symbol in other_pos and other_pos[symbol] != side:
                return {"bot": other_bot, "side": other_pos[symbol]}
        return None

    def record_position(self, bot_name: str, symbol: str, side: str):
        """Bot のポジションを記録"""
        if bot_name not in self._bot_positions:
            self._bot_positions[bot_name] = {}
        self._bot_positions[bot_name][symbol] = side

    def clear_position(self, bot_name: str, symbol: str):
        """Bot のポジションをクリア"""
        if bot_name in self._bot_positions:
            self._bot_positions[bot_name].pop(symbol, None)

    def get_conflict_report(self) -> list:
        """GUI表示用: APIグループごとの競合状況"""
        report = []
        for key_hash, bots in self._api_groups.items():
            count = len(bots)
            if count == 0:
                continue
            risk = "safe" if count == 1 else ("warn" if count == 2 else "high")
            report.append({
                "api_key_hash": key_hash,
                "api_key_masked": f"****{key_hash}",
                "bots": bots,
                "bot_count": count,
                "max_concurrent": 2,
                "risk": risk,
            })
        return report

    def get_api_groups(self) -> Dict[str, List[str]]:
        """APIグループ一覧"""
        return dict(self._api_groups)
