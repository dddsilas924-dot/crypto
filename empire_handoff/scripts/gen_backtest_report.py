"""
バックテスト結果HTMLレポート生成
Usage: python scripts/gen_backtest_report.py
"""
import csv, json, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

START = '2025-03-13'
END = '2026-03-13'
OUT_PATH = 'vault/backtest_results/backtest_report_20250313_20260313.html'

bots_order = [
    'levburn_sec_aggressive', 'levburn_sec', 'scalp',
    'levburn_sec_conservative', 'meanrevert', 'meanrevert_tight',
    'surge', 'weakshort'
]

bot_labels = {
    'levburn_sec': 'LevBurn-Sec Standard',
    'levburn_sec_aggressive': 'LevBurn-Sec Aggressive',
    'levburn_sec_conservative': 'LevBurn-Sec Conservative',
    'meanrevert_tight': 'MeanRevert-Tight',
    'meanrevert': 'MeanRevert',
    'scalp': 'Scalp',
    'surge': 'Surge',
    'weakshort': 'WeakShort',
}

bot_colors = {
    'levburn_sec': '#58a6ff',
    'levburn_sec_aggressive': '#f85149',
    'levburn_sec_conservative': '#3fb950',
    'meanrevert_tight': '#d29922',
    'meanrevert': '#db6d28',
    'scalp': '#bc8cff',
    'surge': '#39d353',
    'weakshort': '#f778ba',
}


def load_data():
    comparison = []
    with open('vault/backtest_results/bt_comparison_20250313_20260313.csv', 'r') as f:
        for row in csv.DictReader(f):
            comparison.append(row)
    comp_map = {r['bot']: r for r in comparison}

    all_trades = {}
    for bot in bots_order:
        path = f'vault/backtest_results/bt_{bot}_20250313_20260313.csv'
        trades = []
        try:
            with open(path, 'r') as f:
                for row in csv.DictReader(f):
                    for k in ('pnl_leveraged_pct', 'pnl_pct', 'holding_days',
                              'leverage', 'entry_price', 'exit_price', 'pnl_amount'):
                        row[k] = float(row.get(k, 0))
                    trades.append(row)
        except Exception:
            pass
        all_trades[bot] = trades

    # Build equity curves
    curves = {}
    for bot in bots_order:
        capital = 1_000_000
        curve = [{'date': START, 'capital': capital}]
        for t in sorted(all_trades[bot], key=lambda x: x.get('exit_date', '')):
            capital += t['pnl_amount']
            curve.append({'date': t.get('exit_date', ''), 'capital': round(capital)})
        curves[bot] = curve

    return comp_map, all_trades, curves


def calc_stats(trades):
    if not trades:
        return {}
    n = len(trades)
    wins = [t for t in trades if t['pnl_leveraged_pct'] > 0]
    losses = [t for t in trades if t['pnl_leveraged_pct'] <= 0]
    pnls = [t['pnl_leveraged_pct'] for t in trades]

    total_profit = sum(t['pnl_leveraged_pct'] for t in wins)
    total_loss = abs(sum(t['pnl_leveraged_pct'] for t in losses))

    monthly = defaultdict(list)
    for t in trades:
        m = t.get('entry_date', '')[:7]
        if m:
            monthly[m].append(t['pnl_leveraged_pct'])

    max_cw = max_cl = cw = cl = 0
    for p in pnls:
        if p > 0:
            cw += 1; cl = 0; max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0; max_cl = max(max_cl, cl)

    longs = [t for t in trades if t.get('side') == 'long']
    shorts = [t for t in trades if t.get('side') == 'short']

    exit_reasons = defaultdict(int)
    for t in trades:
        exit_reasons[t.get('exit_reason', 'unknown')] += 1

    sym_pnl = defaultdict(float)
    for t in trades:
        s = t.get('symbol', '').replace('/USDT:USDT', '')
        sym_pnl[s] += t['pnl_leveraged_pct']

    return {
        'total': n, 'wins': len(wins), 'losses': len(losses),
        'wr': len(wins) / n * 100,
        'avg_win': total_profit / len(wins) if wins else 0,
        'avg_loss': sum(t['pnl_leveraged_pct'] for t in losses) / len(losses) if losses else 0,
        'best': max(pnls), 'worst': min(pnls),
        'total_profit': total_profit, 'total_loss': total_loss,
        'pf': total_profit / total_loss if total_loss > 0 else 999,
        'avg_hold': sum(t['holding_days'] for t in trades) / n,
        'max_cw': max_cw, 'max_cl': max_cl,
        'longs': len(longs), 'shorts': len(shorts),
        'long_wr': sum(1 for t in longs if t['pnl_leveraged_pct'] > 0) / len(longs) * 100 if longs else 0,
        'short_wr': sum(1 for t in shorts if t['pnl_leveraged_pct'] > 0) / len(shorts) * 100 if shorts else 0,
        'exit_reasons': dict(exit_reasons),
        'monthly': {k: sum(v) for k, v in sorted(monthly.items())},
        'monthly_count': {k: len(v) for k, v in sorted(monthly.items())},
        'top_syms': sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:10],
        'worst_syms': sorted(sym_pnl.items(), key=lambda x: x[1])[:10],
    }


