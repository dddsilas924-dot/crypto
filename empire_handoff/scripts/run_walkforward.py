"""ウォークフォワード検証スクリプト

使い方:
  python scripts/run_walkforward.py --bot surge
  python scripts/run_walkforward.py --bot alpha
  python scripts/run_walkforward.py --bot both
"""
import asyncio
import argparse
import csv
import os
import sys
import yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# ウォークフォワード ウィンドウ定義
# IS 12ヶ月 / OOS 3ヶ月、3ヶ月スライド
WINDOWS = [
    {"name": "W1", "is_start": "2024-01-01", "is_end": "2024-12-31", "oos_start": "2025-01-01", "oos_end": "2025-03-31"},
    {"name": "W2", "is_start": "2024-04-01", "is_end": "2025-03-31", "oos_start": "2025-04-01", "oos_end": "2025-06-30"},
    {"name": "W3", "is_start": "2024-07-01", "is_end": "2025-06-30", "oos_start": "2025-07-01", "oos_end": "2025-09-30"},
    {"name": "W4", "is_start": "2024-10-01", "is_end": "2025-09-30", "oos_start": "2025-10-01", "oos_end": "2025-12-31"},
    {"name": "W5", "is_start": "2025-01-01", "is_end": "2025-12-31", "oos_start": "2026-01-01", "oos_end": "2026-03-01"},
]


def safe_pf(results: dict) -> float:
    pf = results.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


