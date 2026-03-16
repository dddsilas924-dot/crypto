"""取引所ファクトリ — settings.yaml の exchange セクションから ccxt インスタンス生成"""
import os
import aiohttp
import ccxt.async_support as ccxt_async
import logging

logger = logging.getLogger("empire")

# ccxt が対応する先物取引所
SUPPORTED_EXCHANGES = {'mexc', 'bitmart', 'binance', 'bybit', 'okx'}

# BitMart demo (testnet) URLs
_DEMO_URLS = {
    'bitmart': {
        'api': 'https://api-cloud-v2.bitmart.com',  # BitMart has no separate testnet URL; use sandbox mode
    },
}


def create_exchange(exchange_config: dict) -> ccxt_async.Exchange:
    """settings.yaml の exchange セクションから ccxt async Exchange を生成。

    Args:
        exchange_config: {
            name: 'mexc' | 'bitmart' | 'binance' | 'bybit' | 'okx',
            api_key_env: str (env var name, default '{NAME}_API_KEY'),
            secret_env: str (env var name, default '{NAME}_API_SECRET'),
            memo_env: str (env var name for BitMart memo, default '{NAME}_MEMO'),
            demo: bool (use sandbox/testnet, default False),
            margin_mode: 'cross' | 'isolated' (default 'cross'),
            leverage: int (default 3),
            type: 'futures' | 'swap' (default 'futures'),
        }

    Returns:
        ccxt.async_support.Exchange instance configured for swap trading
    """
    name = exchange_config.get('name', 'mexc').lower()
    if name not in SUPPORTED_EXCHANGES:
        raise ValueError(f"Unsupported exchange: {name}. Supported: {SUPPORTED_EXCHANGES}")

    # Resolve API credentials from env vars
    name_upper = name.upper()
    api_key_env = exchange_config.get('api_key_env', f'{name_upper}_API_KEY')
    secret_env = exchange_config.get('secret_env', f'{name_upper}_API_SECRET')
    memo_env = exchange_config.get('memo_env', f'{name_upper}_MEMO')

    api_key = os.getenv(api_key_env, '')
    secret = os.getenv(secret_env, '')
    memo = os.getenv(memo_env, '')

    # Build ccxt config
    ccxt_config = {
        'apiKey': api_key,
        'secret': secret,
        'options': {'defaultType': 'swap'},
        'enableRateLimit': True,
        'aiohttp_trust_env': True,
    }

    # BitMart requires 'uid' (memo) for authentication
    if name == 'bitmart' and memo:
        ccxt_config['uid'] = memo

    # Sandbox/demo mode
    demo = exchange_config.get('demo', False)
    if demo:
        ccxt_config['sandbox'] = True

    # Create exchange instance
    exchange_class = getattr(ccxt_async, name, None)
    if exchange_class is None:
        raise ValueError(f"ccxt does not support exchange: {name}")

    exchange = exchange_class(ccxt_config)

    # Use ThreadedResolver to avoid aiodns issues on Windows
    exchange.session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=aiohttp.resolver.ThreadedResolver())
    )

    logger.info(f"[ExchangeFactory] Created {name} exchange (demo={demo})")
    return exchange
