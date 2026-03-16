"""ヒストリカルデータ初期取得 - MEXC先物全銘柄の日足・1時間足を最大範囲で取得"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.fetchers.ohlcv import MEXCFetcher
from src.data.database import HistoricalDB

async def fetch_all_historical():
    fetcher = MEXCFetcher()
    db = HistoricalDB()

    print("=" * 60)
    print("📊 ヒストリカルデータ初期取得")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 銘柄リスト取得
    symbols = await fetcher.fetch_futures_symbols()
    print(f"\n📈 対象銘柄数: {len(symbols)}")

    total_1d = 0
    total_1h = 0
    errors = []

    for i, symbol in enumerate(symbols):
        try:
            # 日足: 最大1000本（約2.7年分）
            df_1d = await fetcher.fetch_ohlcv(symbol, '1d', 1000)
            if df_1d is not None and len(df_1d) > 0:
                count = db.upsert_ohlcv(symbol, '1d', df_1d)
                total_1d += count

                # 聖域価格の自動算出: 2025-10-10の日足安値
                try:
                    target_date = '2025-10-10'
                    oct10 = df_1d[df_1d.index.strftime('%Y-%m-%d') == target_date]
                    if len(oct10) > 0:
                        sanctuary_price = oct10['low'].iloc[0]
                        db.set_sanctuary(symbol, sanctuary_price, target_date, 'auto_10_10')
                    else:
                        # 10/10データなければ200日安値を仮使用
                        if len(df_1d) >= 200:
                            sanctuary_price = df_1d['low'].tail(200).min()
                            db.set_sanctuary(symbol, sanctuary_price, 'last_200d_low', 'auto_200d')
                except Exception:
                    pass

            # 1時間足: 最大500本（約20日分）
            df_1h = await fetcher.fetch_ohlcv(symbol, '1h', 500)
            if df_1h is not None and len(df_1h) > 0:
                count = db.upsert_ohlcv(symbol, '1h', df_1h)
                total_1h += count

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(symbols)}] 取得済み... (1d:{total_1d}, 1h:{total_1h})")

            await asyncio.sleep(0.15)  # レート制限対策

        except Exception as e:
            errors.append(f"{symbol}: {e}")
            await asyncio.sleep(1)

    await fetcher.close()

    # 聖域統計
    conn = db._get_conn()
    total_sanctuary = conn.execute('SELECT COUNT(*) FROM sanctuary').fetchone()[0]
    auto_1010 = conn.execute("SELECT COUNT(*) FROM sanctuary WHERE source='auto_10_10'").fetchone()[0]
    auto_200d = conn.execute("SELECT COUNT(*) FROM sanctuary WHERE source='auto_200d'").fetchone()[0]
    conn.close()

    print(f"\n✅ 完了!")
    print(f"  日足レコード: {total_1d:,}")
    print(f"  1時間足レコード: {total_1h:,}")
    print(f"  聖域価格設定数: {total_sanctuary} (10/10自動:{auto_1010}, 200日安値:{auto_200d})")
    print(f"  エラー: {len(errors)}件")
    if errors[:10]:
        for e in errors[:10]:
            print(f"    ⚠️ {e}")

if __name__ == "__main__":
    asyncio.run(fetch_all_historical())
