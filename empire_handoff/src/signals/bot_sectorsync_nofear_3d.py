"""Bot-SectorSync-NoFear-3D: 3日足タイムフレーム版"""
from src.signals.bot_sectorsync_nofear import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'timeframe': '3d'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
