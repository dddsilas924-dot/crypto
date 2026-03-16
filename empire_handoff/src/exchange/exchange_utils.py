"""取引所ユーティリティ — 接続テスト、FR検証、ポジションモード設定"""
import asyncio
import logging
import time

logger = logging.getLogger("empire")


async def test_connection(exchange) -> dict:
    """取引所接続テスト。各項目の成否を返す。

    Returns:
        {
            'exchange': str,
            'public_ok': bool,
            'private_ok': bool,
            'ws_ok': bool,  # placeholder — WS test is done separately
            'fr_ok': bool,
            'position_mode_ok': bool,
            'latency_ms': float,
            'errors': list[str],
        }
    """
    result = {
        'exchange': exchange.id,
        'public_ok': False,
        'private_ok': False,
        'ws_ok': False,
        'fr_ok': False,
        'position_mode_ok': False,
        'latency_ms': 0,
        'errors': [],
    }

    # Public REST test (load_markets)
    t0 = time.time()
    try:
        await exchange.load_markets()
        result['public_ok'] = True
        result['latency_ms'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        result['errors'].append(f"public: {e}")

    # Private REST test (fetch_balance)
    try:
        await exchange.fetch_balance()
        result['private_ok'] = True
    except Exception as e:
        result['errors'].append(f"private: {e}")

    # Funding rate test
    try:
        markets = exchange.markets or {}
        swap_symbols = [s for s, m in markets.items() if m.get('swap') and ':USDT' in s]
        if swap_symbols:
            test_symbol = 'BTC/USDT:USDT' if 'BTC/USDT:USDT' in swap_symbols else swap_symbols[0]
            fr = await exchange.fetch_funding_rate(test_symbol)
            if fr and fr.get('fundingRate') is not None:
                result['fr_ok'] = True
            else:
                result['errors'].append("fr: returned None")
        else:
            result['errors'].append("fr: no swap markets found")
    except Exception as e:
        result['errors'].append(f"fr: {e}")

    # Position mode test
    try:
        if exchange.has.get('fetchPositionMode'):
            mode = await exchange.fetch_position_mode(symbol='BTC/USDT:USDT')
            result['position_mode_ok'] = True
        else:
            result['position_mode_ok'] = True  # exchange doesn't support position mode toggle
            result['errors'].append("position_mode: fetchPositionMode not supported")
    except Exception as e:
        result['errors'].append(f"position_mode: {e}")

    return result


async def validate_funding_rates(exchange, symbols: list = None, n: int = 3) -> dict:
    """FR取得を n 回繰り返し、妥当性をチェック。

    Returns:
        {
            'valid': bool,
            'checks': [{symbol, rate, ok, error}],
            'error_count': int,
        }
    """
    if not symbols:
        markets = exchange.markets or await exchange.load_markets()
        swap_symbols = [s for s, m in markets.items() if m.get('swap') and ':USDT' in s]
        symbols = ['BTC/USDT:USDT'] if 'BTC/USDT:USDT' in swap_symbols else swap_symbols[:1]

    checks = []
    for i in range(n):
        for symbol in symbols:
            try:
                fr = await exchange.fetch_funding_rate(symbol)
                rate = fr.get('fundingRate') if fr else None
                ok = rate is not None and isinstance(rate, (int, float)) and abs(rate) < 1.0
                checks.append({'symbol': symbol, 'rate': rate, 'ok': ok, 'error': None})
            except Exception as e:
                checks.append({'symbol': symbol, 'rate': None, 'ok': False, 'error': str(e)})
        if i < n - 1:
            await asyncio.sleep(1)

    error_count = sum(1 for c in checks if not c['ok'])
    return {
        'valid': error_count == 0,
        'checks': checks,
        'error_count': error_count,
    }


async def ensure_one_way_mode(exchange) -> bool:
    """ポジションモードを One-Way に設定。

    Returns:
        True if one-way mode is confirmed/set, False if failed.
    """
    if not exchange.has.get('fetchPositionMode'):
        logger.info(f"[ExchangeUtils] {exchange.id}: fetchPositionMode not supported, skipping")
        return True

    try:
        # fetchPositionMode is exchange-specific
        # ccxt unified: setPositionMode(hedged=False) for one-way
        mode = await exchange.fetch_position_mode(symbol='BTC/USDT:USDT')

        # ccxt returns different structures per exchange
        # Check if hedge mode is active
        hedge_mode = False
        if isinstance(mode, dict):
            hedge_mode = mode.get('hedged', mode.get('dualSidePosition', False))

        if hedge_mode:
            logger.info(f"[ExchangeUtils] {exchange.id}: hedge mode detected, switching to one-way")
            await exchange.set_position_mode(False, symbol='BTC/USDT:USDT')
            logger.info(f"[ExchangeUtils] {exchange.id}: switched to one-way mode")

        return True
    except Exception as e:
        logger.error(f"[ExchangeUtils] {exchange.id}: position mode check failed: {e}")
        return False
