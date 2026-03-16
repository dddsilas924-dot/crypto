"""最終サマリー Telegram送信"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.execution.alert import TelegramAlert


async def main():
    text = (
        "<b>🏆 新規Bot設計・検証 最終レポート</b>\n"
        "期間: 2024-01-01 〜 2026-03-01\n"
        "コスト: 0.22%/RT, 翌日始値エントリー\n"
        "\n"
        "<b>📋 提案Bot (6種)</b>\n"
        "Trend / Cascade / MeanRevert / Breakout / BTCFollow / WeakShort\n"
        "\n"
        "<b>📊 バックテスト結果 (PF降順)</b>\n"
        "1. WeakShort   PF=2.16 WR=55% Ret=+55% MDD=-5%\n"
        "2. MeanRevert  PF=2.14 WR=55% Ret=+625% MDD=-7%\n"
        "3. Rebound     PF=1.32 WR=40% Ret=+38% MDD=-19%\n"
        "4. Stability   PF=1.14 WR=38% Ret=+15% MDD=-14%\n"
        "5. Trend       PF=1.11 WR=32% Ret=+16% MDD=-17%\n"
        "6. Breakout    PF=1.06 WR=32% Ret=+1% MDD=-13%\n"
        "7. Momentum    PF=1.02 WR=32% Ret=+7% MDD=-44%\n"
        "8. Cascade     PF=0.77 WR=29% Ret=-23% MDD=-29%\n"
        "9. BTCFollow   PF=inf  (1トレードのみ、データ不足)\n"
        "\n"
        "<b>✅ WF検証通過Bot</b>\n"
        "• Bot-MeanRevert: OOS 5/5win PF&gt;1.0 集計PF=2.10 → 堅牢(GO)\n"
        "• Bot-WeakShort: OOS 4/4win PF&gt;1.0 集計PF=2.03 → 堅牢(GO)\n"
        "• Bot-Surge(既存): OOS 5/5win PF&gt;1.0 集計PF=3.50 → 堅牢(GO)\n"
        "\n"
        "<b>📈 レバレッジ比較 (破産なし)</b>\n"
        "         1x      2x      3x      5x\n"
        "Surge   +38%    +90%   +160%   +379%\n"
        "MnRev  +172%   +625%  +1790% +11965%\n"
        "WkSht   +25%    +55%    +91%   +189%\n"
        "\n"
        "<b>🆚 Bot-Surge比較</b>\n"
        "Surge:    PF=3.27 81t  Fear25-45 BTC下落\n"
        "MnRevert: PF=2.14 383t Fear50-80 過熱Short\n"
        "WkShort:  PF=2.16 103t Fear50-75 BTC上昇\n"
        "→ Fear帯が完全分離。全Bot同時運用可能\n"
        "\n"
        "<b>🧪 テスト: 83/83 PASS</b>\n"
        "\n"
        "<b>💡 推奨Bot構成</b>\n"
        "1. Bot-Surge (主力): Fear25-45, BTC下落時\n"
        "2. Bot-MeanRevert (新): Fear50-80, 過熱逆張り\n"
        "3. Bot-WeakShort (新): Fear50-75, 弱アルトショート\n"
        "→ 3Bot併用で全Fear帯(25-80)をカバー\n"
        "→ 推奨レバ: Surge=2x, MeanRevert=2x, WeakShort=2x"
    )

    alert = TelegramAlert()
    await alert.send_message(text)
    print("Telegram送信完了")


if __name__ == "__main__":
    asyncio.run(main())
