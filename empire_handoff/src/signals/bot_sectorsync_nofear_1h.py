"""Bot-SectorSync-NoFear-1H: 1時間足プロキシ（日足で1日lookback）"""
from src.signals.bot_sectorsync_nofear import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'timeframe': '1h'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
