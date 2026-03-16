"""主力Bot レバレッジ別比較（修正済みエンジン）

対象: Surge, MeanRevert, WeakShort, Alpha, Sniper, Scalp
レバレッジ: 1x, 2x, 3x, 5x, 10x, 20x
Table 1: レバレッジ別比較
Table 2: 破産分析
Table 3: 推奨レバレッジ
"""
import asyncio
import sys
import copy
import yaml
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

BOTS = ['surge', 'meanrevert', 'weakshort', 'alpha', 'sniper', 'scalp']
BOT_LABELS = {
    'surge': 'Surge', 'meanrevert': 'MeanRevert', 'weakshort': 'WeakShort',
    'alpha': 'Alpha', 'sniper': 'Sniper', 'scalp': 'Scalp',
}
LEVERAGES = [1, 2, 3, 5, 10, 20]


def safe_pf(r):
    pf = r.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


def analyze_trades(results):
    """トレード詳細分析"""
    trades = results.get('trades', [])
    if not trades:
        return {
            'max_consecutive_loss': 0, 'max_single_loss': 0,
            'min_capital': results.get('min_capital', 1_000_000),
            'below_10pct_count': 0,
        }

    # 連続最大負け数
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t.get('pnl_amount', 0) < 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    # 最大1トレード損失額
    max_single_loss = min(t.get('pnl_amount', 0) for t in trades)

    # MinCapが初期資金の10%以下になった回数
    capital = 1_000_000
    below_10pct = 0
    for t in trades:
        capital += t.get('pnl_amount', 0)
        if capital <= 100_000:
            below_10pct += 1

    return {
        'max_consecutive_loss': max_streak,
        'max_single_loss': max_single_loss,
        'min_capital': results.get('min_capital', 1_000_000),
        'below_10pct_count': below_10pct,
    }


