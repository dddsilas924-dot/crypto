"""新規Bot バックテスト結果サマリー → Telegram送信"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.execution.alert import TelegramAlert


async def main():
    text = (
        "<b>🔬 新規Bot バックテスト結果</b>\n"
        "期間: 2024-01-01 〜 2026-03-01\n"
        "コスト: 0.22%/RT, 翌日始値エントリー\n"
        "\n"
        "<b>📈 Bot-Momentum</b> (出来高急増+MA乖離)\n"
        "  トレード: 297  WR: 32.0%  PF: 1.02\n"
        "  Return: +6.7%  MDD: -44.3%  Sharpe: 0.34\n"
        "  評価: ❌ PF≈1.0, WR低すぎ, MDD大\n"
        "\n"
        "<b>📈 Bot-Rebound</b> (暴落後リバウンド)\n"
        "  トレード: 45  WR: 40.0%  PF: 1.32\n"
        "  Return: +38.1%  MDD: -18.9%  Sharpe: 2.42\n"
        "  評価: ⚠️ Sharpe良好だがPF未達, トレード数少\n"
        "\n"
        "<b>📈 Bot-Stability</b> (低ボラMA回帰)\n"
        "  トレード: 170  WR: 37.6%  PF: 1.14\n"
        "  Return: +14.9%  MDD: -14.3%  Sharpe: 1.24\n"
        "  評価: ❌ PF未達, 逆張りの精度不足\n"
        "\n"
        "<b>📊 WF検証対象</b>\n"
        "  PF 1.5超のBotなし → WF検証スキップ\n"
        "\n"
        "<b>📋 既存Bot比較</b>\n"
        "  Bot-Surge:  PF=3.50 (WF済・実運用GO)\n"
        "  Bot-Alpha:  PF=1.59 (データ不足)\n"
        "  Bot-Rebound: PF=1.32 (最有望だが要改良)\n"
        "  Bot-Momentum: PF=1.02 (不採用)\n"
        "  Bot-Stability: PF=1.14 (不採用)\n"
        "\n"
        "<b>💡 Next Steps</b>\n"
        "  1. Bot-Rebound: Fear閾値・回復率の最適化で改善可能性あり\n"
        "  2. Bot-Surge が圧倒的に優秀、引き続き主力\n"
        "  3. 新ナレッジ25件を vault/knowledge/mew/ に構造化済"
    )

    alert = TelegramAlert()
    await alert.send_message(text)
    print("Telegram送信完了")


if __name__ == "__main__":
    asyncio.run(main())
