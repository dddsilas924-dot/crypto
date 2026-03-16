"""Bot-Alpha-R7: 緩和厳選版 (Fear<30, BTC-0.5%, Alpha≥1.5, TP8/SL2)"""
from src.signals.bot_alpha_relaxed import check_signal as _check

def check_signal(conn, fg, btc_return, btc_df, date_str, symbols, config):
    config = {**config, 'variant': 'alpha_r7'}
    return _check(conn, fg, btc_return, btc_df, date_str, symbols, config)
