"""ピラミッディング有無の比較スクリプト"""
import asyncio
import sys
import yaml
import copy
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

BOTS = ['surge', 'meanrevert', 'weakshort', 'alpha']
BOT_LABELS = {
    'surge': 'Surge', 'meanrevert': 'MnRevert', 'weakshort': 'WkShort', 'alpha': 'Alpha',
}


def run_bot(bot_type, config, db, pyramid, start='2024-01-01', end='2026-03-01'):
    bot_config = config.get(f'bot_{bot_type}', {}).copy()
    if pyramid:
        bot_config['pyramid'] = True
    engine = BacktestEngine(bot_type, bot_config, db)
    r = engine.run(start, end)
    return r


async def main():
    with open('config/settings.yaml') as f:
        config = yaml.safe_load(f)
    db = HistoricalDB()
    start, end = '2024-01-01', '2026-03-01'

    print("=" * 100)
    print("  Table 1: ピラミッディング比較表")
    print(f"  期間: {start} 〜 {end}")
    print("=" * 100)
    header = f"  {'Bot':10s} {'Mode':5s} {'Trades':>7s} {'WR':>6s} {'PF':>7s} {'Return':>10s} {'MDD':>8s} {'MaxSim':>7s} {'Pyramid':>8s} {'Skipped':>8s}"
    print(header)
    print("  " + "-" * 90)

    all_rows = []

    for bot_type in BOTS:
        for pyramid in [False, True]:
            r = run_bot(bot_type, config, db, pyramid, start, end)
            label = BOT_LABELS[bot_type]
            mode = "ON" if pyramid else "OFF"
            trades = r.get('total_trades', 0)
            wr = r.get('win_rate', 0)
            pf = r.get('profit_factor', 0)
            ret = r.get('total_return_pct', 0)
            mdd = r.get('max_drawdown_pct', 0)
            max_sim = r.get('max_simultaneous', 0)
            pyr_cnt = r.get('pyramid_count', 0)
            skip_cnt = r.get('skipped_count', 0)

            pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
            print(f"  {label:10s} {mode:5s} {trades:7d} {wr:5.1f}% {pf_str:>7s} {ret:+9.1f}% {mdd:7.1f}% {max_sim:7d} {pyr_cnt:8d} {skip_cnt:8d}")

            all_rows.append({
                'bot': bot_type, 'label': label, 'pyramid': pyramid, 'mode': mode,
                'trades': trades, 'wr': wr, 'pf': pf, 'return': ret, 'mdd': mdd,
                'max_sim': max_sim, 'pyr_cnt': pyr_cnt, 'skip_cnt': skip_cnt,
            })

    # Table 3: 効果サマリー
    print("\n" + "=" * 100)
    print("  Table 3: ピラミッディング効果サマリー")
    print("=" * 100)
    print(f"  {'Bot':10s} {'Trades':>12s} {'Return':>15s} {'MDD':>12s} {'PF':>12s} {'判定':>10s}")
    print("  " + "-" * 70)

    for bot_type in BOTS:
        off = next(r for r in all_rows if r['bot'] == bot_type and not r['pyramid'])
        on = next(r for r in all_rows if r['bot'] == bot_type and r['pyramid'])
        label = BOT_LABELS[bot_type]

        t_change = f"{off['trades']}→{on['trades']}"
        if off['return'] != 0:
            r_change = f"{off['return']:+.1f}→{on['return']:+.1f}%"
        else:
            r_change = f"→{on['return']:+.1f}%"
        m_change = f"{off['mdd']:.1f}→{on['mdd']:.1f}%"

        pf_off = off['pf'] if off['pf'] != float('inf') else 999
        pf_on = on['pf'] if on['pf'] != float('inf') else 999
        p_change = f"{pf_off:.2f}→{pf_on:.2f}"

        # 判定
        if pf_on > pf_off * 0.9 and on['return'] > off['return'] and abs(on['mdd']) < abs(off['mdd']) * 1.5:
            verdict = "ON推奨"
        elif pf_on >= pf_off * 0.8 and on['return'] > off['return']:
            verdict = "ON検討"
        else:
            verdict = "OFF推奨"

        print(f"  {label:10s} {t_change:>12s} {r_change:>15s} {m_change:>12s} {p_change:>12s} {verdict:>10s}")

    # WF for PF > 1.5 combinations
    print("\n" + "=" * 100)
    print("  Table 2: WF検証結果 (PF > 1.5)")
    print("=" * 100)

    wf_targets = [(r['bot'], r['pyramid']) for r in all_rows if r['pf'] > 1.5 and r['trades'] > 10]
    from scripts.run_walkforward import WINDOWS, run_walkforward, safe_pf

    wf_results = []
    for bot_type, pyramid in wf_targets:
        bot_config = config.get(f'bot_{bot_type}', {}).copy()
        if pyramid:
            bot_config['pyramid'] = True
        mode = "ON" if pyramid else "OFF"
        label = f"{BOT_LABELS[bot_type]}({mode})"

        summary = run_walkforward(bot_type, bot_config, db)
        oos_pfs = []
        for wr in summary['window_results']:
            if wr['oos_trades'] > 0:
                oos_pfs.append(wr['oos_pf'])

        n_above_1 = sum(1 for p in oos_pfs if p > 1.0)
        n_total = len(oos_pfs)
        agg_pf = summary['agg_pf']
        verdict = summary['verdict']

        oos_str = " ".join([f"W{i+1}:{p:.2f}" for i, p in enumerate(oos_pfs)])
        print(f"  {label:18s} OOS PF>1.0: {n_above_1}/{n_total}  集計PF: {agg_pf:.2f}  {verdict}")
        print(f"    {oos_str}")

        wf_results.append({
            'label': label, 'bot': bot_type, 'pyramid': pyramid,
            'n_above_1': n_above_1, 'n_total': n_total,
            'agg_pf': agg_pf, 'verdict': verdict, 'oos_pfs': oos_pfs,
        })

    # Telegram
    lines = ["<b>📊 ピラミッディング比較結果</b>", f"期間: {start} 〜 {end}", ""]
    lines.append("<b>Table 1: 比較表</b>")
    lines.append("Bot       Mode  Trades  WR    PF    Ret      MDD")
    for r in all_rows:
        pf_s = f"{r['pf']:.2f}" if r['pf'] != float('inf') else "inf"
        lines.append(f"{r['label']:9s} {r['mode']:4s} {r['trades']:5d} {r['wr']:4.0f}% {pf_s:>5s} {r['return']:+6.0f}% {r['mdd']:5.1f}%")

    lines.append("")
    lines.append("<b>Table 3: 効果サマリー</b>")
    for bot_type in BOTS:
        off = next(r for r in all_rows if r['bot'] == bot_type and not r['pyramid'])
        on = next(r for r in all_rows if r['bot'] == bot_type and r['pyramid'])
        label = BOT_LABELS[bot_type]
        pf_off = off['pf'] if off['pf'] != float('inf') else 999
        pf_on = on['pf'] if on['pf'] != float('inf') else 999
        if pf_on > pf_off * 0.9 and on['return'] > off['return'] and abs(on['mdd']) < abs(off['mdd']) * 1.5:
            v = "ON推奨"
        elif pf_on >= pf_off * 0.8 and on['return'] > off['return']:
            v = "ON検討"
        else:
            v = "OFF推奨"
        lines.append(f"{label}: PF {pf_off:.2f}→{pf_on:.2f} Ret {off['return']:+.0f}→{on['return']:+.0f}% → {v}")

    lines.append("")
    lines.append("<b>Table 2: WF結果 (PF&gt;1.5)</b>")
    for wf in wf_results:
        lines.append(f"{wf['label']}: PF&gt;1.0 {wf['n_above_1']}/{wf['n_total']} 集計PF={wf['agg_pf']:.2f}")
        lines.append(f"  {wf['verdict']}")

    lines.append("")
    lines.append("<b>推奨構成</b>")
    for bot_type in BOTS:
        off = next(r for r in all_rows if r['bot'] == bot_type and not r['pyramid'])
        on = next(r for r in all_rows if r['bot'] == bot_type and r['pyramid'])
        pf_off = off['pf'] if off['pf'] != float('inf') else 999
        pf_on = on['pf'] if on['pf'] != float('inf') else 999
        if pf_on > pf_off * 0.9 and on['return'] > off['return'] and abs(on['mdd']) < abs(off['mdd']) * 1.5:
            rec = "ON"
        else:
            rec = "OFF"
        # Check if WF passed
        wf_passed = any(wf for wf in wf_results if wf['bot'] == bot_type and wf['pyramid'] == (rec == "ON")
                        and wf['n_above_1'] == wf['n_total'] and wf['n_total'] > 0)
        wf_mark = "WF-GO" if wf_passed else ""
        lines.append(f"{BOT_LABELS[bot_type]}: pyramid={rec} {wf_mark}")

    lines.append("")
    lines.append("🧪 テスト: 確認中...")

    text = "\n".join(lines)

    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        await alert.send_message(text)
        print("\n📱 Telegram送信完了")
    except Exception as e:
        print(f"\n⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
