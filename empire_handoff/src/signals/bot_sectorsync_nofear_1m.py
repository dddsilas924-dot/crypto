"""Bot-SectorSync-NoFear-1M: 1分足プロキシ（最も敏感な閾値）"""
from src.signals.bot_sectorsync_nofear import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'timeframe': '1m'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
