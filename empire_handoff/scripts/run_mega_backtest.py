"""
メガバックテスト — 全Bot × レバレッジ可変 × 6年データ
+ レジーム別分析 + ハイブリッド最強Bot生成 + HTML包括レポート

想定実行時間: 約4〜6時間
Usage: python scripts/run_mega_backtest.py
"""
import asyncio
import sys
import yaml
import csv
import json
import time
import traceback
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine
from src.backtest.hf_backtest_engine import HFBacktestEngine

# ══════════════════════════════════════════════════════════════
# 設定
# ══════════════════════════════════════════════════════════════

# 期間
DAILY_START = '2020-03-14'
DAILY_END   = '2026-03-14'
HF_START    = '2025-01-01'
HF_END      = '2026-03-14'

INITIAL_CAPITAL = 1_000_000
OUT_DIR = Path('vault/backtest_results/mega')

# ── 日足Bot一覧 ──
DAILY_BOTS = [
    'alpha', 'surge', 'momentum', 'rebound', 'stability', 'trend',
    'cascade', 'meanrevert', 'breakout', 'btcfollow', 'weakshort',
    'scalp', 'sniper',
    # external signal系
    'feardip', 'sectorlead', 'shortsqueeze', 'event',
    'volexhaust', 'fearflat', 'domshift', 'gaptrap', 'sectorsync',
    'meanrevert_adaptive', 'meanrevert_tight', 'meanrevert_hybrid',
    'meanrevert_newlist', 'meanrevert_tuned',
    'ico_meanrevert', 'ico_rebound', 'ico_surge',
]

# ── LevBurnバリアント ──
LEVBURN_BOTS = [
    'levburn', 'levburn_sec', 'levburn_sec_aggressive',
    'levburn_sec_conservative', 'levburn_sec_scalp_micro',
    'levburn_sec_fr_extreme',
]

# ── HFBot一覧 ──
HF_BOTS = [
    'hf_meanrevert', 'hf_momentum', 'hf_spread', 'hf_break', 'hf_frarb',
]

# ── レバレッジグリッド ──
LEVERAGE_GRID_DAILY = [1, 2, 3, 5, 7, 10]
LEVERAGE_GRID_HF    = [3, 5, 7, 10, 15, 20]
LEVERAGE_GRID_LB    = [3, 5, 7, 10, 15, 20]

# レジーム定義 (F&G + BTC 30日リターン)
REGIME_DEFS = {
    'extreme_fear': {'fg_max': 20},
    'fear':         {'fg_min': 20, 'fg_max': 40},
    'neutral':      {'fg_min': 40, 'fg_max': 60},
    'greed':        {'fg_min': 60, 'fg_max': 80},
    'extreme_greed': {'fg_min': 80},
}


def load_config():
    with open('config/settings.yaml', 'r') as f:
        return yaml.safe_load(f)


def get_bot_config(config, bot_type, leverage_override=None):
    """Bot設定を取得し、レバレッジをオーバーライド"""
    # levburn_sec系はbot_levburn_secから設定を取得
    cfg_key = f'bot_{bot_type}'
    bot_cfg = deepcopy(config.get(cfg_key, {}))

    # tp_pct → take_profit_pct 変換
    if 'tp_pct' in bot_cfg and 'take_profit_pct' not in bot_cfg:
        bot_cfg['take_profit_pct'] = bot_cfg['tp_pct']
    if 'sl_pct' in bot_cfg and 'stop_loss_pct' not in bot_cfg:
        bot_cfg['stop_loss_pct'] = bot_cfg['sl_pct']

    if leverage_override is not None:
        bot_cfg['leverage'] = leverage_override

    return bot_cfg


def classify_regime(fg: int) -> str:
    """F&G値からレジームを分類"""
    if fg < 20:
        return 'extreme_fear'
    elif fg < 40:
        return 'fear'
    elif fg < 60:
        return 'neutral'
    elif fg < 80:
        return 'greed'
    else:
        return 'extreme_greed'


def analyze_regime_performance(trades: list, fg_map: dict) -> dict:
    """トレードをレジーム別に分析"""
    regime_trades = defaultdict(list)
    for t in trades:
        entry_date = t.get('entry_date', t.get('signal_date', ''))
        if not entry_date:
            continue
        fg = fg_map.get(entry_date, 50)
        regime = classify_regime(fg)
        regime_trades[regime].append(t)

    result = {}
    for regime, rtrades in regime_trades.items():
        if not rtrades:
            continue
        wins = [t for t in rtrades if t.get('pnl_leveraged_pct', 0) > 0]
        total_pnl = sum(t.get('pnl_amount', 0) for t in rtrades)
        result[regime] = {
            'trades': len(rtrades),
            'win_rate': len(wins) / len(rtrades) * 100 if rtrades else 0,
            'total_pnl': total_pnl,
            'avg_pnl_pct': np.mean([t.get('pnl_leveraged_pct', 0) for t in rtrades]),
            'profit_factor': (
                sum(t['pnl_amount'] for t in wins) /
                abs(sum(t['pnl_amount'] for t in rtrades if t.get('pnl_leveraged_pct', 0) <= 0))
                if any(t.get('pnl_leveraged_pct', 0) <= 0 for t in rtrades) and wins else 999
            ),
        }
    return result


