"""アラート精度フィードバックループ"""
from datetime import datetime, timedelta
from src.data.database import HistoricalDB
from src.fetchers.ohlcv import MEXCFetcher

class FeedbackLoop:
    def __init__(self, db: HistoricalDB, fetcher: MEXCFetcher):
        self.db = db
        self.fetcher = fetcher

    async def update_feedback(self):
        """24時間以上前のアラートのフィードバックを更新"""
        alerts = self.db.get_unfeedback_alerts(hours_ago=1)
        updated = 0

        for alert in alerts:
            symbol = alert['symbol']
            alert_time = datetime.fromisoformat(alert['alert_time'])
            alert_price = alert['alert_price']
            now = datetime.now()

            price_1h = None
            price_24h = None
            price_48h = None

            # 1時間後の価格
            if now - alert_time >= timedelta(hours=1):
                ticker = await self.fetcher.fetch_ticker(symbol)
                if ticker:
                    price_1h = ticker.get('last')

            # 24時間後（DBのOHLCVから取得）
            ohlcv = self.db.get_ohlcv(symbol, '1h', 500)
            if now - alert_time >= timedelta(hours=24):
                if ohlcv is not None:
                    target_ts = alert_time + timedelta(hours=24)
                    closest = ohlcv.index[ohlcv.index <= target_ts]
                    if len(closest) > 0:
                        price_24h = ohlcv.loc[closest[-1], 'close']

            # 48時間後
            if now - alert_time >= timedelta(hours=48):
                if ohlcv is not None:
                    target_ts = alert_time + timedelta(hours=48)
                    closest = ohlcv.index[ohlcv.index <= target_ts]
                    if len(closest) > 0:
                        price_48h = ohlcv.loc[closest[-1], 'close']

            if price_1h or price_24h or price_48h:
                self.db.update_alert_feedback(alert['id'], price_1h, price_24h, price_48h, alert_price)
                updated += 1

        return updated

    def get_accuracy_stats(self) -> dict:
        """アラート精度統計"""
        import pandas as pd
        conn = self.db._get_conn()
        df = pd.read_sql_query("SELECT * FROM alert_log WHERE feedback_updated=1", conn)
        conn.close()

        if len(df) == 0:
            return {'avg_1h': 0, 'avg_24h': 0, 'avg_48h': 0, 'win_rate_24h': 0, 'total': 0}

        return {
            'avg_1h': df['pnl_1h_pct'].mean() if df['pnl_1h_pct'].notna().any() else 0,
            'avg_24h': df['pnl_24h_pct'].mean() if df['pnl_24h_pct'].notna().any() else 0,
            'avg_48h': df['pnl_48h_pct'].mean() if df['pnl_48h_pct'].notna().any() else 0,
            'win_rate_24h': (df['pnl_24h_pct'] > 0).mean() * 100 if df['pnl_24h_pct'].notna().any() else 0,
            'total': len(df),
        }
