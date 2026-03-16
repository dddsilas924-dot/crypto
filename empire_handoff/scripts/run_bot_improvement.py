"""Bot改良 3タスク一括実行スクリプト

Task 1: MeanRevert レバレッジ検証 (1x, 2x, 3x, 5x, 10x)
Task 2: Fear<25 ロング3Bot (FearDip, SectorLead, ShortSqueeze)
Task 3: ハイレバ小口3Bot (Sniper, Scalp, Event)
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


def safe_pf(results):
    pf = results.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


def check_bankruptcy(results):
    capital = 1_000_000
    min_capital = capital
    for t in results.get('trades', []):
        capital += t.get('pnl_amount', 0)
        min_capital = min(min_capital, capital)
        if capital <= 0:
            return True, min_capital, capital
    return False, min_capital, capital


def run_backtest(bot_type, bot_config, db, start='2024-01-01', end='2026-03-01'):
    engine = BacktestEngine(bot_type, bot_config, db)
    results = engine.run(start, end)
    return results


def run_walkforward(bot_type, bot_config, db):
    """WF検証: OOS PF集計"""
    WINDOWS = [
        {"name": "W1", "is_start": "2024-01-01", "is_end": "2024-12-31", "oos_start": "2025-01-01", "oos_end": "2025-03-31"},
        {"name": "W2", "is_start": "2024-04-01", "is_end": "2025-03-31", "oos_start": "2025-04-01", "oos_end": "2025-06-30"},
        {"name": "W3", "is_start": "2024-07-01", "is_end": "2025-06-30", "oos_start": "2025-07-01", "oos_end": "2025-09-30"},
        {"name": "W4", "is_start": "2024-10-01", "is_end": "2025-09-30", "oos_start": "2025-10-01", "oos_end": "2025-12-31"},
        {"name": "W5", "is_start": "2025-01-01", "is_end": "2025-12-31", "oos_start": "2026-01-01", "oos_end": "2026-03-01"},
    ]

    window_results = []
    total_profit = 0.0
    total_loss = 0.0
    oos_pf_positive = 0
    n_with_trades = 0

    for w in WINDOWS:
        engine_oos = BacktestEngine(bot_type, bot_config, db)
        r_oos = engine_oos.run(w['oos_start'], w['oos_end'])
        oos_pf = safe_pf(r_oos)
        oos_trades = r_oos.get('total_trades', 0)

        if oos_trades > 0:
            n_with_trades += 1
            if oos_pf > 1.0:
                oos_pf_positive += 1

        for t in r_oos.get('trades', []):
            pnl = t.get('pnl_amount', 0)
            if pnl > 0:
                total_profit += pnl
            else:
                total_loss += abs(pnl)

        window_results.append({
            'window': w['name'],
            'oos_trades': oos_trades,
            'oos_pf': oos_pf,
            'oos_return': r_oos.get('total_return_pct', 0),
        })

        print(f"    {w['name']}: OOS trades={oos_trades:3d}  PF={oos_pf:5.2f}  return={r_oos.get('total_return_pct', 0):+6.1f}%")

    agg_pf = total_profit / total_loss if total_loss > 0 else 0

    if n_with_trades == 0:
        verdict = "データ不足"
    elif oos_pf_positive == n_with_trades:
        verdict = "堅牢（実運用GO）"
    elif oos_pf_positive >= n_with_trades * 0.8:
        verdict = "概ね堅牢（条件付きGO）"
    else:
        verdict = "過学習の疑い"

    return {
        'window_results': window_results,
        'agg_pf': agg_pf,
        'oos_pf_positive': oos_pf_positive,
        'n_with_trades': n_with_trades,
        'verdict': verdict,
    }


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()

    telegram_lines = ["<b>📊 Bot改良 3タスク一括結果</b>", ""]

    # ========================================
    # Task 1: MeanRevert レバレッジ検証
    # ========================================
    print("=" * 70)
    print("  Task 1: MeanRevert レバレッジ検証 (pyramid:off)")
    print("=" * 70)

    telegram_lines.append("<b>📈 Task1: MeanRevert レバレッジ検証</b>")
    leverages = [1, 2, 3, 5, 10]
    mr_config = config.get('bot_meanrevert', {})
    task1_rows = []

    print(f"  {'Lev':>4s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>10s} {'MDD':>8s} {'Sharpe':>8s} {'MinCap':>12s} {'MaxLoss':>10s} {'破産':>4s}")

    for lev in leverages:
        lev_config = copy.deepcopy(mr_config)
        lev_config['leverage'] = lev
        lev_config['pyramid'] = False

        r = run_backtest('meanrevert', lev_config, db)
        bankrupt, min_cap, final_cap = check_bankruptcy(r)

        trades = r.get('total_trades', 0)
        wr = r.get('win_rate', 0)
        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        sharpe = r.get('sharpe_ratio', 0)

        # 最大単発損失
        max_single_loss = 0
        for t in r.get('trades', []):
            loss = t.get('pnl_amount', 0)
            if loss < max_single_loss:
                max_single_loss = loss

        pf_str = f"{pf:.2f}" if pf < 999 else "inf"
        bank_str = "YES" if bankrupt else "No"

        print(f"  {lev:>3d}x {trades:7d} {wr:5.1f}% {pf_str:>7s} {ret:+9.1f}% {mdd:7.1f}% {sharpe:8.2f} {min_cap:12,.0f} {max_single_loss:+10,.0f} {bank_str:>4s}")

        task1_rows.append({
            'lev': lev, 'trades': trades, 'wr': wr, 'pf': pf,
            'ret': ret, 'mdd': mdd, 'sharpe': sharpe,
            'min_cap': min_cap, 'max_single_loss': max_single_loss, 'bankrupt': bankrupt,
        })

    # 推奨レバ: 破産なし + 最高Sharpe
    safe_rows = [r for r in task1_rows if not r['bankrupt']]
    if safe_rows:
        best_lev = max(safe_rows, key=lambda x: x['sharpe'])
        recommended = f"{best_lev['lev']}x (Sharpe={best_lev['sharpe']:.2f})"
    else:
        recommended = "全レバレッジで破産リスク"
    print(f"\n  推奨レバレッジ: {recommended}")

    for r in task1_rows:
        bank_s = " ⚠破産" if r['bankrupt'] else ""
        telegram_lines.append(f"  {r['lev']}x: Ret={r['ret']:+.1f}% PF={r['pf']:.2f} MDD={r['mdd']:.1f}% MinCap={r['min_cap']:,.0f}{bank_s}")
    telegram_lines.append(f"  推奨: {recommended}")
    telegram_lines.append("")

    # ========================================
    # Task 2: Fear<25 ロング3Bot
    # ========================================
    print("\n" + "=" * 70)
    print("  Task 2: Fear<25 ロング3Bot (FearDip, SectorLead, ShortSqueeze)")
    print("=" * 70)

    telegram_lines.append("<b>📈 Task2: Fear&lt;25 ロング3Bot</b>")
    task2_bots = ['feardip', 'sectorlead', 'shortsqueeze']
    task2_labels = {'feardip': 'FearDip', 'sectorlead': 'SectorLead', 'shortsqueeze': 'ShortSqueeze'}
    task2_results = {}

    for bot in task2_bots:
        label = task2_labels[bot]
        bot_config = config.get(f'bot_{bot}', {})
        print(f"\n  --- {label} ---")
        r = run_backtest(bot, bot_config, db)
        task2_results[bot] = r

        trades = r.get('total_trades', 0)
        wr = r.get('win_rate', 0)
        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        sharpe = r.get('sharpe_ratio', 0)
        final = r.get('final_capital', 0)

        pf_str = f"{pf:.2f}" if pf < 999 else "inf"
        print(f"  Trades={trades}  WR={wr:.1f}%  PF={pf_str}  Return={ret:+.1f}%  MDD={mdd:.1f}%  Sharpe={sharpe:.2f}  Final=¥{final:,.0f}")

        # WF (PF>1.5判定)
        if trades > 0 and pf >= 1.5:
            print(f"  → PF>=1.5 → WF検証実施")
            wf = run_walkforward(bot, bot_config, db)
            telegram_lines.append(f"  {label}: PF={pf_str} Trades={trades} WR={wr:.1f}%")
            telegram_lines.append(f"    WF: OOS集計PF={wf['agg_pf']:.2f} ({wf['oos_pf_positive']}/{wf['n_with_trades']}win)")
            telegram_lines.append(f"    判定: {wf['verdict']}")
            task2_results[bot]['wf'] = wf
        elif trades > 0:
            print(f"  → PF={pf_str} 未達（PF>=1.5基準）→ WFスキップ")
            telegram_lines.append(f"  {label}: PF={pf_str} Trades={trades} → PF未達")
        else:
            print(f"  → トレードなし")
            telegram_lines.append(f"  {label}: トレードなし")

    telegram_lines.append("")

    # ========================================
    # Task 3: ハイレバ小口3Bot
    # ========================================
    print("\n" + "=" * 70)
    print("  Task 3: ハイレバ小口3Bot (Sniper, Scalp, Event)")
    print("  (資金5%, レバ10x)")
    print("=" * 70)

    telegram_lines.append("<b>📈 Task3: ハイレバ小口3Bot (5%×10x)</b>")
    task3_bots = ['sniper', 'scalp', 'event']
    task3_labels = {'sniper': 'Sniper', 'scalp': 'Scalp', 'event': 'Event'}
    task3_results = {}

    for bot in task3_bots:
        label = task3_labels[bot]
        bot_config = config.get(f'bot_{bot}', {})
        print(f"\n  --- {label} ---")
        r = run_backtest(bot, bot_config, db)
        task3_results[bot] = r
        bankrupt, min_cap, final_cap = check_bankruptcy(r)

        trades = r.get('total_trades', 0)
        wr = r.get('win_rate', 0)
        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        sharpe = r.get('sharpe_ratio', 0)

        pf_str = f"{pf:.2f}" if pf < 999 else "inf"
        bank_str = "⚠破産" if bankrupt else "安全"
        print(f"  Trades={trades}  WR={wr:.1f}%  PF={pf_str}  Return={ret:+.1f}%  MDD={mdd:.1f}%")
        print(f"  MinCap=¥{min_cap:,.0f}  破産判定={bank_str}")

        # 破産確率シミュレーション (モンテカルロ)
        bankruptcy_prob = 0.0
        if trades >= 5:
            pnl_list = [t.get('pnl_amount', 0) for t in r.get('trades', [])]
            import numpy as np
            np.random.seed(42)
            n_sim = 10000
            bankruptcies = 0
            for _ in range(n_sim):
                sim_capital = 1_000_000.0
                shuffled = np.random.choice(pnl_list, size=len(pnl_list), replace=True)
                for pnl in shuffled:
                    sim_capital += pnl
                    if sim_capital <= 0:
                        bankruptcies += 1
                        break
            bankruptcy_prob = bankruptcies / n_sim * 100
            print(f"  モンテカルロ破産確率: {bankruptcy_prob:.1f}% ({n_sim}回試行)")

        telegram_lines.append(f"  {label}: PF={pf_str} Trades={trades} WR={wr:.1f}% Ret={ret:+.1f}%")
        if bankruptcy_prob > 0:
            telegram_lines.append(f"    破産確率={bankruptcy_prob:.1f}% MDD={mdd:.1f}%")
        else:
            telegram_lines.append(f"    {bank_str} MDD={mdd:.1f}%")

    telegram_lines.append("")

    # ========================================
    # 全Bot PFランキング
    # ========================================
    print("\n" + "=" * 70)
    print("  全Bot PFランキング")
    print("=" * 70)

    all_bots_for_rank = ['alpha', 'surge', 'momentum', 'rebound', 'stability',
                          'trend', 'cascade', 'meanrevert', 'breakout', 'btcfollow', 'weakshort']
    rankings = []

    for bot in all_bots_for_rank:
        bot_config = config.get(f'bot_{bot}', {})
        r = run_backtest(bot, bot_config, db)
        rankings.append({
            'bot': bot, 'pf': safe_pf(r),
            'trades': r.get('total_trades', 0),
            'wr': r.get('win_rate', 0),
            'ret': r.get('total_return_pct', 0),
        })

    # Task2/3のbotも追加
    for bot in task2_bots + task3_bots:
        r = task2_results.get(bot, task3_results.get(bot, {}))
        rankings.append({
            'bot': bot, 'pf': safe_pf(r),
            'trades': r.get('total_trades', 0),
            'wr': r.get('win_rate', 0),
            'ret': r.get('total_return_pct', 0),
        })

    rankings.sort(key=lambda x: x['pf'], reverse=True)

    telegram_lines.append("<b>📊 全Bot PFランキング</b>")
    print(f"  {'Rank':>4s} {'Bot':>15s} {'PF':>7s} {'Trades':>7s} {'WR':>6s} {'Return':>10s}")
    for i, r in enumerate(rankings, 1):
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 999 else "inf"
        print(f"  {i:>4d} {r['bot']:>15s} {pf_str:>7s} {r['trades']:7d} {r['wr']:5.1f}% {r['ret']:+9.1f}%")
        if i <= 10:
            telegram_lines.append(f"  {i}. {r['bot']}: PF={pf_str} T={r['trades']} Ret={r['ret']:+.1f}%")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    telegram_lines.append(f"\n⏱️ {elapsed:.1f}秒")

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
