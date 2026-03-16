"""銘柄ごとの状態管理"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict
import pandas as pd

@dataclass
class SymbolState:
    symbol: str
    last_price: float = 0.0
    ohlcv_1m: Optional[pd.DataFrame] = None
    ohlcv_1h: Optional[pd.DataFrame] = None
    ohlcv_1d: Optional[pd.DataFrame] = None
    volume_sma_20: float = 0.0
    sma_5: float = 0.0
    sma_200: float = 0.0
    rsi_14: float = 50.0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    orderbook_depth_usd: float = 0.0
    btc_correlation: float = 1.0
    btc_alpha: float = 0.0
    sector: str = ""
    tier1_score: float = 0.0
    tier2_score: float = 0.0
    tier1_passed: bool = False
    tier2_passed: bool = False
    tier1_details: Dict = field(default_factory=dict)
    tier2_details: Dict = field(default_factory=dict)
    last_updated: Optional[datetime] = None
    alerts_sent: Dict[str, datetime] = field(default_factory=dict)

class StateManager:
    def __init__(self):
        self.symbols: Dict[str, SymbolState] = {}
        self.regime: str = "unknown"
        self.regime_data: Dict = {}
        self.btc_state: Optional[SymbolState] = None
        self.fear_greed: int = 50

    def get_or_create(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(symbol=symbol)
        return self.symbols[symbol]

    def get_tier1_passed(self) -> list:
        return [s for s in self.symbols.values() if s.tier1_passed]

    def get_tier2_passed(self) -> list:
        return [s for s in self.symbols.values() if s.tier2_passed]
