"""Bot-LevBurn バリエーション別バックテスト (5 variants × 3 leverages)

使い方:
  python scripts/run_levburn_backtest.py
"""
import asyncio
import sys
import yaml
import csv
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# 期間
START = '2024-03-01'
END = '2026-03-01'

LEVERAGES = [3, 5, 10]

VARIANTS = {
    "base": {
        "label": "LB-Base",
        "fr_threshold": 0.3,
        "vol_threshold": 3.0,
        "take_profit_pct": 5.0,
        "stop_loss_pct": 2.5,
        "max_holding_days": 2,
        "position_size_pct": 3,
        "extra_conditions": None,
    },
    "tight": {
        "label": "LB-Tight",
        "fr_threshold": 0.5,
        "vol_threshold": 4.0,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 1.5,
        "max_holding_days": 1,
        "position_size_pct": 3,
        "extra_conditions": "rsi_extreme",
    },
    "aggressive": {
        "label": "LB-Aggro",
        "fr_threshold": 0.5,
        "vol_threshold": 3.0,
        "take_profit_pct": 8.0,
        "stop_loss_pct": 3.0,
        "max_holding_days": 3,
        "position_size_pct": 2,
        "extra_conditions": "extreme_only",
    },
    "scalp": {
        "label": "LB-Scalp",
        "fr_threshold": 0.15,
        "vol_threshold": 2.0,
        "take_profit_pct": 2.0,
        "stop_loss_pct": 1.0,
        "max_holding_days": 1,
        "position_size_pct": 3,
        "extra_conditions": None,
    },
    "fear_combo": {
        "label": "LB-Fear",
        "fr_threshold": 0.3,
        "vol_threshold": 3.0,
        "take_profit_pct": 6.0,
        "stop_loss_pct": 3.0,
        "max_holding_days": 2,
        "position_size_pct": 5,
        "extra_conditions": "fear_filter",
    },
}


def run_single(variant_name: str, variant_cfg: dict, leverage: int,
               config: dict, db: HistoricalDB) -> dict:
    """単一バックテスト実行"""
    bot_config = variant_cfg.copy()
    bot_config['leverage'] = leverage
    bot_config['max_position_pct'] = 50

    engine = BacktestEngine(f'levburn_{variant_name}', bot_config, db)
    results = engine.run(START, END)

    min_cap = results.get('min_capital', 1_000_000)
    bankrupt = min_cap < 100_000

    return {
        'variant': variant_name,
        'label': variant_cfg.get('label', variant_name),
        'leverage': leverage,
        'trades': results.get('total_trades', 0),
        'wr': results.get('win_rate', 0),
        'pf': min(results.get('profit_factor', 0), 999),
        'return': results.get('total_return_pct', 0),
        'mdd': results.get('max_drawdown_pct', 0),
        'sharpe': results.get('sharpe_ratio', 0),
        'avg_hold': results.get('avg_holding_days', 0),
        'min_cap': min_cap,
        'final_cap': results.get('final_capital', 1_000_000),
        'bankrupt': bankrupt,
        'equity_curve': results.get('equity_curve', []),
        'trades_list': engine.trades,
    }


def yearly_breakdown(trades_list: list) -> dict:
    yearly = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0, 'loss': 0, 'trades': 0})
    for t in trades_list:
        year = t.get('entry_date', '')[:4]
        if not year:
            continue
        pnl = t.get('pnl_leveraged_pct', 0)
        yearly[year]['trades'] += 1
        if pnl > 0:
            yearly[year]['wins'] += 1
            yearly[year]['profit'] += pnl
        else:
            yearly[year]['losses'] += 1
            yearly[year]['loss'] += abs(pnl)
    return dict(yearly)


def count_long_short(trades_list: list) -> tuple:
    long_t = sum(1 for t in trades_list if t.get('side') == 'long')
    short_t = sum(1 for t in trades_list if t.get('side') == 'short')
    return long_t, short_t


