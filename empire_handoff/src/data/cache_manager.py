"""統合キャッシュマネージャー - ファイル永続 + メモリ揮発"""
import json
import time
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

CACHE_DIR = Path("data/cache")


class CacheManager:
    """統合キャッシュマネージャー"""

    # ファイルキャッシュ設定 (TTL秒)
    FILE_CONFIGS = {
        "coingecko_sectors": {"ttl": 7 * 86400},      # 7日
        "coingecko_id_map": {"ttl": 30 * 86400},      # 30日
        "mexc_futures": {"ttl": 24 * 3600},            # 24時間
        "scale_symbol_map": {"ttl": 30 * 86400},      # 30日
    }

    # メモリキャッシュ設定 (TTL秒)
    MEMORY_CONFIGS = {
        "fear_greed": {"ttl": 300},       # 5分
        "global_data": {"ttl": 600},      # 10分
        "orderbook": {"ttl": 3600},       # 1時間（レートリミット対策）
        "funding_rate": {"ttl": 300},     # 5分
        "btc_correlation": {"ttl": 3600}, # 1時間
        "tickers": {"ttl": 30},           # 30秒
        "sector_map": {"ttl": 3600},      # 1時間（スクリプト以外で変更なし）
        "watchlist": {"ttl": 300},        # 5分
        "sanctuary_map": {"ttl": 3600},   # 1時間
        "btc_ohlcv_1h": {"ttl": 300},    # 5分
        "non_crypto_set": {"ttl": 3600}, # 1時間
        "fr_levburn": {"ttl": 300},     # 5分（FR取得キャッシュ）
        "oi_levburn": {"ttl": 300},     # 5分（OI取得キャッシュ）
    }

    def __init__(self, cache_dir: str = str(CACHE_DIR)):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # メモリキャッシュ: {key: {sub_key: (timestamp, value)}}
        self._memory: dict = {}
        # 統計
        self._stats = {"hits": 0, "misses": 0}

    # ========== ファイルキャッシュ ==========

    def _file_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta.json"

    def file_get(self, key: str) -> Optional[Any]:
        """ファイルキャッシュ取得。有効期限内ならデータ返却"""
        meta_path = self._meta_path(key)
        file_path = self._file_path(key)
        if not meta_path.exists() or not file_path.exists():
            self._stats["misses"] += 1
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ttl = self.FILE_CONFIGS.get(key, {}).get("ttl", 86400)
            if time.time() - meta.get("timestamp", 0) > ttl:
                self._stats["misses"] += 1
                return None
            data = json.loads(file_path.read_text(encoding="utf-8"))
            self._stats["hits"] += 1
            return data
        except (json.JSONDecodeError, OSError):
            self._stats["misses"] += 1
            return None

    def file_set(self, key: str, value: Any):
        """ファイルキャッシュ保存"""
        file_path = self._file_path(key)
        meta_path = self._meta_path(key)
        file_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        meta_path.write_text(json.dumps({
            "timestamp": time.time(),
            "updated_at": datetime.now().isoformat(),
            "key": key,
        }), encoding="utf-8")

    def file_is_valid(self, key: str) -> bool:
        """ファイルキャッシュが有効期限内か"""
        meta_path = self._meta_path(key)
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ttl = self.FILE_CONFIGS.get(key, {}).get("ttl", 86400)
            return time.time() - meta.get("timestamp", 0) <= ttl
        except (json.JSONDecodeError, OSError):
            return False

    # ========== メモリキャッシュ ==========

    def get(self, key: str, sub_key: str = "__default__") -> Optional[Any]:
        """メモリキャッシュ取得。有効期限内ならデータ返却"""
        bucket = self._memory.get(key, {})
        entry = bucket.get(sub_key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        ts, value = entry
        ttl = self.MEMORY_CONFIGS.get(key, {}).get("ttl", 60)
        if time.time() - ts > ttl:
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return value

    def set(self, key: str, value: Any, sub_key: str = "__default__"):
        """メモリキャッシュ保存"""
        if key not in self._memory:
            self._memory[key] = {}
        self._memory[key][sub_key] = (time.time(), value)

    def is_valid(self, key: str, sub_key: str = "__default__") -> bool:
        """メモリキャッシュが有効期限内か"""
        bucket = self._memory.get(key, {})
        entry = bucket.get(sub_key)
        if entry is None:
            return False
        ts, _ = entry
        ttl = self.MEMORY_CONFIGS.get(key, {}).get("ttl", 60)
        return time.time() - ts <= ttl

    def invalidate(self, key: str, sub_key: str = None):
        """手動無効化"""
        if sub_key:
            if key in self._memory and sub_key in self._memory[key]:
                del self._memory[key][sub_key]
        else:
            self._memory.pop(key, None)
            # ファイルキャッシュも無効化
            meta = self._meta_path(key)
            if meta.exists():
                meta.unlink()

    def invalidate_all_memory(self):
        """全メモリキャッシュ無効化"""
        self._memory.clear()

    def stats(self) -> dict:
        """キャッシュ統計"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "total": total,
            "hit_rate_pct": round(hit_rate, 1),
            "memory_keys": list(self._memory.keys()),
            "file_caches": [
                k for k in self.FILE_CONFIGS
                if self._file_path(k).exists()
            ],
        }

    def reset_stats(self):
        self._stats = {"hits": 0, "misses": 0}