CSS = """:root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922; --orange: #db6d28;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, 'Segoe UI', sans-serif; padding: 24px; max-width: 1600px; margin: 0 auto; }
h1 { color: var(--accent); margin-bottom: 8px; }
h2 { color: var(--accent); font-size: 1.3em; margin: 30px 0 15px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
h3 { color: var(--text); font-size: 1.1em; margin: 20px 0 10px; }
.subtitle { color: var(--muted); margin-bottom: 24px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 16px; }
.grid { display: grid; gap: 16px; margin-bottom: 20px; }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-2 { grid-template-columns: repeat(2, 1fr); }
.metric-label { color: var(--muted); font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.metric-value { font-size: 1.6em; font-weight: bold; }
.green { color: var(--green); } .red { color: var(--red); } .yellow { color: var(--yellow); }
table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
th { color: var(--muted); font-size: 0.8em; text-transform: uppercase; text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--border); }
td { padding: 8px 10px; border-bottom: 1px solid var(--border); }
tr:hover { background: rgba(88,166,255,0.04); }
.rank { display: inline-block; width: 24px; height: 24px; border-radius: 50%; text-align: center; line-height: 24px; font-size: 0.8em; font-weight: bold; margin-right: 6px; }
.rank-1 { background: #ffd700; color: #000; } .rank-2 { background: #c0c0c0; color: #000; } .rank-3 { background: #cd7f32; color: #000; }
.bot-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; }
.chart-container { position: relative; height: 350px; margin: 15px 0; }
.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }
.tab-btn { padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; font-size: 0.85em; }
.tab-btn:hover { border-color: var(--accent); color: var(--text); }
.tab-btn.active { background: var(--accent); color: #000; border-color: var(--accent); }
.bot-section { display: none; } .bot-section.active { display: block; }
.exit-bar { display: flex; height: 28px; border-radius: 4px; overflow: hidden; margin: 8px 0; }
.exit-bar div { display: flex; align-items: center; justify-content: center; font-size: 0.75em; font-weight: bold; }
footer { text-align: center; color: var(--muted); padding: 30px; font-size: 0.85em; }
@media (max-width: 900px) { .grid-4 { grid-template-columns: repeat(2, 1fr); } }
"""