def generate_html_report(all_results: list, wf_results: list, comparison: list = None) -> str:
    """HTMLレポート生成"""
    # Table 1: 全バリエーション比較（レバ5x固定）
    lev5 = [r for r in all_results if r['leverage'] == 5]

    t1_rows = ""
    for r in lev5:
        long_t, short_t = count_long_short(r['trades_list'])
        ls = f"{long_t}L/{short_t}S"
        pf_color = '#4caf50' if r['pf'] >= 1.3 else ('#ff9800' if r['pf'] >= 1.0 else '#f44336')
        t1_rows += f"""<tr>
            <td>{r['label']}</td><td>{r['trades']}</td>
            <td>{r['wr']:.1f}%</td><td style="color:{pf_color}">{r['pf']:.2f}</td>
            <td>{r['return']:+.1f}%</td><td>{r['mdd']:.1f}%</td>
            <td>{r['sharpe']:.2f}</td><td>{r['avg_hold']:.1f}d</td><td>{ls}</td>
        </tr>"""

    # Table 2: レバ別比較
    t2_rows = ""
    for vname, vcfg in VARIANTS.items():
        for lev in LEVERAGES:
            r = next((x for x in all_results if x['variant'] == vname and x['leverage'] == lev), None)
            if not r:
                continue
            bank = ' 💀' if r['bankrupt'] else ''
            t2_rows += f"""<tr>
                <td>{r['label']}</td><td>{lev}x</td>
                <td>{r['return']:+.1f}%</td><td>{r['mdd']:.1f}%</td>
                <td>{r['pf']:.2f}</td><td>{bank}</td>
            </tr>"""

    # Table 3: 年度別（base, lev=5）
    base5 = next((r for r in all_results if r['variant'] == 'base' and r['leverage'] == 5), None)
    t3_rows = ""
    if base5 and base5['trades_list']:
        yearly = yearly_breakdown(base5['trades_list'])
        for year in sorted(yearly.keys()):
            y = yearly[year]
            wr = y['wins'] / y['trades'] * 100 if y['trades'] > 0 else 0
            pf = y['profit'] / y['loss'] if y['loss'] > 0 else 999
            ret = y['profit'] - y['loss']
            t3_rows += f"<tr><td>{year}</td><td>{y['trades']}</td><td>{wr:.1f}%</td><td>{pf:.2f}</td><td>{ret:+.1f}%</td></tr>"

    # Table 4: WF検証
    t4_rows = ""
    for wf in wf_results:
        go_ng = '✅ GO' if wf['oos_pf'] >= 1.0 and wf['is_pf'] >= 1.0 else '❌ NG'
        t4_rows += f"""<tr>
            <td>{wf['label']}</td><td>{wf['window']}</td>
            <td>{wf['is_pf']:.2f}</td><td>{wf['oos_pf']:.2f}</td><td>{go_ng}</td>
        </tr>"""

    # Table 5: 推奨構成
    t5_rows = ""
    for vname, vcfg in VARIANTS.items():
        best_lev = 5
        best_r = next((x for x in all_results if x['variant'] == vname and x['leverage'] == 5), None)
        if not best_r:
            continue
        reason = ""
        if best_r['pf'] >= 1.5:
            reason = "PF良好、安定稼働可"
        elif best_r['pf'] >= 1.3:
            reason = "PF合格ライン"
        elif best_r['pf'] >= 1.0:
            reason = "要注意、微利"
        else:
            reason = "不採用（PF不足）"
        alloc = "5%" if best_r['pf'] >= 1.3 else ("3%" if best_r['pf'] >= 1.0 else "0%")
        t5_rows += f"<tr><td>{vcfg['label']}</td><td>{best_lev}x</td><td>{alloc}</td><td>{reason}</td></tr>"

    # Comparison table
    comparison_html = ""
    if comparison:
        comp_rows = ""
        for c in comparison:
            pf_color = '#4caf50' if c['real_pf'] >= c['proxy_pf'] else '#f44336'
            comp_rows += f"""<tr>
                <td>{c['variant']}</td>
                <td>{c['proxy_pf']:.2f}</td><td style="color:{pf_color}">{c['real_pf']:.2f}</td>
                <td>{c['proxy_ret']:+.1f}%</td><td>{c['real_ret']:+.1f}%</td>
                <td>{c['wr_diff']:+.1f}%</td><td>{c['trades_diff']:+d}</td>
            </tr>"""
        comparison_html = f"""<h2>Table 6: 疑似FR vs 実FR 比較 (レバ5x)</h2>
<table><tr><th>Variant</th><th>PF(疑似)</th><th>PF(実FR)</th><th>Return(疑似)</th><th>Return(実FR)</th><th>WR差</th><th>T差</th></tr>
{comp_rows}</table>"""

    # Best results for summary
    best_pf_r = max(all_results, key=lambda x: x['pf'] if x['trades'] > 0 else 0)
    best_ret_r = max(all_results, key=lambda x: x['return'])
    wf_pass = sum(1 for w in wf_results if w['oos_pf'] >= 1.0 and w['is_pf'] >= 1.0)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Bot-LevBurn Backtest Report</title>