def run_walkforward(bot_type: str, bot_config: dict, db: HistoricalDB) -> dict:
    bot_labels = {
        'alpha': 'Bot-Alpha', 'surge': 'Bot-Surge',
        'momentum': 'Bot-Momentum', 'rebound': 'Bot-Rebound', 'stability': 'Bot-Stability',
    }
    label = bot_labels.get(bot_type, f"Bot-{bot_type.title()}")
    print(f"\n{'═' * 60}")
    print(f"  {label} ウォークフォワード検証")
    print(f"{'═' * 60}")

    window_results = []

    for w in WINDOWS:
        print(f"\n  {w['name']}: IS {w['is_start']}〜{w['is_end']} | OOS {w['oos_start']}〜{w['oos_end']}")

        engine_is = BacktestEngine(bot_type, bot_config, db)
        r_is = engine_is.run(w['is_start'], w['is_end'])

        engine_oos = BacktestEngine(bot_type, bot_config, db)
        r_oos = engine_oos.run(w['oos_start'], w['oos_end'])

        is_pf = safe_pf(r_is)
        oos_pf = safe_pf(r_oos)
        pf_degradation = (1 - oos_pf / is_pf) * 100 if is_pf > 0 else 0

        row = {
            'window': w['name'],
            'oos_period': f"{w['oos_start']}〜{w['oos_end']}",
            'is_trades': r_is.get('total_trades', 0),
            'is_wr': r_is.get('win_rate', 0),
            'is_pf': is_pf,
            'is_return': r_is.get('total_return_pct', 0),
            'oos_trades': r_oos.get('total_trades', 0),
            'oos_wr': r_oos.get('win_rate', 0),
            'oos_pf': oos_pf,
            'oos_return': r_oos.get('total_return_pct', 0),
            'oos_mdd': r_oos.get('max_drawdown_pct', 0),
            'pf_degradation': pf_degradation,
            'oos_trades_detail': r_oos.get('trades', []),
        }
        window_results.append(row)

        print(f"    IS:  trades={row['is_trades']:3d}  WR={row['is_wr']:5.1f}%  PF={row['is_pf']:5.2f}  return={row['is_return']:+6.1f}%")
        print(f"    OOS: trades={row['oos_trades']:3d}  WR={row['oos_wr']:5.1f}%  PF={row['oos_pf']:5.2f}  return={row['oos_return']:+6.1f}%  MDD={row['oos_mdd']:.1f}%  PF劣化={row['pf_degradation']:+.0f}%")

    # --- Table 1: IS/OOS比較 ---
    print(f"\n{'─' * 60}")
    print(f"  Table 1: {label} IS/OOS比較")
    print(f"{'─' * 60}")
    print(f"  {'Win':4s} {'IS_T':>5s} {'IS_WR':>6s} {'IS_PF':>6s} {'IS_Ret':>7s} {'OOS_T':>5s} {'OOS_WR':>7s} {'OOS_PF':>7s} {'OOS_Ret':>8s} {'OOS_DD':>7s} {'PF劣化':>7s}")
    for r in window_results:
        print(f"  {r['window']:4s} {r['is_trades']:5d} {r['is_wr']:5.1f}% {r['is_pf']:6.2f} {r['is_return']:+6.1f}% {r['oos_trades']:5d} {r['oos_wr']:6.1f}% {r['oos_pf']:7.2f} {r['oos_return']:+7.1f}% {r['oos_mdd']:6.1f}% {r['pf_degradation']:+6.0f}%")

    # --- Table 3: OOS集計 ---
    print(f"\n{'─' * 60}")
    print(f"  Table 3: OOS期間のみ集計 ({label})")
    print(f"{'─' * 60}")
    print(f"  {'Win':4s} {'OOS期間':24s} {'Trades':>7s} {'WR':>6s} {'PF':>6s} {'Return':>8s} {'MDD':>7s}")

    total_oos_trades = 0
    total_oos_wins = 0
    total_oos_profit = 0.0
    total_oos_loss = 0.0
    total_oos_return = 0.0
    max_oos_mdd = 0.0
    oos_pf_positive = 0
    oos_return_positive = 0
    worst_window = None
    worst_pf = float('inf')

    for r in window_results:
        print(f"  {r['window']:4s} {r['oos_period']:24s} {r['oos_trades']:7d} {r['oos_wr']:5.1f}% {r['oos_pf']:6.2f} {r['oos_return']:+7.1f}% {r['oos_mdd']:6.1f}%")
        total_oos_trades += r['oos_trades']
        if r['oos_trades'] > 0:
            total_oos_wins += int(r['oos_wr'] / 100 * r['oos_trades'])
        for t in r['oos_trades_detail']:
            pnl = t.get('pnl_amount', 0)
            if pnl > 0:
                total_oos_profit += pnl
            else:
                total_oos_loss += abs(pnl)
        total_oos_return += r['oos_return']
        max_oos_mdd = min(max_oos_mdd, r['oos_mdd'])
        if r['oos_pf'] > 1.0 and r['oos_trades'] > 0:
            oos_pf_positive += 1
        if r['oos_return'] > 0:
            oos_return_positive += 1
        if r['oos_trades'] > 0 and r['oos_pf'] < worst_pf:
            worst_pf = r['oos_pf']
            worst_window = r

    agg_wr = total_oos_wins / total_oos_trades * 100 if total_oos_trades > 0 else 0
    agg_pf = total_oos_profit / total_oos_loss if total_oos_loss > 0 else 0
    print(f"  {'合計':4s} {'':24s} {total_oos_trades:7d} {agg_wr:5.1f}% {agg_pf:6.2f} {total_oos_return:+7.1f}% {max_oos_mdd:6.1f}%")

    # --- Table 4: 安定性指標 ---
    n_windows = len(window_results)
    n_with_trades = sum(1 for r in window_results if r['oos_trades'] > 0)

    engine_full = BacktestEngine(bot_type, bot_config, db)
    r_full = engine_full.run('2024-01-01', '2026-03-01')
    full_pf = safe_pf(r_full)
    full_wr = r_full.get('win_rate', 0)
    pf_degradation_vs_full = (1 - agg_pf / full_pf) * 100 if full_pf > 0 else 0

    print(f"\n{'─' * 60}")
    print(f"  Table 4: 安定性指標 ({label})")
    print(f"{'─' * 60}")
    print(f"  OOS PF > 1.0:      {oos_pf_positive}/{n_with_trades} ウィンドウ")
    print(f"  OOS Return > 0%:   {oos_return_positive}/{n_windows} ウィンドウ")
    print(f"  OOS集計PF:         {agg_pf:.2f}  (全期間PF: {full_pf:.2f}, 劣化率: {pf_degradation_vs_full:+.0f}%)")
    print(f"  OOS集計WR:         {agg_wr:.1f}%  (全期間WR: {full_wr:.1f}%)")

    # 判定
    if n_with_trades == 0:
        verdict = "データ不足（判定不能）"
    elif oos_pf_positive == n_with_trades:
        verdict = "堅牢（実運用GO）"
    elif oos_pf_positive >= n_with_trades * 0.8:
        verdict = "概ね堅牢（条件付きGO）"
    else:
        verdict = "過学習の疑い（要調整）"

    if agg_pf >= full_pf * 0.5 and agg_pf > 1.0:
        pf_verdict = "許容範囲"
    else:
        pf_verdict = "要注意"
        if verdict == "堅牢（実運用GO）":
            verdict = "概ね堅牢（条件付きGO）"

    print(f"  判定:              {verdict}")
    print(f"  PF劣化:            {pf_verdict}")

    # 最悪OOSウィンドウ
    if worst_window and worst_window['oos_trades_detail']:
        print(f"\n  最悪OOSウィンドウ: {worst_window['window']} (PF={worst_window['oos_pf']:.2f})")
        for t in worst_window['oos_trades_detail']:
            pnl = t.get('pnl_leveraged_pct', 0)
            mark = '+' if pnl > 0 else ' '
            print(f"    {t['symbol']:20s} {t['entry_date']} {t.get('exit_reason','?'):7s} {mark}{pnl:.1f}%")

    return {
        'bot_type': bot_type,
        'window_results': window_results,
        'total_oos_trades': total_oos_trades,
        'agg_wr': agg_wr,
        'agg_pf': agg_pf,
        'total_oos_return': total_oos_return,
        'max_oos_mdd': max_oos_mdd,
        'full_pf': full_pf,
        'full_wr': full_wr,
        'oos_pf_positive': oos_pf_positive,
        'oos_return_positive': oos_return_positive,
        'n_with_trades': n_with_trades,
        'verdict': verdict,
        'pf_verdict': pf_verdict,
    }