def calc_extra_metrics(trades: list) -> dict:
    """追加メトリクス計算"""
    if not trades:
        return {}

    pnls = [t.get('pnl_leveraged_pct', 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # 月次PnL
    monthly = defaultdict(list)
    for t in trades:
        m = t.get('entry_date', '')[:7]
        if m:
            monthly[m].append(t.get('pnl_leveraged_pct', 0))

    # 年次PnL
    yearly = defaultdict(list)
    for t in trades:
        y = t.get('entry_date', '')[:4]
        if y:
            yearly[y].append(t.get('pnl_amount', 0))

    # 連勝・連敗
    max_cw = max_cl = cw = cl = 0
    for p in pnls:
        if p > 0:
            cw += 1; cl = 0; max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0; max_cl = max(max_cl, cl)

    # 方向別
    longs = [t for t in trades if t.get('side') == 'long']
    shorts = [t for t in trades if t.get('side') == 'short']

    # Exit reasons
    exit_reasons = defaultdict(int)
    for t in trades:
        exit_reasons[t.get('exit_reason', 'unknown')] += 1

    # 銘柄別PnL
    sym_pnl = defaultdict(float)
    sym_count = defaultdict(int)
    for t in trades:
        s = t.get('symbol', '').replace('/USDT:USDT', '')
        sym_pnl[s] += t.get('pnl_leveraged_pct', 0)
        sym_count[s] += 1

    return {
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'best_trade': max(pnls) if pnls else 0,
        'worst_trade': min(pnls) if pnls else 0,
        'max_consec_win': max_cw,
        'max_consec_loss': max_cl,
        'long_count': len(longs),
        'short_count': len(shorts),
        'long_wr': sum(1 for t in longs if t.get('pnl_leveraged_pct', 0) > 0) / len(longs) * 100 if longs else 0,
        'short_wr': sum(1 for t in shorts if t.get('pnl_leveraged_pct', 0) > 0) / len(shorts) * 100 if shorts else 0,
        'exit_reasons': dict(exit_reasons),
        'monthly_pnl': {k: sum(v) for k, v in sorted(monthly.items())},
        'monthly_count': {k: len(v) for k, v in sorted(monthly.items())},
        'yearly_pnl': {k: sum(v) for k, v in sorted(yearly.items())},
        'top_symbols': sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:15],
        'worst_symbols': sorted(sym_pnl.items(), key=lambda x: x[1])[:15],
        'unique_symbols': len(sym_pnl),
    }


# ══════════════════════════════════════════════════════════════
# バックテスト実行
# ══════════════════════════════════════════════════════════════

def run_daily_backtest(db, config, bot_type, leverage, start, end):
    """日足バックテスト1回実行"""
    bot_cfg = get_bot_config(config, bot_type, leverage)
    engine = BacktestEngine(bot_type, bot_cfg, db)
    results = engine.run(start, end)
    results['_trades'] = engine.trades
    results['_equity_curve'] = engine.equity_curve
    return results


def run_hf_backtest(db, config, bot_type, leverage, start, end):
    """HFバックテスト1回実行"""
    bot_cfg = get_bot_config(config, bot_type, leverage)
    engine = HFBacktestEngine(bot_type, bot_cfg, db)
    results = engine.run(start, end)
    results['_trades'] = engine.trades
    results['_equity_curve'] = engine.equity_curve
    return results


def run_phase(phase_name, db, config, bot_list, lev_grid, start, end, is_hf=False):
    """フェーズ実行: Bot群 × レバグリッド"""
    total = len(bot_list) * len(lev_grid)
    print(f"\n{'═' * 80}")
    print(f"  {phase_name}: {len(bot_list)} bots × {len(lev_grid)} leverages = {total} runs")
    print(f"  Period: {start} ~ {end}")
    print(f"{'═' * 80}")

    all_results = {}
    run_fn = run_hf_backtest if is_hf else run_daily_backtest

    done = 0
    phase_start = time.time()

    for bot_type in bot_list:
        for lev in lev_grid:
            key = f"{bot_type}_lev{lev}"
            done += 1
            elapsed = time.time() - phase_start
            eta = (elapsed / done) * (total - done) if done > 0 else 0

            print(f"  [{done}/{total}] {key:<40s} ", end='', flush=True)

            try:
                results = run_fn(db, config, bot_type, lev, start, end)
                trades_n = results.get('total_trades', 0)
                ret = results.get('total_return_pct', 0)
                wr = results.get('win_rate', 0)
                mdd = results.get('max_drawdown_pct', 0)
                sharpe = results.get('sharpe_ratio', 0)

                all_results[key] = {
                    'bot_type': bot_type,
                    'leverage': lev,
                    'results': results,
                    'trades': results.get('_trades', []),
                    'equity_curve': results.get('_equity_curve', []),
                }

                if trades_n > 0:
                    print(f"{trades_n:>5d}T  WR={wr:>5.1f}%  Ret={ret:>+10.1f}%  "
                          f"MDD={mdd:>6.1f}%  Sharpe={sharpe:>6.2f}  "
                          f"[ETA {eta/60:.0f}m]")
                else:
                    print(f"  No trades  [ETA {eta/60:.0f}m]")

            except Exception as e:
                print(f"  ERROR: {e}")
                all_results[key] = {
                    'bot_type': bot_type, 'leverage': lev,
                    'results': {'error': str(e), 'total_trades': 0},
                    'trades': [], 'equity_curve': [],
                }

    elapsed = time.time() - phase_start
    print(f"\n  {phase_name} 完了: {elapsed/60:.1f}分 ({done}ラン)")
    return all_results


# ══════════════════════════════════════════════════════════════
# ハイブリッドBot分析
# ══════════════════════════════════════════════════════════════

def find_best_per_regime(all_results: dict, fg_map: dict) -> dict:
    """レジーム別に最強Bot+レバを特定"""
    regime_scores = defaultdict(list)

    for key, data in all_results.items():
        trades = data.get('trades', [])
        if not trades:
            continue

        regime_perf = analyze_regime_performance(trades, fg_map)
        for regime, perf in regime_perf.items():
            if perf['trades'] >= 5:  # 最低5トレード
                # スコア = Sharpe的指標 (avg_pnl / リスク)
                pnls = [t.get('pnl_leveraged_pct', 0) for t in trades
                        if classify_regime(fg_map.get(t.get('entry_date', ''), 50)) == regime]
                if not pnls:
                    continue
                avg = np.mean(pnls)
                std = np.std(pnls) if len(pnls) > 1 else 1
                score = avg / std if std > 0 else avg
                regime_scores[regime].append({
                    'key': key,
                    'bot_type': data['bot_type'],
                    'leverage': data['leverage'],
                    'score': score,
                    'perf': perf,
                })

    best_per_regime = {}
    for regime, entries in regime_scores.items():
        # スコア上位3つ
        top = sorted(entries, key=lambda x: x['score'], reverse=True)[:3]
        best_per_regime[regime] = top

    return best_per_regime


def simulate_hybrid_bot(all_results: dict, best_per_regime: dict,
                        fg_map: dict, initial_capital: float = 1_000_000) -> dict:
    """ハイブリッドBot: レジーム別に最強Botのトレードを合成"""
    # 各レジームの1位Botからトレードを抽出
    hybrid_trades = []
    used_bots = {}

    for regime, top_list in best_per_regime.items():
        if not top_list:
            continue
        best = top_list[0]
        used_bots[regime] = best['key']
        data = all_results.get(best['key'], {})
        trades = data.get('trades', [])

        for t in trades:
            entry_date = t.get('entry_date', t.get('signal_date', ''))
            if not entry_date:
                continue
            fg = fg_map.get(entry_date, 50)
            if classify_regime(fg) == regime:
                trade_copy = dict(t)
                trade_copy['_hybrid_source'] = best['key']
                trade_copy['_hybrid_regime'] = regime
                hybrid_trades.append(trade_copy)

    # 日付順にソート
    hybrid_trades.sort(key=lambda t: t.get('entry_date', ''))

    # 資本シミュレーション
    capital = initial_capital
    equity_curve = []
    peak = capital
    max_dd = 0

    for t in hybrid_trades:
        capital += t.get('pnl_amount', 0)
        peak = max(peak, capital)
        dd = (capital - peak) / peak * 100 if peak > 0 else 0
        max_dd = min(max_dd, dd)
        equity_curve.append({
            'date': t.get('exit_date', t.get('entry_date', '')),
            'capital': capital,
        })

    wins = [t for t in hybrid_trades if t.get('pnl_leveraged_pct', 0) > 0]
    total = len(hybrid_trades)

    gross_profit = sum(t['pnl_amount'] for t in wins) if wins else 0
    losses = [t for t in hybrid_trades if t.get('pnl_leveraged_pct', 0) <= 0]
    gross_loss = abs(sum(t['pnl_amount'] for t in losses)) if losses else 0

    return {
        'trades': hybrid_trades,
        'equity_curve': equity_curve,
        'used_bots': used_bots,
        'total_trades': total,
        'win_rate': len(wins) / total * 100 if total > 0 else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else 999,
        'total_return_pct': (capital - initial_capital) / initial_capital * 100,
        'max_drawdown_pct': max_dd,
        'final_capital': capital,
    }


# ══════════════════════════════════════════════════════════════
# HTMLレポート生成
# ══════════════════════════════════════════════════════════════

def generate_mega_report(daily_results, hf_results, lb_results,
                         hybrid_result, best_per_regime, fg_map,
                         elapsed_total):
    """包括的HTMLレポート生成"""

    # 全結果をマージ
    all_results = {}
    all_results.update(daily_results)
    all_results.update(hf_results)
    all_results.update(lb_results)

    # ランキング作成（トレードありのみ）
    ranking = []
    for key, data in all_results.items():
        r = data['results']
        if r.get('total_trades', 0) == 0:
            continue
        ranking.append({
            'key': key,
            'bot_type': data['bot_type'],
            'leverage': data['leverage'],
            'trades': r['total_trades'],
            'win_rate': r.get('win_rate', 0),
            'profit_factor': r.get('profit_factor', 0),
            'total_return_pct': r.get('total_return_pct', 0),
            'max_drawdown_pct': r.get('max_drawdown_pct', 0),
            'sharpe_ratio': r.get('sharpe_ratio', 0),
            'final_capital': r.get('final_capital', 0),
            'avg_holding': r.get('avg_holding_days', r.get('avg_holding_hours', 0)),
        })

    ranking.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    # レバレッジ最適解（Bot別にSharpe最大のレバを特定）
    lev_optimal = {}
    for r in ranking:
        bt = r['bot_type']
        if bt not in lev_optimal or r['sharpe_ratio'] > lev_optimal[bt]['sharpe_ratio']:
            lev_optimal[bt] = r

    # Top30のequity curveデータ
    top30 = ranking[:30]
    top30_curves = {}
    for r in top30:
        data = all_results.get(r['key'], {})
        ec = data.get('equity_curve', [])
        if ec:
            top30_curves[r['key']] = ec

    # Bot別最適レバ一覧
    lev_opt_list = sorted(lev_optimal.values(), key=lambda x: x['sharpe_ratio'], reverse=True)

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    hours = elapsed_total / 3600

    # ── HTML構築 ──
    css = """:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d29922;--orange:#db6d28}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',sans-serif;padding:24px;max-width:1800px;margin:0 auto}
h1{color:var(--accent);margin-bottom:8px;font-size:1.8em}
h2{color:var(--accent);font-size:1.3em;margin:30px 0 15px;border-bottom:1px solid var(--border);padding-bottom:8px}
h3{color:var(--text);font-size:1.1em;margin:20px 0 10px}
.subtitle{color:var(--muted);margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:16px}
.grid{display:grid;gap:16px;margin-bottom:20px}
.grid-5{grid-template-columns:repeat(5,1fr)} .grid-4{grid-template-columns:repeat(4,1fr)}
.grid-3{grid-template-columns:repeat(3,1fr)} .grid-2{grid-template-columns:repeat(2,1fr)}
.metric-label{color:var(--muted);font-size:0.8em;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px}
.metric-value{font-size:1.6em;font-weight:bold}
.green{color:var(--green)} .red{color:var(--red)} .yellow{color:var(--yellow)} .orange{color:var(--orange)}
table{width:100%;border-collapse:collapse;font-size:0.85em}
th{color:var(--muted);font-size:0.75em;text-transform:uppercase;text-align:left;padding:6px 8px;border-bottom:2px solid var(--border);position:sticky;top:0;background:var(--card)}
td{padding:6px 8px;border-bottom:1px solid var(--border)}
tr:hover{background:rgba(88,166,255,0.04)}
.rank{display:inline-block;width:22px;height:22px;border-radius:50%;text-align:center;line-height:22px;font-size:0.75em;font-weight:bold;margin-right:4px}
.rank-1{background:#ffd700;color:#000} .rank-2{background:#c0c0c0;color:#000} .rank-3{background:#cd7f32;color:#000}
.chart-container{position:relative;height:400px;margin:15px 0}
.tab-bar{display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap}
.tab-btn{padding:5px 12px;border:1px solid var(--border);border-radius:6px;background:transparent;color:var(--muted);cursor:pointer;font-size:0.8em}
.tab-btn:hover{border-color:var(--accent);color:var(--text)}
.tab-btn.active{background:var(--accent);color:#000;border-color:var(--accent)}
.section{display:none} .section.active{display:block}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.7em;font-weight:bold;color:#000}
.scroll-table{max-height:500px;overflow-y:auto}
footer{text-align:center;color:var(--muted);padding:30px;font-size:0.85em}
@media(max-width:1200px){.grid-5{grid-template-columns:repeat(3,1fr)} .grid-4{grid-template-columns:repeat(2,1fr)}}
"""

    # Color palette for bots
    bot_colors = [
        '#58a6ff', '#f85149', '#3fb950', '#d29922', '#db6d28', '#bc8cff',
        '#39d353', '#f778ba', '#79c0ff', '#ffa657', '#7ee787', '#d2a8ff',
        '#ff7b72', '#56d4dd', '#e3b341', '#8b949e', '#f0883e', '#a5d6ff',
        '#ffdcd7', '#c9d1d9', '#b392f0', '#ffdf5d', '#85e89d', '#f97583',
        '#b1bac4', '#fddf68', '#dbedff', '#ffeef0', '#dafbe1', '#fff5b1',
    ]

    def get_color(idx):
        return bot_colors[idx % len(bot_colors)]

    parts = []
    parts.append(f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mega Backtest Report - Empire Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{css}</style></head><body>
<h1>Empire Monitor — Mega Backtest Report</h1>
<p class="subtitle">Daily: {DAILY_START} ~ {DAILY_END} (6Y) | HF: {HF_START} ~ {HF_END} |
{len(all_results)} runs | {hours:.1f}h compute | Generated: {now}</p>''')

    # ══ Section 0: Executive Summary ══
    total_runs = len(all_results)
    runs_with_trades = len(ranking)
    best = ranking[0] if ranking else None

    parts.append('<h2>0. Executive Summary</h2>')
    parts.append('<div class="grid grid-5">')
    parts.append(f'<div class="card"><div class="metric-label">Total Runs</div><div class="metric-value">{total_runs}</div></div>')
    parts.append(f'<div class="card"><div class="metric-label">With Trades</div><div class="metric-value">{runs_with_trades}</div></div>')
    if best:
        parts.append(f'<div class="card"><div class="metric-label">Best Sharpe</div><div class="metric-value green">{best["sharpe_ratio"]:.2f}</div><div style="color:var(--muted);font-size:0.7em">{best["key"]}</div></div>')
        best_ret = max(ranking, key=lambda x: x['total_return_pct'])
        parts.append(f'<div class="card"><div class="metric-label">Best Return</div><div class="metric-value green">{best_ret["total_return_pct"]:+,.0f}%</div><div style="color:var(--muted);font-size:0.7em">{best_ret["key"]}</div></div>')
    if hybrid_result:
        parts.append(f'<div class="card"><div class="metric-label">Hybrid Bot</div><div class="metric-value green">{hybrid_result["total_return_pct"]:+,.0f}%</div><div style="color:var(--muted);font-size:0.7em">{hybrid_result["total_trades"]}T WR{hybrid_result["win_rate"]:.0f}%</div></div>')
    parts.append('</div>')

    # ══ Section 1: Top 50 Ranking ══
    parts.append('<h2>1. Performance Ranking (Top 50 by Sharpe)</h2>')
    parts.append('<div class="card"><div class="scroll-table"><table>')
    parts.append('<tr><th>#</th><th>Bot + Leverage</th><th>Trades</th><th>Win Rate</th>'
                 '<th>PF</th><th>Total Return</th><th>MDD</th><th>Sharpe</th><th>Final ¥</th></tr>')

    for i, r in enumerate(ranking[:50]):
        rank_cls = f' rank-{i+1}' if i < 3 else ''
        ret_cls = 'green' if r['total_return_pct'] > 0 else 'red'
        wr_cls = 'green' if r['win_rate'] >= 60 else ('yellow' if r['win_rate'] >= 50 else 'red')
        sh_cls = 'green' if r['sharpe_ratio'] >= 5 else ('yellow' if r['sharpe_ratio'] >= 2 else 'red')
        color = get_color(i)
        parts.append(
            f'<tr><td><span class="rank{rank_cls}">{i+1}</span></td>'
            f'<td><span class="badge" style="background:{color}">{r["bot_type"]}</span> {r["leverage"]}x</td>'
            f'<td>{r["trades"]}</td><td class="{wr_cls}">{r["win_rate"]:.1f}%</td>'
            f'<td>{r["profit_factor"]:.2f}</td>'
            f'<td class="{ret_cls}" style="font-weight:bold">{r["total_return_pct"]:+,.1f}%</td>'
            f'<td class="red">{r["max_drawdown_pct"]:.1f}%</td>'
            f'<td class="{sh_cls}" style="font-weight:bold">{r["sharpe_ratio"]:.2f}</td>'
            f'<td>&yen;{r["final_capital"]:,.0f}</td></tr>'
        )

    parts.append('</table></div></div>')

    # ══ Section 2: Optimal Leverage per Bot ══
    parts.append('<h2>2. Optimal Leverage per Bot (by Sharpe)</h2>')
    parts.append('<div class="card"><table>')
    parts.append('<tr><th>#</th><th>Bot</th><th>Best Leverage</th><th>Trades</th>'
                 '<th>WR</th><th>Return</th><th>MDD</th><th>Sharpe</th></tr>')

    for i, r in enumerate(lev_opt_list):
        ret_cls = 'green' if r['total_return_pct'] > 0 else 'red'
        parts.append(
            f'<tr><td>{i+1}</td><td><b>{r["bot_type"]}</b></td>'
            f'<td style="font-weight:bold;color:var(--accent)">{r["leverage"]}x</td>'
            f'<td>{r["trades"]}</td><td>{r["win_rate"]:.1f}%</td>'
            f'<td class="{ret_cls}">{r["total_return_pct"]:+,.1f}%</td>'
            f'<td class="red">{r["max_drawdown_pct"]:.1f}%</td>'
            f'<td>{r["sharpe_ratio"]:.2f}</td></tr>'
        )

    parts.append('</table></div>')

    # ══ Section 3: Leverage Sensitivity Heatmap ══
    parts.append('<h2>3. Leverage Sensitivity (Sharpe Ratio Heatmap)</h2>')

    # グループ別にヒートマップ表示
    for group_name, bot_list, lev_grid in [
        ('Daily Bots', DAILY_BOTS, LEVERAGE_GRID_DAILY),
        ('HF Bots', HF_BOTS, LEVERAGE_GRID_HF),
        ('LevBurn', LEVBURN_BOTS, LEVERAGE_GRID_LB),
    ]:
        parts.append(f'<h3>{group_name}</h3>')
        parts.append('<div class="card"><div class="scroll-table"><table>')
        parts.append(f'<tr><th>Bot</th>')
        for lev in lev_grid:
            parts.append(f'<th>{lev}x</th>')
        parts.append('</tr>')

        for bot in bot_list:
            parts.append(f'<tr><td><b>{bot}</b></td>')
            for lev in lev_grid:
                key = f"{bot}_lev{lev}"
                data = all_results.get(key, {})
                r = data.get('results', {})
                sharpe = r.get('sharpe_ratio', 0)
                trades_n = r.get('total_trades', 0)

                if trades_n == 0:
                    parts.append('<td style="color:var(--muted)">—</td>')
                else:
                    # Color intensity based on Sharpe
                    if sharpe >= 8:
                        bg = 'rgba(63,185,80,0.4)'
                    elif sharpe >= 5:
                        bg = 'rgba(63,185,80,0.25)'
                    elif sharpe >= 2:
                        bg = 'rgba(210,153,34,0.25)'
                    elif sharpe >= 0:
                        bg = 'rgba(210,153,34,0.1)'
                    else:
                        bg = 'rgba(248,81,73,0.25)'

                    ret = r.get('total_return_pct', 0)
                    parts.append(f'<td style="background:{bg};text-align:center" '
                                 f'title="{bot} {lev}x: {trades_n}T Ret={ret:+.0f}%">'
                                 f'<b>{sharpe:.1f}</b><br><span style="font-size:0.7em;color:var(--muted)">'
                                 f'{ret:+.0f}%</span></td>')

            parts.append('</tr>')
        parts.append('</table></div></div>')

    # ══ Section 4: Equity Curves (Top 10) ══
    parts.append('<h2>4. Equity Curves (Top 10 by Sharpe)</h2>')
    parts.append('<div class="card"><div class="chart-container"><canvas id="equityChart"></canvas></div></div>')

    datasets = []
    for i, r in enumerate(ranking[:10]):
        data = all_results.get(r['key'], {})
        ec = data.get('equity_curve', [])
        if not ec:
            continue
        # サンプリング（データポイント多すぎ防止）
        step = max(1, len(ec) // 500)
        sampled = ec[::step]
        datasets.append({
            'label': f"{r['bot_type']} {r['leverage']}x",
            'data': [{'x': p.get('date', ''), 'y': p.get('capital', 0)} for p in sampled],
            'borderColor': get_color(i),
            'borderWidth': 2, 'pointRadius': 0, 'fill': False, 'tension': 0.1,
        })

    parts.append(f'''<script>
new Chart(document.getElementById('equityChart'), {{
    type: 'line',
    data: {{ datasets: {json.dumps(datasets)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#e6edf3', font: {{ size: 10 }} }}, position: 'top' }} }},
        scales: {{
            x: {{ type: 'category', ticks: {{ color: '#8b949e', maxTicksLimit: 20 }}, grid: {{ color: '#30363d' }} }},
            y: {{ ticks: {{ color: '#8b949e', callback: function(v) {{ return '\\u00a5' + v.toLocaleString(); }} }}, grid: {{ color: '#30363d' }} }}
        }}
    }}
}});
</script>''')

    # ══ Section 5: Regime Analysis ══
    parts.append('<h2>5. Regime Analysis — Best Bot per Market Condition</h2>')

    regime_labels = {
        'extreme_fear': 'Extreme Fear (F&G < 20)',
        'fear': 'Fear (F&G 20-40)',
        'neutral': 'Neutral (F&G 40-60)',
        'greed': 'Greed (F&G 60-80)',
        'extreme_greed': 'Extreme Greed (F&G > 80)',
    }
    regime_colors = {
        'extreme_fear': '#f85149', 'fear': '#ffa657',
        'neutral': '#d29922', 'greed': '#3fb950', 'extreme_greed': '#58a6ff',
    }

    for regime in ['extreme_fear', 'fear', 'neutral', 'greed', 'extreme_greed']:
        top = best_per_regime.get(regime, [])
        label = regime_labels.get(regime, regime)
        color = regime_colors.get(regime, '#8b949e')

        parts.append(f'<h3 style="color:{color}">{label}</h3>')
        if not top:
            parts.append('<div class="card"><p style="color:var(--muted)">No qualifying bots (min 5 trades)</p></div>')
            continue

        parts.append('<div class="card"><table>')
        parts.append('<tr><th>#</th><th>Bot + Leverage</th><th>Trades</th><th>WR</th><th>Avg PnL</th><th>PF</th><th>Score</th></tr>')
        for i, entry in enumerate(top):
            p = entry['perf']
            parts.append(
                f'<tr><td>{i+1}</td><td><b>{entry["key"]}</b></td>'
                f'<td>{p["trades"]}</td><td>{p["win_rate"]:.1f}%</td>'
                f'<td>{p["avg_pnl_pct"]:+.2f}%</td><td>{p["profit_factor"]:.2f}</td>'
                f'<td>{entry["score"]:.3f}</td></tr>'
            )
        parts.append('</table></div>')

    # ══ Section 6: Hybrid Bot ══
    if hybrid_result:
        parts.append('<h2>6. Hybrid "Best Of" Bot — Regime-Switched Composite</h2>')

        parts.append('<div class="grid grid-5">')
        hr = hybrid_result
        ret_cls = 'green' if hr['total_return_pct'] > 0 else 'red'
        parts.append(f'<div class="card"><div class="metric-label">Total Return</div><div class="metric-value {ret_cls}">{hr["total_return_pct"]:+,.1f}%</div></div>')
        parts.append(f'<div class="card"><div class="metric-label">Trades</div><div class="metric-value">{hr["total_trades"]}</div></div>')
        parts.append(f'<div class="card"><div class="metric-label">Win Rate</div><div class="metric-value">{hr["win_rate"]:.1f}%</div></div>')
        parts.append(f'<div class="card"><div class="metric-label">Profit Factor</div><div class="metric-value">{hr["profit_factor"]:.2f}</div></div>')
        parts.append(f'<div class="card"><div class="metric-label">MDD</div><div class="metric-value red">{hr["max_drawdown_pct"]:.1f}%</div></div>')
        parts.append('</div>')

        # Bot使い分け表
        parts.append('<div class="card"><h3>Regime → Bot Mapping</h3><table>')
        parts.append('<tr><th>Market Regime</th><th>Selected Bot</th></tr>')
        for regime, key in hr.get('used_bots', {}).items():
            label = regime_labels.get(regime, regime)
            color = regime_colors.get(regime, '#8b949e')
            parts.append(f'<tr><td style="color:{color}">{label}</td><td><b>{key}</b></td></tr>')
        parts.append('</table></div>')

        # Hybrid equity curve
        hec = hr.get('equity_curve', [])
        if hec:
            parts.append('<div class="card"><div class="chart-container"><canvas id="hybridChart"></canvas></div></div>')
            step = max(1, len(hec) // 500)
            sampled = hec[::step]
            hds = [{
                'label': 'Hybrid Bot',
                'data': [{'x': p['date'], 'y': p['capital']} for p in sampled],
                'borderColor': '#ffd700', 'borderWidth': 3, 'pointRadius': 0, 'fill': False,
            }]
            parts.append(f'''<script>
new Chart(document.getElementById('hybridChart'), {{
    type: 'line',
    data: {{ datasets: {json.dumps(hds)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }},
        scales: {{
            x: {{ type: 'category', ticks: {{ color: '#8b949e', maxTicksLimit: 20 }}, grid: {{ color: '#30363d' }} }},
            y: {{ ticks: {{ color: '#8b949e', callback: function(v) {{ return '\\u00a5' + v.toLocaleString(); }} }}, grid: {{ color: '#30363d' }} }}
        }}
    }}
}});
</script>''')

    # ══ Section 7: Top 10 Bot Details ══
    parts.append('<h2>7. Top 10 Bot Details</h2>')
    parts.append('<div class="tab-bar">')
    for i, r in enumerate(ranking[:10]):
        active = ' active' if i == 0 else ''
        parts.append(f'<button class="tab-btn{active}" onclick="showDetail(\'{r["key"]}\')" '
                      f'style="border-color:{get_color(i)}">{r["bot_type"]} {r["leverage"]}x</button>')
    parts.append('</div>')

    for idx, r in enumerate(ranking[:10]):
        data = all_results.get(r['key'], {})
        trades = data.get('trades', [])
        extra = calc_extra_metrics(trades)
        active = ' active' if idx == 0 else ''

        ret_cls = 'green' if r['total_return_pct'] > 0 else 'red'

        parts.append(f'<div class="section{active}" id="detail-{r["key"]}">')

        # KPI
        parts.append(f'''<div class="grid grid-5">
<div class="card"><div class="metric-label">Return</div><div class="metric-value {ret_cls}">{r["total_return_pct"]:+,.1f}%</div></div>
<div class="card"><div class="metric-label">Win Rate</div><div class="metric-value">{r["win_rate"]:.1f}%</div><div style="color:var(--muted);font-size:0.7em">{len([t for t in trades if t.get("pnl_leveraged_pct",0)>0])}W / {len([t for t in trades if t.get("pnl_leveraged_pct",0)<=0])}L</div></div>
<div class="card"><div class="metric-label">Profit Factor</div><div class="metric-value">{r["profit_factor"]:.2f}</div></div>
<div class="card"><div class="metric-label">Sharpe</div><div class="metric-value">{r["sharpe_ratio"]:.2f}</div></div>
<div class="card"><div class="metric-label">MDD</div><div class="metric-value red">{r["max_drawdown_pct"]:.1f}%</div></div>
</div>''')

        # Direction + Exit reasons
        if extra:
            parts.append('<div class="grid grid-2">')
            parts.append(f'''<div class="card"><h3>Direction</h3><table>
<tr><th>Side</th><th>Trades</th><th>Win Rate</th></tr>
<tr><td class="green">LONG</td><td>{extra["long_count"]}</td><td>{extra["long_wr"]:.1f}%</td></tr>
<tr><td class="red">SHORT</td><td>{extra["short_count"]}</td><td>{extra["short_wr"]:.1f}%</td></tr>
</table></div>''')

            exit_r = extra.get('exit_reasons', {})
            total_ex = sum(exit_r.values()) or 1
            parts.append('<div class="card"><h3>Exit Reasons</h3><table>')
            parts.append('<tr><th>Reason</th><th>Count</th><th>%</th></tr>')
            for reason, cnt in sorted(exit_r.items(), key=lambda x: -x[1]):
                parts.append(f'<tr><td>{reason}</td><td>{cnt}</td><td>{cnt/total_ex*100:.1f}%</td></tr>')
            parts.append('</table></div></div>')

            # Yearly PnL
            yearly = extra.get('yearly_pnl', {})
            if yearly:
                parts.append('<div class="card"><h3>Yearly PnL (Amount)</h3><table>')
                parts.append('<tr><th>Year</th><th>PnL (¥)</th><th>Cumulative</th></tr>')
                cum = 0
                for y, pnl in sorted(yearly.items()):
                    cum += pnl
                    cls = 'green' if pnl >= 0 else 'red'
                    parts.append(f'<tr><td>{y}</td><td class="{cls}">&yen;{pnl:+,.0f}</td><td>&yen;{cum:+,.0f}</td></tr>')
                parts.append('</table></div>')

            # Top / Worst symbols
            parts.append('<div class="grid grid-2">')
            parts.append('<div class="card"><h3>Top Symbols</h3><table><tr><th>Symbol</th><th>PnL%</th></tr>')
            for sym, pnl in extra.get('top_symbols', [])[:10]:
                cls = 'green' if pnl >= 0 else 'red'
                parts.append(f'<tr><td>{sym}</td><td class="{cls}">{pnl:+.1f}%</td></tr>')
            parts.append('</table></div>')
            parts.append('<div class="card"><h3>Worst Symbols</h3><table><tr><th>Symbol</th><th>PnL%</th></tr>')
            for sym, pnl in extra.get('worst_symbols', [])[:10]:
                cls = 'green' if pnl >= 0 else 'red'
                parts.append(f'<tr><td>{sym}</td><td class="{cls}">{pnl:+.1f}%</td></tr>')
            parts.append('</table></div></div>')

        parts.append('</div>')  # section

    # ══ Section 8: Strategy Insights ══
    parts.append('<h2>8. Strategy Insights & Recommendations</h2>')
    parts.append('<div class="card">')

    # Auto-generate insights from data
    if ranking:
        best_sharpe = ranking[0]
        best_return = max(ranking, key=lambda x: x['total_return_pct'])
        best_wr = max(ranking, key=lambda x: x['win_rate'])
        lowest_mdd = min(ranking, key=lambda x: x['max_drawdown_pct'])

        parts.append(f'''
<h3>Key Findings</h3>
<ul style="color:var(--muted);line-height:2;padding-left:20px">
<li><strong style="color:var(--text)">Best Risk-Adjusted:</strong> {best_sharpe["key"]} — Sharpe {best_sharpe["sharpe_ratio"]:.2f}, Return {best_sharpe["total_return_pct"]:+,.0f}%, MDD {best_sharpe["max_drawdown_pct"]:.1f}%</li>
<li><strong style="color:var(--text)">Highest Return:</strong> {best_return["key"]} — {best_return["total_return_pct"]:+,.0f}%, Sharpe {best_return["sharpe_ratio"]:.2f}</li>
<li><strong style="color:var(--text)">Highest Win Rate:</strong> {best_wr["key"]} — WR {best_wr["win_rate"]:.1f}%, {best_wr["trades"]}T</li>
<li><strong style="color:var(--text)">Lowest Drawdown:</strong> {lowest_mdd["key"]} — MDD {lowest_mdd["max_drawdown_pct"]:.1f}%, Return {lowest_mdd["total_return_pct"]:+,.0f}%</li>
</ul>''')

        # Leverage recommendations
        parts.append('<h3 style="margin-top:16px">Leverage Recommendations</h3>')
        parts.append('<ul style="color:var(--muted);line-height:2;padding-left:20px">')
        for r in lev_opt_list[:10]:
            parts.append(f'<li><strong style="color:var(--text)">{r["bot_type"]}</strong>: '
                         f'Optimal leverage = <span style="color:var(--accent)">{r["leverage"]}x</span> '
                         f'(Sharpe {r["sharpe_ratio"]:.2f}, Return {r["total_return_pct"]:+,.0f}%)</li>')
        parts.append('</ul>')

    if hybrid_result:
        parts.append(f'''<h3 style="margin-top:16px">Hybrid Bot Performance</h3>
<p style="color:var(--muted)">The regime-switched hybrid combines the best-performing bot for each market condition
(Fear & Greed levels). This approach yielded <strong style="color:var(--green)">{hybrid_result["total_return_pct"]:+,.1f}%</strong>
return over the backtest period with {hybrid_result["total_trades"]} trades and
MDD of <strong style="color:var(--red)">{hybrid_result["max_drawdown_pct"]:.1f}%</strong>.</p>''')

    parts.append('''<h3 style="margin-top:16px">Important Caveats</h3>
<ul style="color:var(--red);line-height:2;padding-left:20px">
<li>LevBurn-Sec bots use daily FR proxy in backtest — live 1-second trigger logic is NOT simulated</li>
<li>Backtest uses daily candles — intraday price paths not simulated (TP/SL checked at daily extremes)</li>
<li>Past performance does not guarantee future results — market regime can shift</li>
<li>HF bots tested on 15-month 1h data only (limited compared to 6Y daily)</li>
<li>Hybrid bot is in-sample optimized — walk-forward validation recommended</li>
</ul>''')
    parts.append('</div>')

    # Tab JS
    parts.append('''<script>
function showDetail(key) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    var el = document.getElementById('detail-' + key);
    if (el) el.classList.add('active');
    if (event && event.target) event.target.classList.add('active');
}
</script>''')

    parts.append(f'<footer>Empire Monitor Mega Backtest Report | {now} | {hours:.1f}h compute time</footer>')
    parts.append('</body></html>')

    return '\n'.join(parts)


# ══════════════════════════════════════════════════════════════
# メイン
# ══════════════════════════════════════════════════════════════

async def main():
    config = load_config()
    db = HistoricalDB()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # F&Gマップ取得
    conn = db._get_conn()
    fg_rows = conn.execute("SELECT date, value FROM fear_greed_history ORDER BY date").fetchall()
    fg_map = {r[0]: r[1] for r in fg_rows}
    fg_count = len(fg_map)
    fg_range = conn.execute("SELECT MIN(date), MAX(date) FROM fear_greed_history").fetchone()

    # 1dデータ範囲確認
    d1_range = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT symbol) FROM ohlcv WHERE timeframe='1d'"
    ).fetchone()
    h1_range = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT symbol) FROM ohlcv WHERE timeframe='1h'"
    ).fetchone()
    conn.close()

    print("=" * 80)
    print("  MEGA BACKTEST — Empire Monitor")
    print("=" * 80)
    print(f"  1d data: {datetime.utcfromtimestamp(d1_range[0]/1000).strftime('%Y-%m-%d')} ~ "
          f"{datetime.utcfromtimestamp(d1_range[1]/1000).strftime('%Y-%m-%d')} ({d1_range[2]} symbols)")
    print(f"  1h data: {datetime.utcfromtimestamp(h1_range[0]/1000).strftime('%Y-%m-%d')} ~ "
          f"{datetime.utcfromtimestamp(h1_range[1]/1000).strftime('%Y-%m-%d')} ({h1_range[2]} symbols)")
    print(f"  F&G: {fg_count} days ({fg_range[0]} ~ {fg_range[1]})")
    print(f"  Daily bots: {len(DAILY_BOTS)} × {len(LEVERAGE_GRID_DAILY)} lev = {len(DAILY_BOTS)*len(LEVERAGE_GRID_DAILY)}")
    print(f"  LevBurn:    {len(LEVBURN_BOTS)} × {len(LEVERAGE_GRID_LB)} lev = {len(LEVBURN_BOTS)*len(LEVERAGE_GRID_LB)}")
    print(f"  HF bots:    {len(HF_BOTS)} × {len(LEVERAGE_GRID_HF)} lev = {len(HF_BOTS)*len(LEVERAGE_GRID_HF)}")
    total_runs = (len(DAILY_BOTS)*len(LEVERAGE_GRID_DAILY) +
                  len(LEVBURN_BOTS)*len(LEVERAGE_GRID_LB) +
                  len(HF_BOTS)*len(LEVERAGE_GRID_HF))
    print(f"  Total runs: {total_runs}")
    print("=" * 80)

    mega_start = time.time()

    # ── Phase 1: Daily Bots ──
    daily_results = run_phase(
        "Phase 1: Daily Bots (6Y)", db, config,
        DAILY_BOTS, LEVERAGE_GRID_DAILY, DAILY_START, DAILY_END
    )

    # ── Phase 2: LevBurn Variants ──
    lb_results = run_phase(
        "Phase 2: LevBurn Variants (6Y)", db, config,
        LEVBURN_BOTS, LEVERAGE_GRID_LB, DAILY_START, DAILY_END
    )

    # ── Phase 3: HF Bots ──
    hf_results = run_phase(
        "Phase 3: HF Bots (15M)", db, config,
        HF_BOTS, LEVERAGE_GRID_HF, HF_START, HF_END,
        is_hf=True
    )

    # ── Phase 4: Analysis ──
    print(f"\n{'═' * 80}")
    print("  Phase 4: Regime Analysis + Hybrid Bot")
    print(f"{'═' * 80}")

    all_results = {}
    all_results.update(daily_results)
    all_results.update(lb_results)
    all_results.update(hf_results)

    best_per_regime = find_best_per_regime(all_results, fg_map)
    print("\n  Regime winners:")
    for regime, top in best_per_regime.items():
        if top:
            print(f"    {regime:20s} → {top[0]['key']:40s} (score={top[0]['score']:.3f})")

    hybrid_result = simulate_hybrid_bot(all_results, best_per_regime, fg_map)
    print(f"\n  Hybrid Bot: {hybrid_result['total_trades']}T, "
          f"WR={hybrid_result['win_rate']:.1f}%, "
          f"Return={hybrid_result['total_return_pct']:+,.1f}%, "
          f"MDD={hybrid_result['max_drawdown_pct']:.1f}%")

    # ── Phase 5: Save CSVs ──
    print(f"\n{'═' * 80}")
    print("  Phase 5: Saving Results")
    print(f"{'═' * 80}")

    # Summary CSV
    csv_path = OUT_DIR / 'mega_summary.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['key', 'bot_type', 'leverage', 'trades', 'win_rate', 'profit_factor',
                     'total_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'final_capital'])
        for key, data in sorted(all_results.items(),
                                 key=lambda x: x[1].get('results', {}).get('sharpe_ratio', 0),
                                 reverse=True):
            r = data['results']
            w.writerow([key, data['bot_type'], data['leverage'],
                        r.get('total_trades', 0), r.get('win_rate', 0),
                        f"{r.get('profit_factor', 0):.2f}",
                        f"{r.get('total_return_pct', 0):.2f}",
                        f"{r.get('max_drawdown_pct', 0):.2f}",
                        f"{r.get('sharpe_ratio', 0):.2f}",
                        f"{r.get('final_capital', 0):.0f}"])
    print(f"  Summary CSV: {csv_path}")

    # Per-bot trade CSVs for top 20
    ranking = sorted(
        [(k, d) for k, d in all_results.items() if d['results'].get('total_trades', 0) > 0],
        key=lambda x: x[1]['results'].get('sharpe_ratio', 0), reverse=True
    )

    for key, data in ranking[:20]:
        trades = data.get('trades', [])
        if not trades:
            continue
        trade_csv = OUT_DIR / f'trades_{key}.csv'
        with open(trade_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            cols = ['symbol', 'entry_date', 'entry_price', 'side', 'leverage',
                    'exit_date', 'exit_price', 'exit_reason', 'holding_days',
                    'pnl_pct', 'pnl_leveraged_pct', 'pnl_amount']
            w.writerow(cols)
            for t in trades:
                w.writerow([t.get(c, '') for c in cols])

    print(f"  Trade CSVs: Top 20 bots saved")

    elapsed_total = time.time() - mega_start

    # ── Phase 6: HTML Report ──
    print(f"\n{'═' * 80}")
    print("  Phase 6: Generating HTML Report")
    print(f"{'═' * 80}")

    html = generate_mega_report(
        daily_results, hf_results, lb_results,
        hybrid_result, best_per_regime, fg_map,
        elapsed_total
    )

    html_path = OUT_DIR / 'mega_backtest_report.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"  HTML Report: {html_path}")
    print(f"  Size: {len(html):,} bytes")

    # ── 完了 ──
    hours = elapsed_total / 3600
    minutes = elapsed_total / 60
    print(f"\n{'═' * 80}")
    print(f"  MEGA BACKTEST 完了")
    print(f"  Total time: {hours:.1f}h ({minutes:.0f}m)")
    print(f"  Total runs: {total_runs}")
    print(f"  Results: {OUT_DIR}")
    print(f"{'═' * 80}")

    # Telegram通知
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        msg = (f"MEGA BACKTEST 完了\n"
               f"{total_runs} runs, {hours:.1f}h\n"
               f"Top Sharpe: {ranking[0][0] if ranking else 'N/A'}\n"
               f"Hybrid: {hybrid_result['total_return_pct']:+,.0f}% "
               f"({hybrid_result['total_trades']}T)")
        await alert.send_message(msg)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
