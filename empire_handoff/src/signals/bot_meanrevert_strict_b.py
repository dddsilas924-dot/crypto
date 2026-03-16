"""Bot-MeanRevert-Strict-B: 超厳格版 (Fear60-80, MA30%, RSI>80)"""
from src.signals.bot_meanrevert_strict import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'variant': 'strict_b'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
