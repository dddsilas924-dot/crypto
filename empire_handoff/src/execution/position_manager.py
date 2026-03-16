"""ポジション管理・DD警告・SL/TP監視"""
from typing import List, Optional
from datetime import datetime
from src.data.database import HistoricalDB
from src.execution.alert import TelegramAlert

class PositionManager:
    def __init__(self, db: HistoricalDB, alert: TelegramAlert, config: dict):
        self.db = db
        self.alert = alert
        self.dd_warning_pct = config.get('dd_warning_pct', -3.0)
        self.dd_critical_pct = config.get('dd_critical_pct', -5.0)

    async def check_positions(self, current_prices: dict):
        """全オープンポジションの損益チェック"""
        positions = self.db.get_open_positions()
        for pos in positions:
            symbol = pos['symbol']
            if symbol not in current_prices:
                continue

            current_price = current_prices[symbol]
            entry_price = pos['entry_price']
            leverage = pos['leverage']

            if pos['side'] == 'long':
                pnl_pct = (current_price - entry_price) / entry_price * 100 * leverage
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100 * leverage

            self.db.update_position_price(pos['id'], current_price, pnl_pct)

            # DD警告
            if pnl_pct <= self.dd_critical_pct:
                await self.alert.send_position_alert(symbol, pnl_pct, 'sl_hit')
            elif pnl_pct <= self.dd_warning_pct:
                await self.alert.send_position_alert(symbol, pnl_pct, 'dd_warning')

            # TP接近
            if pos['take_profit'] and current_price >= pos['take_profit'] * 0.95:
                await self.alert.send_position_alert(symbol, pnl_pct, 'tp_near')

            # SL到達
            if pos['stop_loss']:
                if pos['side'] == 'long' and current_price <= pos['stop_loss']:
                    await self.alert.send_position_alert(symbol, pnl_pct, 'sl_hit')
                elif pos['side'] == 'short' and current_price >= pos['stop_loss']:
                    await self.alert.send_position_alert(symbol, pnl_pct, 'sl_hit')
