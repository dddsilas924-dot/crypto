"""Fear & Greed Index ヒストリカルデータ取得・DB保存"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import aiohttp
from aiohttp.resolver import ThreadedResolver
from src.data.database import HistoricalDB


async def main():
    db = HistoricalDB()
    conn = db._get_conn()

    existing = conn.execute("SELECT COUNT(*) FROM fear_greed_history").fetchone()[0]
    print(f"📊 既存レコード: {existing}件")

    print("🔍 Fear & Greed Index ヒストリカルデータ取得中...")
    url = "https://api.alternative.me/fng/?limit=0&date_format=us"

    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                print(f"❌ API応答エラー: {resp.status}")
                return
            data = await resp.json()

    records = data.get('data', [])
    print(f"📦 API応答: {len(records)}件")

    inserted = 0
    for rec in records:
        value = int(rec['value'])
        classification = rec.get('value_classification', '')
        # timestamp is MM-DD-YYYY format
        ts_str = rec['timestamp']
        try:
            dt = datetime.strptime(ts_str, '%m-%d-%Y')
            date_str = dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

        try:
            conn.execute(
                "INSERT OR IGNORE INTO fear_greed_history (date, value, classification) VALUES (?, ?, ?)",
                (date_str, value, classification)
            )
            inserted += 1
        except Exception:
            pass

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM fear_greed_history").fetchone()[0]
    date_range = conn.execute(
        "SELECT MIN(date), MAX(date) FROM fear_greed_history"
    ).fetchone()
    conn.close()

    new_records = inserted - existing if inserted > existing else inserted
    print(f"\n✅ 完了!")
    print(f"  新規挿入: {new_records}件")
    print(f"  総レコード: {total}件")
    print(f"  期間: {date_range[0]} 〜 {date_range[1]}")


if __name__ == "__main__":
    asyncio.run(main())