def build_html(comp_map, all_trades, curves):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    parts = []
    parts.append(f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report - Empire Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{CSS}</style></head><body>
<h1>Empire Monitor Backtest Report</h1>
<p class="subtitle">Period: {START} to {END} (1 Year) | Generated: {now}</p>''')

    # ── 1. Comparison Table ──
    parts.append('<h2>1. Performance Comparison</h2><div class="card"><table>')
    parts.append('<tr><th>#</th><th>Bot</th><th>Trades</th><th>Win Rate</th><th>PF</th>'
                 '<th>Total Return</th><th>MDD</th><th>Avg PnL</th><th>Sharpe</th>'
                 '<th>Avg Hold</th><th>Final Capital</th></tr>')

    for i, bot in enumerate(bots_order):
        c = comp_map.get(bot, {})
        tn = int(c.get('trades', 0))
        if tn == 0:
            continue
        ret = float(c.get('total_return_pct', 0))
        wr = float(c.get('win_rate', 0))
        sharpe = float(c.get('sharpe_ratio', 0))
        mdd = float(c.get('max_drawdown_pct', 0))
        rank_cls = f' rank-{i+1}' if i < 3 else ''
        ret_cls = 'green' if ret > 0 else 'red'
        wr_cls = 'green' if wr >= 60 else ('yellow' if wr >= 50 else 'red')
        sh_cls = 'green' if sharpe >= 5 else ('yellow' if sharpe >= 2 else 'red')
        color = bot_colors.get(bot, '#8b949e')

        parts.append(f'<tr><td><span class="rank{rank_cls}">{i+1}</span></td>'
                      f'<td><span class="bot-badge" style="background:{color};color:#000">'
                      f'{bot_labels.get(bot, bot)}</span></td>'
                      f'<td>{tn}</td><td class="{wr_cls}">{wr:.1f}%</td>'
                      f'<td>{float(c.get("profit_factor",0)):.2f}</td>'
                      f'<td class="{ret_cls}" style="font-weight:bold">{ret:+.1f}%</td>'
                      f'<td class="red">{mdd:.1f}%</td>'
                      f'<td>{float(c.get("avg_pnl_pct",0)):+.2f}%</td>'
                      f'<td class="{sh_cls}">{sharpe:.2f}</td>'
                      f'<td>{float(c.get("avg_hold_days",0)):.1f}d</td>'
                      f'<td>&yen;{float(c.get("final_capital",0)):,.0f}</td></tr>')

    parts.append('</table></div>')

    # ── 2. Equity Curve ──
    parts.append('<h2>2. Equity Curves</h2>'
                 '<div class="card"><div class="chart-container">'
                 '<canvas id="equityChart"></canvas></div></div>')

    datasets = []
    for bot in bots_order:
        curve = curves.get(bot, [])
        if not curve:
            continue
        datasets.append({
            'label': bot_labels.get(bot, bot),
            'data': [{'x': p['date'], 'y': p['capital']} for p in curve],
            'borderColor': bot_colors.get(bot, '#8b949e'),
            'borderWidth': 2, 'pointRadius': 0, 'fill': False, 'tension': 0.1,
        })

    parts.append(f'''<script>
new Chart(document.getElementById('equityChart'), {{
    type: 'line',
    data: {{ datasets: {json.dumps(datasets)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#e6edf3', font: {{ size: 11 }} }} }} }},
        scales: {{
            x: {{ type: 'category', ticks: {{ color: '#8b949e', maxTicksLimit: 12 }}, grid: {{ color: '#30363d' }} }},
            y: {{ ticks: {{ color: '#8b949e', callback: function(v) {{ return String.fromCharCode(165) + v.toLocaleString(); }} }}, grid: {{ color: '#30363d' }} }}
        }}
    }}
}});
</script>''')

    # ── 3. Risk-Return Scatter ──
    parts.append('<h2>3. Risk-Return Map</h2>'
                 '<div class="card"><div class="chart-container">'
                 '<canvas id="rrChart"></canvas></div></div>')

    sc_ds = []
    for bot in bots_order:
        c = comp_map.get(bot, {})
        if int(c.get('trades', 0)) == 0:
            continue
        sc_ds.append({
            'label': bot_labels.get(bot, bot),
            'data': [{'x': float(c.get('max_drawdown_pct', 0)),
                       'y': float(c.get('total_return_pct', 0))}],
            'backgroundColor': bot_colors.get(bot, '#8b949e'),
            'borderColor': bot_colors.get(bot, '#8b949e'),
            'pointRadius': 12, 'pointHoverRadius': 16,
        })

    parts.append(f'''<script>
new Chart(document.getElementById('rrChart'), {{
    type: 'scatter',
    data: {{ datasets: {json.dumps(sc_ds)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }},
            tooltip: {{ callbacks: {{ label: function(ctx) {{
                return ctx.dataset.label + ': MDD ' + ctx.parsed.x.toFixed(1) + '%, Ret ' + ctx.parsed.y.toFixed(0) + '%';
            }} }} }}
        }},
        scales: {{
            x: {{ title: {{ display: true, text: 'Max Drawdown %', color: '#8b949e' }}, ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }}, reverse: true }},
            y: {{ title: {{ display: true, text: 'Total Return %', color: '#8b949e' }}, ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }}
        }}
    }}
}});
</script>''')

    # ── 4. Bot Detail Tabs ──
    parts.append('<h2>4. Bot Details</h2><div class="tab-bar">')
    for i, bot in enumerate(bots_order):
        active = ' active' if i == 0 else ''
        color = bot_colors.get(bot, '#8b949e')
        parts.append(f'<button class="tab-btn{active}" onclick="showBot(\'{bot}\')" '
                      f'style="border-color:{color}">{bot_labels.get(bot, bot)}</button>')
    parts.append('</div>')

    for idx, bot in enumerate(bots_order):
        trades = all_trades[bot]
        s = calc_stats(trades)
        c = comp_map.get(bot, {})
        active = ' active' if idx == 0 else ''
        color = bot_colors.get(bot, '#8b949e')

        ret = float(c.get('total_return_pct', 0))
        ret_cls = 'green' if ret >= 0 else 'red'
        sharpe = float(c.get('sharpe_ratio', 0))
        mdd = float(c.get('max_drawdown_pct', 0))

        parts.append(f'<div class="bot-section{active}" id="section-{bot}">')

        # KPI cards
        parts.append(f'''<div class="grid grid-4">
