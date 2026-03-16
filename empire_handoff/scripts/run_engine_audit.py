"""バックテストエンジン修正前後比較スクリプト

修正内容:
1. MDD: トレード確定ベース → equity_curve（含み損込み）ベース
2. Sharpe: トレード単位PnL × √252 → 日次リターン × √365
3. ポジションサイズ上限: 青天井 → initial_capital × max_position_pct(50%)
4. MinCapital: equity_curveから最小値
"""
import asyncio
import sys
import copy
import yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine


def safe_pf(r):
    pf = r.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start, end = '2024-01-01', '2026-03-01'
    leverage = 2

    bots = ['surge', 'meanrevert', 'weakshort', 'alpha', 'sniper', 'scalp']
    labels = {
        'surge': 'Surge', 'meanrevert': 'MeanRevert', 'weakshort': 'WeakShort',
        'alpha': 'Alpha', 'sniper': 'Sniper', 'scalp': 'Scalp',
    }

    # 修正前の値（前回セッションの結果）
    before = {
        'surge':     {'pf': 3.26, 'ret': 89.4,  'mdd': -5.5,  'sharpe': 5.02},
        'meanrevert':{'pf': 2.18, 'ret': 580.6, 'mdd': -4.9,  'sharpe': 6.26},
        'weakshort': {'pf': 2.17, 'ret': 54.2,  'mdd': -3.3,  'sharpe': 3.95},
        'alpha':     {'pf': 2.32, 'ret': 12.2,  'mdd': -5.1,  'sharpe': 1.43},
        'sniper':    {'pf': 3.38, 'ret': 50.0,  'mdd': -5.1,  'sharpe': 3.44},
        'scalp':     {'pf': 1.71, 'ret': 2084.2,'mdd': -31.0, 'sharpe': 3.26},
    }

    print("=" * 90)
    print(f"  バックテストエンジン修正前後比較 (lev={leverage}x, {start}〜{end})")
    print("=" * 90)
    print(f"\n  修正内容:")
    print(f"  1. MDD: トレード確定ベース → equity_curve（含み損込み）ベース")
    print(f"  2. Sharpe: トレードPnL × √252 → 日次リターン × √365")
    print(f"  3. ポジサイズ上限: 青天井 → initial × max_position_pct(50%)")
    print(f"  4. MinCapital: equity_curveの最小値を追跡")

    telegram_lines = ["<b>📊 バックテストエンジン修正前後比較</b>", f"統一レバ: {leverage}x  期間: {start}〜{end}", ""]

    # ヘッダー
    print(f"\n  {'Bot':>12s} │ {'PF':>6s}→{'PF':>6s} │ {'Ret':>9s}→{'Ret':>9s} │ {'MDD':>7s}→{'MDD':>7s} │ {'Sharpe':>6s}→{'Sharpe':>6s} │ {'MinCap':>12s}")
    print(f"  {'':12s} │ {'(旧)':>6s} {'(新)':>6s} │ {'(旧)':>9s} {'(新)':>9s} │ {'(旧)':>7s} {'(新)':>7s} │ {'(旧)':>6s} {'(新)':>6s} │")
    print(f"  {'─' * 12}─┼{'─' * 15}─┼{'─' * 21}─┼{'─' * 17}─┼{'─' * 15}─┼{'─' * 14}")

    all_results = {}

    for bot in bots:
        label = labels[bot]
        bot_config = copy.deepcopy(config.get(f'bot_{bot}', {}))
        bot_config['leverage'] = leverage

        engine = BacktestEngine(bot, bot_config, db)
        r = engine.run(start, end)
        all_results[bot] = r

        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        sharpe = r.get('sharpe_ratio', 0)
        min_cap = r.get('min_capital', 0)
        trades = r.get('total_trades', 0)

        old = before.get(bot, {})
        old_pf = old.get('pf', 0)
        old_ret = old.get('ret', 0)
        old_mdd = old.get('mdd', 0)
        old_sharpe = old.get('sharpe', 0)

        pf_s = f"{pf:.2f}" if pf < 999 else "inf"
        old_pf_s = f"{old_pf:.2f}" if old_pf < 999 else "inf"

        print(f"  {label:>12s} │ {old_pf_s:>6s} {pf_s:>6s} │ {old_ret:+8.1f}% {ret:+8.1f}% │ {old_mdd:>6.1f}% {mdd:>6.1f}% │ {old_sharpe:>6.2f} {sharpe:>6.2f} │ {min_cap:>12,.0f}")

        telegram_lines.append(f"<b>{label}</b> (T={trades})")
        telegram_lines.append(f"  PF: {old_pf_s}→{pf_s}  Ret: {old_ret:+.1f}%→{ret:+.1f}%")
        telegram_lines.append(f"  MDD: {old_mdd:.1f}%→{mdd:.1f}%  Sharpe: {old_sharpe:.2f}→{sharpe:.2f}")
        telegram_lines.append(f"  MinCap: ¥{min_cap:,.0f}")

    # MeanRevert月別（lev=10）
    print(f"\n{'─' * 90}")
    print(f"  MeanRevert月別残高推移 (lev=10x)")
    print(f"{'─' * 90}")

    mr_config = copy.deepcopy(config.get('bot_meanrevert', {}))
    mr_config['leverage'] = 10
    engine = BacktestEngine('meanrevert', mr_config, db)
    r10 = engine.run(start, end)

    monthly_equity = {}
    for ec in r10.get('equity_curve', []):
        month = ec['date'][:7]
        monthly_equity[month] = ec['capital']

    telegram_lines.append("")
    telegram_lines.append("<b>MeanRevert月別 (10x)</b>")
    for month, eq in sorted(monthly_equity.items()):
        ret_pct = (eq - 1_000_000) / 1_000_000 * 100
        print(f"    {month}: ¥{eq:>14,.0f}  ({ret_pct:+.1f}%)")

    # 要約
    final_10x = r10.get('final_capital', 0)
    mdd_10x = r10.get('max_drawdown_pct', 0)
    min_10x = r10.get('min_capital', 0)
    telegram_lines.append(f"  Final: ¥{final_10x:,.0f} MDD:{mdd_10x:.1f}% MinCap:¥{min_10x:,.0f}")

    # Telegram
    text = "\n".join(telegram_lines)
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        await alert.send_message(text)
        print("\n📱 Telegram送信完了")
    except Exception as e:
        print(f"\n⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