def calc_ruin_prob(wr, n_consec=20):
    """WRで n_consec 連敗する確率"""
    if wr >= 100:
        return 0.0
    loss_rate = 1 - wr / 100
    return loss_rate ** n_consec * 100


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start, end = '2024-01-01', '2026-03-01'
    start_time = datetime.now()

    all_rows = []

    # ========================================
    # Table 1: レバレッジ別比較
    # ========================================
    print("=" * 110)
    print("  Table 1: 主力Bot レバレッジ別比較")
    print(f"  期間: {start}〜{end}  コスト: 0.22%/RT  pyramid: OFF  max_position_pct: 50")
    print("=" * 110)
    print(f"  {'Bot':>12s} {'Lev':>4s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>12s} {'MDD':>8s} {'Sharpe':>8s} {'MinCap':>12s} {'破産':>4s}")
    print(f"  {'─' * 108}")

    for bot in BOTS:
        label = BOT_LABELS[bot]
        base_config = config.get(f'bot_{bot}', {})

        for lev in LEVERAGES:
            cfg = copy.deepcopy(base_config)
            cfg['leverage'] = lev
            cfg['pyramid'] = False

            engine = BacktestEngine(bot, cfg, db)
            r = engine.run(start, end)

            trades_detail = analyze_trades(r)
            bankrupt = trades_detail['min_capital'] <= 0

            trades = r.get('total_trades', 0)
            wr = r.get('win_rate', 0)
            pf = safe_pf(r)
            ret = r.get('total_return_pct', 0)
            mdd = r.get('max_drawdown_pct', 0)
            sharpe = r.get('sharpe_ratio', 0)
            min_cap = r.get('min_capital', 1_000_000)

            pf_str = f"{pf:.2f}" if pf < 999 else "inf"
            bank_str = "YES" if bankrupt else "No"

            print(f"  {label:>12s} {lev:>3d}x {trades:7d} {wr:5.1f}% {pf_str:>7s} {ret:+11.1f}% {mdd:7.1f}% {sharpe:8.2f} {min_cap:>12,.0f} {bank_str:>4s}")

            all_rows.append({
                'bot': bot, 'label': label, 'lev': lev,
                'trades': trades, 'wr': wr, 'pf': pf,
                'ret': ret, 'mdd': mdd, 'sharpe': sharpe,
                'min_cap': min_cap, 'bankrupt': bankrupt,
                'max_consec_loss': trades_detail['max_consecutive_loss'],
                'max_single_loss': trades_detail['max_single_loss'],
                'below_10pct': trades_detail['below_10pct_count'],
            })

        print(f"  {'─' * 108}")

    # ========================================
    # Table 2: 破産分析
    # ========================================
    print(f"\n{'=' * 110}")
    print("  Table 2: 破産分析")
    print(f"{'=' * 110}")
    print(f"  {'Bot':>12s} {'Lev':>4s} {'MinCap':>12s} {'<10%回数':>8s} {'最大連敗':>8s} {'最大1T損失':>14s} {'20連敗確率':>10s} {'破産':>4s}")
    print(f"  {'─' * 108}")

    for row in all_rows:
        ruin = calc_ruin_prob(row['wr'], 20)
        ruin_str = f"{ruin:.1e}%" if ruin < 0.01 else f"{ruin:.4f}%"
        bank_str = "YES" if row['bankrupt'] else "No"
        print(f"  {row['label']:>12s} {row['lev']:>3d}x {row['min_cap']:>12,.0f} {row['below_10pct']:>8d} {row['max_consec_loss']:>8d} {row['max_single_loss']:>+14,.0f} {ruin_str:>10s} {bank_str:>4s}")

    # ========================================
    # Table 3: 推奨レバレッジ
    # ========================================
    print(f"\n{'=' * 110}")
    print("  Table 3: 推奨レバレッジ")
    print(f"{'=' * 110}")
    print(f"  {'Bot':>12s} │ {'保守的':>8s} (MDD>-10%) │ {'積極的':>8s} (MDD>-20%) │ {'最大許容':>8s} (破産なし) │ {'理由'}")
    print(f"  {'─' * 100}")

    telegram_lines = [
        "<b>📊 主力Bot レバレッジ別比較</b>",
        f"期間: {start}〜{end}  コスト: 0.22%/RT",
        "",
    ]

    for bot in BOTS:
        label = BOT_LABELS[bot]
        bot_rows = [r for r in all_rows if r['bot'] == bot]

        # 保守的: MDD > -10%
        conservative = [r for r in bot_rows if r['mdd'] > -10 and not r['bankrupt']]
        cons_lev = max(r['lev'] for r in conservative) if conservative else 0

        # 積極的: MDD > -20%
        aggressive = [r for r in bot_rows if r['mdd'] > -20 and not r['bankrupt']]
        agg_lev = max(r['lev'] for r in aggressive) if aggressive else 0

        # 最大許容: 破産しない最大レバ
        safe = [r for r in bot_rows if not r['bankrupt']]
        max_lev = max(r['lev'] for r in safe) if safe else 0

        # 最適Sharpe（保守範囲内）
        if conservative:
            best_sharpe_row = max(conservative, key=lambda x: x['sharpe'])
            reason = f"Sharpe最大={best_sharpe_row['sharpe']:.2f}@{best_sharpe_row['lev']}x"
        else:
            reason = "全レバMDD>10%"

        cons_str = f"{cons_lev}x" if cons_lev > 0 else "N/A"
        agg_str = f"{agg_lev}x" if agg_lev > 0 else "N/A"
        max_str = f"{max_lev}x" if max_lev > 0 else "N/A"

        print(f"  {label:>12s} │ {cons_str:>8s}          │ {agg_str:>8s}          │ {max_str:>8s}           │ {reason}")

        # Telegram
        telegram_lines.append(f"<b>{label}</b>")
        telegram_lines.append(f"  保守: {cons_str}  積極: {agg_str}  最大: {max_str}")

        # 破産するレバを列挙
        bankrupt_levs = [r['lev'] for r in bot_rows if r['bankrupt']]
        if bankrupt_levs:
            telegram_lines.append(f"  ⚠破産: {','.join(str(l)+'x' for l in bankrupt_levs)}")

        # 各レバのサマリー
        for r in bot_rows:
            pf_s = f"{r['pf']:.2f}" if r['pf'] < 999 else "inf"
            bank_s = " ⚠" if r['bankrupt'] else ""
            telegram_lines.append(f"  {r['lev']}x: Ret={r['ret']:+.1f}% MDD={r['mdd']:.1f}% PF={pf_s}{bank_s}")
        telegram_lines.append("")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    telegram_lines.append(f"⏱️ {elapsed:.1f}秒")

    # Telegram送信
    text = "\n".join(telegram_lines)
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        await alert.send_message(text)
        print("📱 Telegram送信完了")
    except Exception as e:
        print(f"⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