<style>
body {{ background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', monospace; margin: 20px; }}
h1 {{ color: #ff6b35; border-bottom: 2px solid #30363d; padding-bottom: 10px; }}
h2 {{ color: #58a6ff; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th {{ background: #161b22; color: #58a6ff; padding: 10px; text-align: left; border: 1px solid #30363d; }}
td {{ padding: 8px 10px; border: 1px solid #30363d; }}
tr:nth-child(even) {{ background: #161b22; }}
.summary {{ background: #161b22; padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #30363d; }}
.warn {{ color: #ff9800; font-size: 0.9em; margin: 10px 0; }}
</style></head><body>
<h1>🔥 Bot-LevBurn バックテストレポート</h1>
<div class="summary">
    <b>期間:</b> {START} ~ {END} (2年間)<br>
    <b>バリエーション:</b> {len(VARIANTS)}種 × レバ{len(LEVERAGES)}段階 = {len(VARIANTS)*len(LEVERAGES)}パターン<br>
    <b>コスト:</b> 0.22%/RT (taker 0.06% + slippage 0.05% × 2)<br>
    <b>最高PF:</b> {best_pf_r['label']} {best_pf_r['leverage']}x PF={best_pf_r['pf']:.2f}<br>
    <b>最高Return:</b> {best_ret_r['label']} {best_ret_r['leverage']}x {best_ret_r['return']:+.1f}%<br>
    <b>WF通過:</b> {wf_pass}/{len(wf_results)}<br>
</div>
<p class="warn">実FRデータ優先 + proxyフォールバック。
実FRが存在する日は取引所APIの値を使用、存在しない日はOHLCVベースの疑似FR推定を使用。</p>

<h2>Table 1: 全バリエーション比較 (レバ5x)</h2>
<table><tr><th>Variant</th><th>Trades</th><th>WR</th><th>PF</th><th>Return</th><th>MDD</th><th>Sharpe</th><th>AvgHold</th><th>L/S</th></tr>
{t1_rows}</table>

<h2>Table 2: レバ別比較</h2>
<table><tr><th>Variant</th><th>Lev</th><th>Return</th><th>MDD</th><th>PF</th><th>破産</th></tr>
{t2_rows}</table>

<h2>Table 3: 年度別成績 (Base, 5x)</h2>
<table><tr><th>Year</th><th>Trades</th><th>WR</th><th>PF</th><th>Return</th></tr>
{t3_rows}</table>

<h2>Table 4: WF検証結果</h2>
<table><tr><th>Variant</th><th>Window</th><th>IS PF</th><th>OOS PF</th><th>GO/NG</th></tr>
{t4_rows}</table>

<h2>Table 5: 推奨構成</h2>
<table><tr><th>Variant</th><th>推奨レバ</th><th>配分</th><th>理由</th></tr>
{t5_rows}</table>

{comparison_html}

<h2>FR推定について</h2>
<ul>
<li><b>実FR</b>: MEXC APIから8h毎のFR履歴を取得。DBに存在する日はこの値を使用。</li>
<li><b>疑似FR</b>: 実FRが無い日のフォールバック。3日連続陽線/陰線 + 出来高急増 + ボラティリティ急増で推定。</li>
<li><b>OI代替</b>: 出来高急増で投機過熱を代替。実際のOIデータがないため、投機度の正確な判定は不可。</li>
</ul>

<p style="color:#8b949e; font-size:0.8em;">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>"""
    return html


def run_walkforward(variant_name: str, variant_cfg: dict, leverage: int,
                    config: dict, db: HistoricalDB) -> list:
    """WF検証: IS 6M / OOS 3M × 4窓"""
    windows = [
        ('2024-03-01', '2024-09-01', '2024-09-01', '2024-12-01'),
        ('2024-06-01', '2024-12-01', '2024-12-01', '2025-03-01'),
        ('2024-09-01', '2025-03-01', '2025-03-01', '2025-06-01'),
        ('2024-12-01', '2025-06-01', '2025-06-01', '2025-09-01'),
    ]
    results = []
    for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
        # IS
        bot_config = variant_cfg.copy()
        bot_config['leverage'] = leverage
        bot_config['max_position_pct'] = 50
        engine_is = BacktestEngine(f'levburn_{variant_name}', bot_config, db)
        is_res = engine_is.run(is_start, is_end)
        # OOS
        engine_oos = BacktestEngine(f'levburn_{variant_name}', bot_config, db)
        oos_res = engine_oos.run(oos_start, oos_end)

        results.append({
            'label': variant_cfg.get('label', variant_name),
            'window': f"W{i+1} IS:{is_start[:7]}~{is_end[:7]} OOS:{oos_start[:7]}~{oos_end[:7]}",
            'is_pf': min(is_res.get('profit_factor', 0), 999),
            'oos_pf': min(oos_res.get('profit_factor', 0), 999),
            'is_trades': is_res.get('total_trades', 0),
            'oos_trades': oos_res.get('total_trades', 0),
        })
    return results


def load_proxy_baseline() -> dict:
    """前回疑似FRバックテスト結果を読み込み（比較用）"""
    proxy_csv = 'vault/backtest_results/levburn_backtest_proxy_fr.csv'
    baseline = {}
    try:
        with open(proxy_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row['variant']}_{row['leverage']}"
                baseline[key] = {
                    'pf': float(row['pf']),
                    'return': float(row['return']),
                    'wr': float(row['wr']),
                    'mdd': float(row['mdd']),
                    'trades': int(row['trades']),
                }
    except FileNotFoundError:
        pass
    return baseline


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()

    # FR件数確認
    conn = db._get_conn()
    fr_count = conn.execute("SELECT COUNT(*) FROM funding_rate_history").fetchone()[0]
    fr_symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM funding_rate_history").fetchone()[0]
    conn.close()
    avg_fr = fr_count / fr_symbols if fr_symbols > 0 else 0

    print("=" * 70)
    print("  Bot-LevBurn バックテスト: 5 variants × 3 leverages = 15 runs")
    print(f"  期間: {START} ~ {END}")
    print(f"  FR: 実データ {fr_count}件 ({fr_symbols}銘柄, 平均{avg_fr:.0f}件) + proxy fallback")
    print("=" * 70)

    all_results = []

    # ===== Phase 1: 全バリエーション × 全レバ =====
    for vname, vcfg in VARIANTS.items():
        for lev in LEVERAGES:
            print(f"  {vcfg['label']:12s} lev={lev:2d}x ... ", end='', flush=True)
            r = run_single(vname, vcfg, lev, config, db)
            all_results.append(r)
            bank_mark = " 💀" if r['bankrupt'] else ""
            print(f"T={r['trades']:>4d} WR={r['wr']:>5.1f}% PF={r['pf']:>6.2f} Ret={r['return']:>+9.1f}% MDD={r['mdd']:>6.1f}%{bank_mark}")

    # ===== Table 1: レバ5x固定 =====
    print(f"\n{'='*70}")
    print("  Table 1: 全バリエーション比較 (レバ5x)")
    print(f"{'='*70}")
    print(f"  {'Variant':<12s} {'T':>5s} {'WR':>6s} {'PF':>7s} {'Return':>9s} {'MDD':>7s} {'Sharpe':>7s} {'Hold':>6s} {'L/S':>10s}")
    print(f"  {'-'*70}")
    for r in [x for x in all_results if x['leverage'] == 5]:
        lt, st = count_long_short(r['trades_list'])
        print(f"  {r['label']:<12s} {r['trades']:>5d} {r['wr']:>5.1f}% {r['pf']:>7.2f} {r['return']:>+8.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['avg_hold']:>5.1f}d {lt}L/{st}S")

    # ===== Table 2: レバ別 =====
    print(f"\n{'='*70}")
    print("  Table 2: レバ別比較")
    print(f"{'='*70}")
    print(f"  {'Variant':<12s} {'Lev':>4s} {'Return':>9s} {'MDD':>7s} {'PF':>7s} {'破産':>5s}")
    print(f"  {'-'*50}")
    for vname, vcfg in VARIANTS.items():
        for lev in LEVERAGES:
            r = next((x for x in all_results if x['variant'] == vname and x['leverage'] == lev), None)
            if r:
                bank = "💀" if r['bankrupt'] else ""
                print(f"  {r['label']:<12s} {lev:>3d}x {r['return']:>+8.1f}% {r['mdd']:>6.1f}% {r['pf']:>7.2f} {bank}")

    # ===== WF検証（PF >= 1.3 のバリエーションのみ）=====
    print(f"\n{'='*70}")
    print("  Walk-Forward 検証 (IS 6M / OOS 3M × 4窓)")
    print(f"{'='*70}")

    wf_results = []
    for vname, vcfg in VARIANTS.items():
        r5 = next((x for x in all_results if x['variant'] == vname and x['leverage'] == 5), None)
        if r5 and r5['pf'] >= 1.0 and r5['trades'] > 0:
            print(f"  {vcfg['label']} WF検証中...", flush=True)
            wf = run_walkforward(vname, vcfg, 5, config, db)
            wf_results.extend(wf)
            for w in wf:
                go = "✅" if w['oos_pf'] >= 1.0 and w['is_pf'] >= 1.0 else "❌"
                print(f"    {w['window']} IS_PF={w['is_pf']:.2f} OOS_PF={w['oos_pf']:.2f} {go}")

    # ===== CSV保存 =====
    outdir = 'vault/backtest_results'
    os.makedirs(outdir, exist_ok=True)
    csv_path = f"{outdir}/levburn_backtest_summary.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['variant', 'leverage', 'trades', 'wr', 'pf', 'return', 'mdd', 'sharpe', 'avg_hold', 'bankrupt'])
        for r in all_results:
            writer.writerow([r['variant'], r['leverage'], r['trades'], round(r['wr'], 1),
                             round(r['pf'], 2), round(r['return'], 1), round(r['mdd'], 1),
                             round(r['sharpe'], 2), round(r['avg_hold'], 1), r['bankrupt']])
    print(f"\n  CSV: {csv_path}")

    # ===== 疑似FR vs 実FR 比較テーブル =====
    baseline = load_proxy_baseline()
    comparison_rows = []
    if baseline:
        print(f"\n{'='*70}")
        print("  疑似FR vs 実FR 比較 (レバ5x)")
        print(f"{'='*70}")
        print(f"  {'Variant':<12s} {'PF(疑似)':>9s} {'PF(実FR)':>9s} {'Ret(疑似)':>10s} {'Ret(実FR)':>10s} {'WR差':>7s} {'T差':>5s}")
        print(f"  {'-'*65}")
        for vname, vcfg in VARIANTS.items():
            key = f"{vname}_5"
            proxy = baseline.get(key)
            real = next((x for x in all_results if x['variant'] == vname and x['leverage'] == 5), None)
            if proxy and real:
                wr_diff = real['wr'] - proxy['wr']
                t_diff = real['trades'] - proxy['trades']
                pf_arrow = ">>>" if real['pf'] > proxy['pf'] + 0.1 else ("<<<" if real['pf'] < proxy['pf'] - 0.1 else " = ")
                print(f"  {vcfg['label']:<12s} {proxy['pf']:>8.2f}  {real['pf']:>8.2f} {pf_arrow} {proxy['return']:>+8.1f}%  {real['return']:>+8.1f}% {wr_diff:>+6.1f}% {t_diff:>+4d}")
                comparison_rows.append({
                    'variant': vcfg['label'],
                    'proxy_pf': proxy['pf'], 'real_pf': real['pf'],
                    'proxy_ret': proxy['return'], 'real_ret': real['return'],
                    'wr_diff': wr_diff, 'trades_diff': t_diff,
                })
    else:
        print("\n  (疑似FRベースラインなし - 初回実行)")

    # ===== HTML レポート =====
    html_path = 'vault/docs/levburn_backtest_report.html'
    os.makedirs('vault/docs', exist_ok=True)
    html = generate_html_report(all_results, wf_results, comparison_rows)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  HTML: {html_path}")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n  処理時間: {elapsed:.1f}秒")

    # ===== サマリー =====
    best_pf = max(all_results, key=lambda x: x['pf'] if x['trades'] > 0 else 0)
    best_ret = max(all_results, key=lambda x: x['return'])
    wf_pass = sum(1 for w in wf_results if w['oos_pf'] >= 1.0 and w['is_pf'] >= 1.0)
    print(f"\n  Bot-LevBurn バックテスト完了")
    print(f"  期間: {START}~{END}")
    print(f"  FR: 実データ{fr_count}件 + proxy fallback")
    print(f"  バリエーション: {len(VARIANTS)}種 x レバ{len(LEVERAGES)}段階 = {len(all_results)}パターン")
    print(f"  最高PF: {best_pf['label']} {best_pf['leverage']}x PF={best_pf['pf']:.2f}")
    print(f"  最高Return: {best_ret['label']} {best_ret['leverage']}x {best_ret['return']:+.1f}%")
    print(f"  WF通過: {wf_pass}/{len(wf_results)}")

    # Telegram通知
    try:
        import asyncio as _aio
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        comp_text = ""
        if comparison_rows:
            for c in comparison_rows:
                comp_text += f"\n  {c['variant']}: PF {c['proxy_pf']:.2f} -> {c['real_pf']:.2f}"
        text = (
            f"<b>LevBurn 実FRバックテスト完了</b>\n"
            f"FR: {fr_count}件 / {fr_symbols}銘柄 / 平均{avg_fr:.0f}件\n"
            f"カバー率: {avg_fr/730*100:.1f}%\n"
            f"最高PF: {best_pf['label']} {best_pf['leverage']}x PF={best_pf['pf']:.2f}\n"
            f"WF: {wf_pass}/{len(wf_results)}"
            f"{comp_text}"
        )
        _aio.get_event_loop().run_until_complete(alert.send_message(text))
    except Exception:
        pass

    return all_results


if __name__ == '__main__':
    asyncio.run(main())
