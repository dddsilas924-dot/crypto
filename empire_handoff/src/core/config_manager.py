"""settings.yamlの動的読み書き"""
import os
import sys
import time
import yaml
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("empire")

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

# ファイルロック: プラットフォーム分岐
_IS_WINDOWS = sys.platform == 'win32'
if _IS_WINDOWS:
    import msvcrt

    def _lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_file(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
else:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file(f):
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass


class ConfigManager:
    """settings.yamlの動的読み書き"""

    _LOCK_MAX_RETRIES = 3
    _LOCK_RETRY_SEC = 1.0

    def __init__(self, path: str = None):
        self.path = Path(path) if path else CONFIG_PATH

    def load(self) -> dict:
        """設定ファイル読み込み"""
        with open(self.path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def save(self, config: dict):
        """設定ファイル保存（排他ロック + アトミック書き込み）"""
        lock_path = Path(str(self.path) + '.lock')
        lock_fd = None
        for attempt in range(self._LOCK_MAX_RETRIES):
            try:
                lock_fd = open(lock_path, 'w')
                _lock_file(lock_fd)
                break
            except (IOError, OSError):
                if lock_fd:
                    lock_fd.close()
                    lock_fd = None
                if attempt < self._LOCK_MAX_RETRIES - 1:
                    logger.warning(f"[ConfigManager] Lock retry {attempt+1}/{self._LOCK_MAX_RETRIES}")
                    time.sleep(self._LOCK_RETRY_SEC)
                else:
                    logger.error("[ConfigManager] Failed to acquire file lock, saving without lock")

        try:
            # アトミック書き込み: 一時ファイルに書いてからリネーム
            dir_path = self.path.parent
            with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', dir=dir_path,
                                             delete=False, encoding='utf-8') as tmp:
                yaml.dump(config, tmp, default_flow_style=False, allow_unicode=True, sort_keys=False)
                tmp_path = tmp.name
            # Windows: 既存ファイルがあるとrenameが失敗するので置換
            if _IS_WINDOWS:
                os.replace(tmp_path, self.path)
            else:
                os.rename(tmp_path, self.path)
            logger.info(f"[ConfigManager] Settings saved to {self.path}")
        except Exception as e:
            # 一時ファイルのクリーンアップ
            try:
                if 'tmp_path' in locals():
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise e
        finally:
            if lock_fd:
                _unlock_file(lock_fd)
                lock_fd.close()

    def update_bot_api(self, bot_name: str, api_key: str, api_secret: str):
        """Bot別APIを更新してyaml保存"""
        config = self.load()
        if bot_name == "default":
            if 'exchange' not in config:
                config['exchange'] = {}
            config['exchange']['api_key'] = api_key
            config['exchange']['api_secret'] = api_secret
        else:
            bots = config.get('bots', {})
            if bot_name in bots:
                if bots[bot_name] is None:
                    bots[bot_name] = {}
                if bots[bot_name].get('api') is None:
                    bots[bot_name]['api'] = {}
                bots[bot_name]['api']['api_key'] = api_key
                bots[bot_name]['api']['api_secret'] = api_secret
        self.save(config)

    def update_bot_mode(self, bot_name: str, mode: str):
        """Botモードを更新してyaml保存"""
        config = self.load()
        bots = config.get('bots', {})
        if bot_name in bots:
            if bots[bot_name] is None:
                bots[bot_name] = {}
            bots[bot_name]['mode'] = mode
            self.save(config)

    def get_bot_api(self, bot_name: str) -> dict:
        """Bot別API設定を取得（なければdefault）"""
        config = self.load()
        bots = config.get('bots', {})
        bot_cfg = bots.get(bot_name, {}) or {}
        api_cfg = bot_cfg.get('api') or {}
        if api_cfg.get('api_key'):
            return api_cfg
        # default fallback
        return {
            'api_key': config.get('exchange', {}).get('api_key', ''),
            'api_secret': config.get('exchange', {}).get('api_secret', ''),
        }

    def get_all_bot_apis(self) -> dict:
        """全Botのapi設定を返す（conflict check用）"""
        config = self.load()
        default_key = config.get('exchange', {}).get('api_key', '')
        bots = config.get('bots', {})
        result = {}
        for bot_name, bot_cfg in bots.items():
            if bot_cfg is None:
                bot_cfg = {}
            api_cfg = bot_cfg.get('api') or {}
            key = api_cfg.get('api_key', '') or default_key
            result[bot_name] = {
                'api_key': key,
                'mode': bot_cfg.get('mode', 'paper'),
                'is_custom': bool(api_cfg.get('api_key')),
            }
        return result

    def get_live_execution(self) -> dict:
        """live_execution設定を取得"""
        config = self.load()
        defaults = {
            'enabled': False,
            'max_positions': 3,
            'max_daily_loss_pct': 5.0,
            'max_consecutive_losses': 5,
            'min_balance_usd': 50.0,
            'position_size_cap_usd': 500.0,
            'default_margin_type': 'cross',
            'slippage_tolerance_pct': 0.5,
            'dry_run_first': True,
            'allowed_bots': [],
            'sync_interval_seconds': 60,
        }
        live_cfg = config.get('live_execution', {})
        for k, v in defaults.items():
            if k not in live_cfg:
                live_cfg[k] = v
        return live_cfg

    # バリデーションルール: (min, max)
    _LIVE_EXEC_RANGES = {
        'max_positions': (1, 50),
        'max_consecutive_losses': (1, 50),
        'sync_interval_seconds': (10, 600),
        'max_daily_loss_pct': (0.5, 50.0),
        'min_balance_usd': (0, 100000),
        'position_size_cap_usd': (10, 100000),
        'slippage_tolerance_pct': (0.01, 10.0),
    }

    def update_live_execution(self, updates: dict):
        """live_execution設定を部分更新してyaml保存。型変換+範囲バリデーション付き。"""
        config = self.load()
        if 'live_execution' not in config:
            config['live_execution'] = {}
        live = config['live_execution']

        # 型安全: 数値フィールドは数値に変換
        int_fields = {'max_positions', 'max_consecutive_losses', 'sync_interval_seconds'}
        float_fields = {'max_daily_loss_pct', 'min_balance_usd', 'position_size_cap_usd',
                        'slippage_tolerance_pct'}
        bool_fields = {'enabled', 'dry_run_first'}

        errors = []
        for key, value in updates.items():
            try:
                if key in int_fields:
                    v = int(value)
                    lo, hi = self._LIVE_EXEC_RANGES.get(key, (None, None))
                    if lo is not None and not (lo <= v <= hi):
                        errors.append(f'{key}: {v} out of range [{lo}, {hi}]')
                        continue
                    live[key] = v
                elif key in float_fields:
                    v = float(value)
                    lo, hi = self._LIVE_EXEC_RANGES.get(key, (None, None))
                    if lo is not None and not (lo <= v <= hi):
                        errors.append(f'{key}: {v} out of range [{lo}, {hi}]')
                        continue
                    live[key] = v
                elif key in bool_fields:
                    if isinstance(value, str):
                        live[key] = value.lower() in ('true', '1', 'yes')
                    else:
                        live[key] = bool(value)
                elif key == 'allowed_bots':
                    if isinstance(value, str):
                        live[key] = [b.strip() for b in value.split(',') if b.strip()]
                    else:
                        live[key] = list(value)
                elif key == 'default_margin_type':
                    if value not in ('cross', 'isolated'):
                        errors.append(f'default_margin_type: must be cross or isolated')
                        continue
                    live[key] = str(value)
                else:
                    live[key] = value
            except (ValueError, TypeError) as e:
                errors.append(f'{key}: invalid value "{value}" ({e})')

        if errors:
            raise ValueError('; '.join(errors))

        self.save(config)
        logger.info(f"[ConfigManager] live_execution updated: {list(updates.keys())}")

    def get_risk_management(self) -> dict:
        """リスク管理設定を取得"""
        defaults = {
            'daily_loss_limit_pct': 5.0,
            'cumulative_loss_limit_pct': 20.0,
            'limit_action': 'order_stop',
        }
        config = self.load()
        rm = config.get('risk_management', {})
        defaults.update(rm)
        return defaults

    def update_risk_management(self, updates: dict):
        """リスク管理設定を更新"""
        config = self.load()
        rm = config.get('risk_management', {})
        float_fields = {'daily_loss_limit_pct', 'cumulative_loss_limit_pct'}
        for k, v in updates.items():
            if k in float_fields:
                rm[k] = float(v)
            elif k == 'limit_action':
                if v in ('order_stop', 'bot_stop'):
                    rm[k] = v
            else:
                rm[k] = v
        config['risk_management'] = rm
        self.save(config)

    @staticmethod
    def mask_key(key: str) -> str:
        """APIキーをマスク表示"""
        if not key or len(key) < 8:
            return '****'
        return key[:4] + '****' + key[-4:]
