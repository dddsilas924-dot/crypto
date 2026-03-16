"""聖域価格補完 - 新規上場銘柄は全日足の最安値を聖域に設定"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.fetchers.ohlcv import MEXCFetcher


async def main():
    start_time = datetime.now()
    db = HistoricalDB()
    fetcher = MEXCFetcher()

    print("=" * 60)
    print("🔧 聖域価格補完（新規上場銘柄）")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 未設定銘柄取得
    conn = db._get_conn()
    all_symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv WHERE timeframe='1d'").fetchall()]
    set_symbols = [r[0] for r in conn.execute("SELECT symbol FROM sanctuary").fetchall()]
    conn.close()
    missing = [s for s in all_symbols if s not in set_symbols]
    print(f"\n未設定銘柄: {len(missing)}")

    stats = {'success': 0, 'fail': 0}
    results = []

    for i, symbol in enumerate(missing):
        try:
            # MEXCから取得可能な全日足を取得（最大1000本）
            df = await fetcher.fetch_ohlcv(symbol, '1d', 1000)
            if df is not None and len(df) > 0:
                low_price = df['low'].min()
                low_date = df.loc[df['low'].idxmin()].name.strftime('%Y-%m-%d')
                bars = len(df)

                if low_price > 0:
                    db.set_sanctuary(symbol, float(low_price), low_date,
                                     source='post_listing_low', is_new_listing=True)
                    stats['success'] += 1
                    results.append(f"  ✅ {symbol}: ${low_price:.6f} ({low_date}, {bars}本)")
                else:
                    stats['fail'] += 1
                    results.append(f"  ⚠️ {symbol}: low=0（スキップ）")
            else:
                stats['fail'] += 1
                results.append(f"  ❌ {symbol}: データ取得失敗")
        except Exception as e:
            stats['fail'] += 1
            results.append(f"  ❌ {symbol}: {str(e)[:50]}")

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(missing)}] 成功:{stats['success']} 失敗:{stats['fail']}")

        await asyncio.sleep(0.15)

    await fetcher.close()

    # 最終集計
    conn = db._get_conn()
    total_sanctuary = conn.execute('SELECT COUNT(*) FROM sanctuary').fetchone()[0]
    new_listing_count = conn.execute('SELECT COUNT(*) FROM sanctuary WHERE is_new_listing=1').fetchone()[0]
    conn.close()

    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n✅ 完了! ({elapsed:.0f}秒)")
    print(f"  補完成功: {stats['success']}")
    print(f"  失敗/スキップ: {stats['fail']}")
    print(f"  聖域設定済み合計: {total_sanctuary}/{len(all_symbols)}")
    print(f"  うち新規上場: {new_listing_count}")

    # 詳細ログ（先頭30件）
    for r in results[:30]:
        print(r)
    if len(results) > 30:
        print(f"  ...他{len(results)-30}件")

    # Telegram送信
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        text = (
            f"🔧 <b>聖域価格補完完了</b>\n\n"
            f"■ 結果\n"
            f"  補完成功: {stats['success']}銘柄\n"
            f"  失敗/スキップ: {stats['fail']}銘柄\n"
            f"  処理時間: {elapsed:.0f}秒\n\n"
            f"■ 聖域設定状況\n"
            f"  合計: {total_sanctuary}/{len(all_symbols)} ({total_sanctuary/len(all_symbols)*100:.1f}%)\n"
            f"  うち新規上場: {new_listing_count}銘柄\n"
            f"  source: post_listing_low\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await alert.send_message(text)
        print("\n📱 Telegram送信完了")
    except Exception as e:
        print(f"\n⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
