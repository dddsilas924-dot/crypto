"""MeanRevert検証結果 Telegram送信"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.execution.alert import TelegramAlert


async def main():
    text = (
        "<b>🔬 Bot-MeanRevert 詳細検証レポート</b>\n"
        "\n"
        "<b>📊 月別PnLサマリー (修正後: cooldown=2日)</b>\n"
        "トレード: 383→220件 (同一銘柄クールダウン追加)\n"
        "PF: 2.14→1.95 | Return: +625%→+160%\n"
        "MDD: -6.8%→-6.1% | Sharpe: 6.25→5.24\n"
        "\n"
        "月別PnL (抜粋):\n"
        "2024-01: +232K | 2024-04: +323K | 2024-07: +234K\n"
        "2025-01: +542K | 2025-06: +596K | 2025-08: +1,166K\n"
        "唯一の負け月: 2025-04 (-55K)\n"
        "\n"
        "<b>⚠️ 発見した異常パターン</b>\n"
        "1. 同一銘柄連続エントリー: 189/383件(49%)\n"
        "   → cooldown 2日追加で 32/220件(15%)に改善\n"
        "2. 同一銘柄重複ポジション: 13件\n"
        "   → 重複禁止チェック追加で解消\n"
        "3. AIXBT 21回等の銘柄集中\n"
        "   → cooldown後は最大10回に分散\n"
        "\n"
        "<b>🔗 MeanRevert × WeakShort 相関</b>\n"
        "シグナル日重複: 83日 (WS103日の81%)\n"
        "銘柄一致: 4/83日 (4.8%) → 低い重複\n"
        "月次同時負け: 1/20ヶ月のみ (2025-04)\n"
        "→ 同時ドローダウンリスク: 極めて低い\n"
        "\n"
        "<b>💰 複利計算確認</b>\n"
        "ポジションサイズ推移 (修正前参考):\n"
        "最初: ¥150K → 最後: ¥1,069K (7.1倍)\n"
        "前半平均: ¥286K / 後半平均: ¥688K (2.4倍)\n"
        "→ 複利で後半の金額が膨張(正常動作)\n"
        "\n"
        "<b>✅ 修正後WF再検証</b>\n"
        "OOS 5/5 PF&gt;1.0 | 集計PF=1.91 | 堅牢(GO)\n"
        "W1: PF=2.69 | W2: PF=1.03 | W3: PF=2.16\n"
        "W4: PF=11.14 | W5: PF=1.78\n"
        "\n"
        "<b>🧪 テスト: 83/83 PASS</b>\n"
        "\n"
        "<b>📝 修正内容</b>\n"
        "1. 同一銘柄クールダウン(2日)追加\n"
        "2. オープン中の銘柄への重複エントリー禁止\n"
        "→ 全Botに適用(既存Botへの影響なし)"
    )

    alert = TelegramAlert()
    await alert.send_message(text)
    print("Telegram送信完了")


if __name__ == "__main__":
    asyncio.run(main())