def save_csv(summary: dict, bot_type: str):
    outdir = "vault/backtest_results/walkforward"
    os.makedirs(outdir, exist_ok=True)
    filepath = f"{outdir}/wf_{bot_type}.csv"
    rows = summary['window_results']
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['window', 'oos_period', 'is_trades', 'is_wr', 'is_pf', 'is_return',
                         'oos_trades', 'oos_wr', 'oos_pf', 'oos_return', 'oos_mdd', 'pf_degradation'])
        for r in rows:
            writer.writerow([r['window'], r['oos_period'], r['is_trades'], r['is_wr'], r['is_pf'],
                             r['is_return'], r['oos_trades'], r['oos_wr'], r['oos_pf'],
                             r['oos_return'], r['oos_mdd'], round(r['pf_degradation'], 1)])
    print(f"\n  📁 CSV保存: {filepath}")
    return filepath


def build_telegram_text(summaries: list) -> str:
    lines = ["<b>📊 ウォークフォワード検証結果</b>", "IS 12M / OOS 3M × 5ウィンドウ", ""]

    for s in summaries:
        label = "Bot-Alpha" if s['bot_type'] == 'alpha' else "Bot-Surge"
        note = "（参考値）" if s['bot_type'] == 'alpha' else ""
        lines.append(f"<b>📈 {label}{note}</b>")
        for r in s['window_results']:
            pf_str = f"{r['oos_pf']:.2f}" if r['oos_trades'] > 0 else "N/A"
            ret_str = f"{r['oos_return']:+.1f}%" if r['oos_trades'] > 0 else "N/A"
            lines.append(f"  {r['window']}: PF={pf_str} Ret={ret_str} ({r['oos_trades']}t)")
        lines.append(f"  集計: PF={s['agg_pf']:.2f} WR={s['agg_wr']:.0f}% Ret={s['total_oos_return']:+.1f}%")
        lines.append(f"  全期間PF: {s['full_pf']:.2f} → OOS集計: {s['agg_pf']:.2f}")
        lines.append(f"  PF>1.0: {s['oos_pf_positive']}/{s['n_with_trades']}win")
        lines.append(f"  <b>判定: {s['verdict']}</b>")
        lines.append("")

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="ウォークフォワード検証")
    ALL_BOTS = ['alpha', 'surge', 'momentum', 'rebound', 'stability',
                 'trend', 'cascade', 'meanrevert', 'breakout', 'btcfollow', 'weakshort',
                 'feardip', 'sectorlead', 'shortsqueeze', 'sniper', 'scalp', 'event',
                 'volexhaust', 'fearflat', 'domshift', 'gaptrap', 'sectorsync',
                 'meanrevert_adaptive', 'meanrevert_tight', 'meanrevert_hybrid',
                 'meanrevert_newlist', 'meanrevert_tuned',
                 'ico_meanrevert', 'ico_rebound', 'ico_surge']
    parser.add_argument('--bot', choices=ALL_BOTS + ['both'], default='both')
    args = parser.parse_args()

    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()
    bots = ['alpha', 'surge'] if args.bot == 'both' else [args.bot]

    summaries = []
    for bot_type in bots:
        bot_config = config.get(f'bot_{bot_type}', {})
        summary = run_walkforward(bot_type, bot_config, db)
        save_csv(summary, bot_type)
        summaries.append(summary)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    # Telegram送信
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        text = build_telegram_text(summaries) + f"\n⏱️ {elapsed:.1f}秒"
        await alert.send_message(text)
        print("📱 Telegram送信完了")
    except Exception as e:
        print(f"⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