<div class="card"><div class="metric-label">Total Return</div><div class="metric-value {ret_cls}">{ret:+.1f}%</div></div>
<div class="card"><div class="metric-label">Win Rate</div><div class="metric-value">{s["wr"]:.1f}%</div><div style="color:var(--muted);font-size:0.8em">{s["wins"]}W / {s["losses"]}L</div></div>
<div class="card"><div class="metric-label">Profit Factor</div><div class="metric-value">{s["pf"]:.2f}</div></div>
<div class="card"><div class="metric-label">Sharpe</div><div class="metric-value">{sharpe:.2f}</div></div>
</div><div class="grid grid-4">
<div class="card"><div class="metric-label">MDD</div><div class="metric-value red">{mdd:.1f}%</div></div>
<div class="card"><div class="metric-label">Avg Win / Loss</div><div class="metric-value" style="font-size:1.1em"><span class="green">{s["avg_win"]:+.2f}%</span> / <span class="red">{s["avg_loss"]:+.2f}%</span></div></div>
<div class="card"><div class="metric-label">Best / Worst</div><div class="metric-value" style="font-size:1.1em"><span class="green">{s["best"]:+.1f}%</span> / <span class="red">{s["worst"]:+.1f}%</span></div></div>
<div class="card"><div class="metric-label">Consec W/L</div><div class="metric-value" style="font-size:1.1em">{s["max_cw"]}W / {s["max_cl"]}L</div></div>
</div>''')

        # Side + Exit reasons
        parts.append('<div class="grid grid-2">')
        parts.append(f'''<div class="card"><h3>Direction</h3><table>
<tr><th>Side</th><th>Trades</th><th>Win Rate</th></tr>
<tr><td class="green">LONG</td><td>{s["longs"]}</td><td>{s["long_wr"]:.1f}%</td></tr>
<tr><td class="red">SHORT</td><td>{s["shorts"]}</td><td>{s["short_wr"]:.1f}%</td></tr>
</table></div>''')

        exit_r = s.get('exit_reasons', {})
        total_ex = sum(exit_r.values()) or 1
        exit_colors_map = {'TP': 'var(--green)', 'SL': 'var(--red)',
                           'timeout': 'var(--yellow)', 'force_close': 'var(--orange)'}
        bar_html = ''
        for reason, cnt in sorted(exit_r.items(), key=lambda x: -x[1]):
            pct = cnt / total_ex * 100
            col = exit_colors_map.get(reason, 'var(--muted)')
            bar_html += f'<div style="width:{pct:.0f}%;background:{col}">{reason} {cnt}</div>'

        parts.append(f'<div class="card"><h3>Exit Reasons</h3><div class="exit-bar">{bar_html}</div><table>')
        parts.append('<tr><th>Reason</th><th>Count</th><th>%</th></tr>')
        for reason, cnt in sorted(exit_r.items(), key=lambda x: -x[1]):
            parts.append(f'<tr><td>{reason}</td><td>{cnt}</td><td>{cnt/total_ex*100:.1f}%</td></tr>')
        parts.append('</table></div></div>')

        # Monthly PnL
        monthly = s.get('monthly', {})
        mc = s.get('monthly_count', {})
        if monthly:
            parts.append('<div class="card"><h3>Monthly PnL</h3><table>')
            parts.append('<tr><th>Month</th><th>Trades</th><th>PnL</th><th>Cumulative</th></tr>')
            cum = 0
            for m in sorted(monthly.keys()):
                p = monthly[m]
                cum += p
                cls = 'green' if p >= 0 else 'red'
                parts.append(f'<tr><td>{m}</td><td>{mc.get(m,0)}</td>'
                              f'<td class="{cls}">{p:+.1f}%</td><td>{cum:+.1f}%</td></tr>')
            parts.append('</table></div>')

        # Top / Worst symbols
        parts.append('<div class="grid grid-2">')
        parts.append('<div class="card"><h3>Top 10 Symbols</h3><table><tr><th>Symbol</th><th>PnL</th></tr>')
        for sym, pnl in s.get('top_syms', []):
            cls = 'green' if pnl >= 0 else 'red'
            parts.append(f'<tr><td>{sym}</td><td class="{cls}">{pnl:+.1f}%</td></tr>')
        parts.append('</table></div>')

        parts.append('<div class="card"><h3>Worst 10 Symbols</h3><table><tr><th>Symbol</th><th>PnL</th></tr>')
        for sym, pnl in s.get('worst_syms', []):
            cls = 'green' if pnl >= 0 else 'red'
            parts.append(f'<tr><td>{sym}</td><td class="{cls}">{pnl:+.1f}%</td></tr>')
        parts.append('</table></div></div>')

        # Trade Log
        parts.append('<div class="card"><h3>Trade Log (Recent 30)</h3>')
        parts.append('<div style="max-height:400px;overflow-y:auto"><table>')
        parts.append('<tr><th>#</th><th>Symbol</th><th>Side</th><th>Lev</th>'
                     '<th>Entry</th><th>Exit</th><th>Reason</th><th>Hold</th>'
                     '<th>PnL(raw)</th><th>PnL(lev)</th></tr>')
        start_idx = max(0, len(trades) - 30)
        for i, t in enumerate(trades[start_idx:], start_idx + 1):
            pnl = t['pnl_leveraged_pct']
            cls = 'green' if pnl > 0 else 'red'
            sc = 'green' if t['side'] == 'long' else 'red'
            sym = t.get('symbol', '').replace('/USDT:USDT', '')
            parts.append(f'<tr><td>{i}</td><td>{sym}</td><td class="{sc}">{t["side"].upper()}</td>'
                          f'<td>{t["leverage"]:.0f}x</td><td>{t.get("entry_date","")}</td>'
                          f'<td>{t.get("exit_date","")}</td><td>{t.get("exit_reason","")}</td>'
                          f'<td>{t["holding_days"]:.0f}d</td><td>{t["pnl_pct"]:+.2f}%</td>'
                          f'<td class="{cls}" style="font-weight:bold">{pnl:+.2f}%</td></tr>')
        parts.append('</table></div></div>')

        parts.append('</div>')  # bot-section

    # ── 5. Key Insights ──
    parts.append('''<h2>5. Key Insights</h2><div class="card">
