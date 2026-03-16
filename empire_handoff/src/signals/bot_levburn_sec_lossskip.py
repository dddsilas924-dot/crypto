"""Bot-LevBurn-Sec-LossSkip: 連敗対策 — 負け後の同一銘柄同一方向を1回スキップ

派生バリアント (config.variant で切替):
  lossskip     : 同一銘柄+同一方向の負け後1回スキップ
  lossskip2    : 2連敗後に同一銘柄を24hクールダウン
  cooldown_sym : 負け後にその銘柄を3回スキップ
  reverse_entry: 負け後の次シグナルを逆方向でエントリー
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

# 直近の負けトレード記録 {(symbol, side): loss_count}
_loss_memory = {}
_loss_dates = {}  # {symbol: last_loss_date}


def _reset_memory():
    global _loss_memory, _loss_dates
    _loss_memory = {}
    _loss_dates = {}


def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    """LevBurn-Secベースのシグナル + 連敗スキップロジック"""
    variant = config.get('variant', 'lossskip')

    # ベースのlevburn_secロジックを流用
    from src.signals.bot_levburn_sec_base import check_levburn_sec_base
    base_signal = check_levburn_sec_base(conn, fg, btc_return, btc_df, date_str, symbols, config)

    if base_signal is None:
        return None

    sym = base_signal['symbol']
    side = base_signal['side']
    key = (sym, side)

    if variant == 'lossskip':
        # 同一銘柄+同一方向の負け後1回スキップ
        if key in _loss_memory and _loss_memory[key] > 0:
            _loss_memory[key] -= 1
            return None

    elif variant == 'lossskip2':
        # 2連敗後に同一銘柄スキップ
        if key in _loss_memory and _loss_memory[key] >= 2:
            _loss_memory[key] = 0
            return None

    elif variant == 'cooldown_sym':
        # 負け後にその銘柄を3回スキップ
        sym_key = sym
        if sym_key in _loss_memory and _loss_memory[sym_key] > 0:
            _loss_memory[sym_key] -= 1
            return None

    elif variant == 'reverse_entry':
        # 負け後の次シグナルを逆方向
        if key in _loss_memory and _loss_memory[key] > 0:
            _loss_memory[key] -= 1
            base_signal['side'] = 'short' if side == 'long' else 'long'

    return base_signal


def record_loss(symbol, side, variant='lossskip'):
    """バックテストエンジンから負けトレード記録を受け取る"""
    key = (symbol, side)
    if variant == 'lossskip':
        _loss_memory[key] = 1
    elif variant == 'lossskip2':
        _loss_memory[key] = _loss_memory.get(key, 0) + 1
    elif variant == 'cooldown_sym':
        _loss_memory[symbol] = 3
    elif variant == 'reverse_entry':
        _loss_memory[key] = 1
