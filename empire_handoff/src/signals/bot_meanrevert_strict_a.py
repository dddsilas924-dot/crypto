"""Bot-MeanRevert-Strict-A: 厳格版 (Fear55-75, MA25%, RSI>75)"""
from src.signals.bot_meanrevert_strict import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'variant': 'strict_a'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