<h3>LevBurn-Sec Dominance</h3>
<ul style="color:var(--muted);line-height:1.8;padding-left:20px">
<li><strong style="color:var(--text)">Conservative</strong> &mdash; Best risk-adjusted: Sharpe 13.36, MDD -2.2%, WR 90.3%. Capital preservation.</li>
<li><strong style="color:var(--text)">Standard</strong> &mdash; Best balance: Sharpe 10.49, PF 8.54, +1,080% return.</li>
<li><strong style="color:var(--text)">Aggressive</strong> &mdash; Highest return +2,643% but MDD -11.6%. High-conviction only.</li>
</ul>
<h3 style="margin-top:16px">Traditional Bots</h3>
<ul style="color:var(--muted);line-height:1.8;padding-left:20px">
<li><strong style="color:var(--text)">Scalp</strong> &mdash; Most active (300T), WR 43.7%, MDD -16.5%. Needs WR improvement.</li>
<li><strong style="color:var(--text)">MeanRevert</strong> &mdash; Steady +90%. Good diversifier alongside LevBurn-Sec.</li>
<li><strong style="color:var(--text)">Surge</strong> &mdash; Low freq (47T), high precision WR 63.8%. Wait-and-strike.</li>
<li><strong style="color:var(--text)">WeakShort</strong> &mdash; Limited window (F&amp;G 50-75). +13% in 34 trades.</li>
</ul>
<h3 style="margin-top:16px">Caveat</h3>
<p style="color:var(--red)">LevBurn-Sec uses daily FR proxy in backtest. Real-time 1s trigger logic is NOT simulated. Actual live performance will differ significantly.</p>
</div>''')

    # ── Tab JS ──
    parts.append('''<script>
function showBot(bot) {
    document.querySelectorAll('.bot-section').forEach(function(s) { s.classList.remove('active'); });
    document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById('section-' + bot).classList.add('active');
    event.target.classList.add('active');
}
</script>''')

    parts.append(f'<footer>Empire Monitor Backtest Report | {now}</footer>')
    parts.append('</body></html>')

    return '\n'.join(parts)


def main():
    print("Loading data...")
    comp_map, all_trades, curves = load_data()

    print("Generating HTML...")
    html = build_html(comp_map, all_trades, curves)

    Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Report saved: {OUT_PATH}")
    print(f"Size: {len(html):,} bytes")


if __name__ == '__main__':
    main()
