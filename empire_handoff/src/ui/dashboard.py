"""Empire Monitor ローカルGUIダッシュボード - Flask製"""
import os
import sys
import yaml
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request
from markupsafe import Markup

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.bot_display_names import get_display_name

ROUND_TRIP_COST_PCT = 0.22  # 往復コスト (taker + slippage)

app = Flask(__name__)

DB_PATH = PROJECT_ROOT / "data" / "empire_monitor.db"
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

# グローバル状態（エンジン統合時に更新される）
_state = {
    'btc_price': 0,
    'fear_greed': 50,
    'btc_d': 0,
    'regime': 'F',
    'start_time': datetime.now().isoformat(),
    'cycle_count': 0,
    'error_count': 0,
    'watchlist': [],
    'bot_status': {},
}

# BotManager参照（create_appで注入）
_bot_manager = None
_ws_feed = None  # WebSocketFeed参照
_order_executor = None  # OrderExecutor参照（サーキットブレーカー情報用）
_engine = None  # EmpireMonitor参照（サーキットブレーカー等のアクセス用）


def get_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def get_db():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(str(DB_PATH))


def update_state(new_state: dict):
    """エンジンから状態更新"""
    _state.update(new_state)


# ========================================
# HTML テンプレート
# ========================================

DARK_CSS = """:root {
    --bg: #0d1117;
    --card-bg: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --yellow: #d29922;
    --orange: #db6d28;
    --red: #f85149;
    --gray: #484f58;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, 'Segoe UI', sans-serif;
    padding: 20px;
    max-width: 1400px;
    margin: 0 auto;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 15px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 20px;
}
.header h1 { color: var(--accent); font-size: 1.5em; }
.nav { display: flex; gap: 15px; }
.nav a {
    color: var(--muted);
    text-decoration: none;
    padding: 5px 12px;
    border-radius: 6px;
    transition: all 0.2s;
}
.nav a:hover, .nav a.active {
    color: var(--text);
    background: var(--card-bg);
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 15px;
    margin-bottom: 25px;
}
.card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
}
.card h3 {
    color: var(--muted);
    font-size: 0.85em;
    margin-bottom: 8px;
    text-transform: uppercase;
}
.metric {
    font-size: 1.8em;
    font-weight: bold;
}
.metric.green { color: var(--green); }
.metric.yellow { color: var(--yellow); }
.metric.red { color: var(--red); }
.label {
    color: var(--muted);
    font-size: 0.9em;
}
.status-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
}
.status-dot.green { background: var(--green); }
.status-dot.yellow { background: var(--yellow); }
.status-dot.orange { background: var(--orange); }
.status-dot.red { background: var(--red); }
.status-dot.gray { background: var(--gray); }
.mode-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: bold;
    text-transform: uppercase;
}
.mode-badge.live { background: var(--green); color: #000; }
.mode-badge.paper { background: var(--yellow); color: #000; }
.mode-badge.disabled { background: var(--gray); color: var(--muted); }
.bot-card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
    transition: border-color 0.2s;
}
.bot-card:hover { border-color: var(--accent); }
.bot-controls {
    display: flex;
    gap: 8px;
    margin-top: 12px;
}
.mode-btn {
    flex: 1;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-size: 0.8em;
    transition: all 0.2s;
}
.mode-btn:hover { border-color: var(--accent); color: var(--text); }
.mode-btn.active-live { background: var(--green); color: #000; border-color: var(--green); }
.mode-btn.active-paper { background: var(--yellow); color: #000; border-color: var(--yellow); }
.mode-btn.active-disabled { background: var(--gray); color: var(--text); }
table {
    width: 100%;
    border-collapse: collapse;
}
th, td {
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
}
th { color: var(--muted); font-size: 0.85em; text-transform: uppercase; }
.score-bar {
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
}
.score-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
}
.filter-bar {
    display: flex;
    gap: 20px;
    align-items: center;
    padding: 12px 0;
    margin-bottom: 15px;
    flex-wrap: wrap;
}
.filter-group {
    display: flex;
    align-items: center;
    gap: 8px;
}
.filter-label {
    color: var(--muted);
    font-size: 0.85em;
}
.filter-btn {
    padding: 5px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-size: 0.8em;
    transition: all 0.2s;
}
.filter-btn:hover { border-color: var(--accent); color: var(--text); }
.filter-btn.active { background: var(--accent); color: #000; border-color: var(--accent); }
.sort-select {
    background: var(--card-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 0.85em;
}
.search-input {
    background: var(--card-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 0.85em;
    width: 180px;
}
.search-input::placeholder { color: var(--gray); }
.overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.8);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}
.overlay.hidden { display: none; }
.overlay-content {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    width: 90%;
    max-width: 800px;
    max-height: 85vh;
    overflow-y: auto;
    padding: 25px;
}
.overlay-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 15px;
    border-bottom: 1px solid var(--border);
}
.overlay-header h2 { color: var(--accent); }
.overlay-controls { display: flex; align-items: center; gap: 15px; }
.close-btn {
    background: transparent;
    border: none;
    color: var(--muted);
    font-size: 1.5em;
    cursor: pointer;
}
.close-btn:hover { color: var(--text); }
.perf-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 20px;
}
.perf-card {
    background: var(--bg);
    border-radius: 8px;
    padding: 12px;
    text-align: center;
}
.perf-label { color: var(--muted); font-size: 0.8em; margin-bottom: 4px; }
.perf-value { font-size: 1.3em; font-weight: bold; }
.perf-value.green { color: var(--green); }
.perf-value.red { color: var(--red); }
.perf-comparison { margin-bottom: 20px; }
.perf-comparison h3, .signal-history h3 {
    color: var(--accent);
    font-size: 1em;
    margin-bottom: 10px;
}
.green { color: var(--green); }
.red { color: var(--red); }
.bot-card { cursor: pointer; }
.bot-card:active { transform: scale(0.98); }
.bot-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 15px;
    margin-bottom: 25px;
}
.live-bar {
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 25px;
    padding: 12px 20px;
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border-bottom: 2px solid var(--border);
    margin: -20px -20px 20px -20px;
    flex-wrap: wrap;
}
.live-total { display: flex; flex-direction: column; margin-right: 20px; }
.live-label { color: var(--muted); font-size: 0.7em; text-transform: uppercase; letter-spacing: 1px; }
.live-pnl { font-size: 2em; font-weight: bold; }
.live-stat { display: flex; flex-direction: column; align-items: center; }
.live-value { font-size: 1.1em; font-weight: 600; }
.live-alert {
    margin-left: auto;
    padding: 8px 15px;
    background: rgba(248,81,73,0.15);
    border: 1px solid var(--red);
    border-radius: 8px;
    color: var(--red);
    font-weight: bold;
    animation: pulse 1.5s infinite;
}
.live-alert.hidden { display: none; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
.mode-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.mode-dot.live { background: var(--green); }
.mode-dot.paper { background: var(--yellow); }
.position-table { margin-bottom: 25px; width: 100%; }
.position-table th, .position-table td { padding: 8px 6px; white-space: nowrap; font-size: 0.85em; }
.position-row:hover { background: rgba(88,166,255,0.05); }
.btn-close {
    padding: 4px 10px; background: transparent; border: 1px solid var(--red);
    border-radius: 4px; color: var(--red); cursor: pointer; font-size: 0.8em;
}
.btn-close:hover { background: var(--red); color: #fff; }
.tp-sl-bar { height: 16px; background: var(--border); border-radius: 6px; position: relative; margin: 2px 0; min-width: 80px; overflow: visible; }
.tp-sl-bar .sl-zone { position: absolute; left: 0; height: 100%; background: rgba(248,81,73,0.3); border-radius: 6px 0 0 6px; }
.tp-sl-bar .tp-zone { position: absolute; right: 0; height: 100%; background: rgba(63,185,80,0.3); border-radius: 0 6px 6px 0; }
.tp-sl-bar .entry-line { position: absolute; height: 100%; width: 1px; background: var(--muted); opacity: 0.5; }
.tp-sl-bar .current-pos { position: absolute; top: -2px; transform: translateX(-50%); font-size: 16px; color: var(--accent); line-height: 1; }
.tp-sl-bar .bar-labels { display: flex; justify-content: space-between; font-size: 0.65em; color: var(--muted); margin-top: 1px; }
.small { font-size: 0.75em; color: var(--muted); }
.perf-tabs { display: flex; gap: 8px; margin-bottom: 15px; }
.perf-tab {
    padding: 6px 14px; background: transparent; border: 1px solid var(--border);
    border-radius: 6px; color: var(--muted); cursor: pointer;
}
.perf-tab.active { background: var(--accent); color: #000; border-color: var(--accent); }
.bot-perf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px; }
.bot-perf-card {
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 10px; padding: 15px; transition: border-color 0.2s;
}
.bot-perf-card:hover { border-color: var(--accent); }
.bpc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.bpc-main { margin-bottom: 8px; }
.bpc-pnl { font-size: 1.5em; font-weight: bold; }
.bpc-wr { color: var(--muted); font-size: 0.9em; }
.bpc-sub { display: flex; gap: 12px; color: var(--muted); font-size: 0.8em; margin-bottom: 10px; }
.bpc-chart { display: flex; align-items: flex-end; gap: 3px; height: 40px; margin-bottom: 10px; }
.bpc-chart .bar { flex: 1; border-radius: 2px 2px 0 0; min-width: 4px; }
.bpc-chart .bar.green { background: var(--green); }
.bpc-chart .bar.red { background: var(--red); }
.bpc-actions { display: flex; gap: 8px; }
.btn-detail, .btn-switch {
    flex: 1; padding: 5px; border: 1px solid var(--border); border-radius: 6px;
    background: transparent; color: var(--muted); cursor: pointer; font-size: 0.8em;
}
.btn-detail:hover { border-color: var(--accent); color: var(--accent); }
.btn-switch:hover { border-color: var(--yellow); color: var(--yellow); }
.section { margin-bottom: 30px; }
.section h2 { color: var(--accent); margin-bottom: 15px; font-size: 1.2em; }
.no-positions { color: var(--muted); padding: 20px; text-align: center; }
.no-positions.hidden { display: none; }
.refresh-indicator {
    position: fixed;
    top: 10px;
    right: 10px;
    color: var(--muted);
    font-size: 0.75em;
}
footer { text-align: center; color: var(--muted); padding: 20px; font-size: 0.85em; }
"""


def _page(page_id, title, content_html):
    """全ページ共通のHTML構造を生成して返す"""
    config = get_config()
    refresh = config.get('dashboard', {}).get('refresh_seconds', 30)
    dry_run = config.get('dry_run', False)
    mode_class = 'paper' if dry_run else 'live'
    mode_label = 'DRY RUN' if dry_run else 'LIVE'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    nav_items = [
        ('/', 'index', 'ダッシュボード'),
        ('/positions', 'positions', 'ポジション'),
        ('/trades', 'trades', '取引履歴'),
        ('/portfolios', 'portfolios', 'ポートフォリオ'),
        ('/bot-stats', 'bot-stats', 'BOT成績一覧'),
        ('/control', 'control', 'Bot管理'),
        ('/watchlist', 'watchlist', '監視リスト'),
        ('/scores', 'scores', 'スコア'),
        ('/logs', 'logs', 'ログ'),
        ('/settings', 'settings', '設定'),
    ]
    nav_html = ''
    for href, pid, label in nav_items:
        cls = ' class="active"' if pid == page_id else ''
        nav_html += f'<a href="{href}"{cls}>{label}</a>'

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - Empire Monitor</title>
<style>{DARK_CSS}</style>
</head>
<body>
<div class="header">
  <h1>Empire Monitor</h1>
  <div style="display:flex;align-items:center;gap:15px">
    <span class="mode-badge {mode_class}">{mode_label}</span>
    <div class="nav">{nav_html}</div>
  </div>
</div>
{content_html}
<footer>Empire Monitor v3.5 | {now}</footer>
{'<script>setTimeout(function(){ location.reload(); }, ' + str(refresh * 1000) + ');</script>' if page_id not in ('portfolios', 'settings', 'trades') else '<!-- no auto-reload on form pages -->'}
<div class="refresh-indicator">
    自動更新: {refresh}秒 | <span id="clock"></span>
    <script>document.getElementById('clock').textContent = new Date().toLocaleTimeString('ja-JP');</script>
</div>
</body>
</html>'''


# ========================================
# Routes
# ========================================

@app.route('/')
def index():
    """メインダッシュボード - 3層構造"""
    config = get_config()
    fg = _state.get('fear_greed', 50)

    if fg <= 25:
        fg_class = 'red'
    elif fg <= 50:
        fg_class = 'yellow'
    else:
        fg_class = 'green'

    # DB data
    db_stats = {'ohlcv_1d': 0, 'ohlcv_1h': 0, 'positions': 0, 'paper': 0}
    open_positions = []
    bot_paper_stats = {}
    recent_pnl_bars = {}
    conn = get_db()
    if conn:
        try:
            db_stats['ohlcv_1d'] = conn.execute("SELECT COUNT(*) FROM ohlcv WHERE timeframe='1d'").fetchone()[0]
            db_stats['ohlcv_1h'] = conn.execute("SELECT COUNT(*) FROM ohlcv WHERE timeframe='1h'").fetchone()[0]
            db_stats['positions'] = conn.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            # Fallback: get Fear&Greed from DB if _state has default
            if _state.get('fear_greed', 50) == 50:
                try:
                    row = conn.execute(
                        "SELECT value FROM fear_greed_history ORDER BY date DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        fg = row[0]
                        if fg <= 25:
                            fg_class = 'red'
                        elif fg <= 50:
                            fg_class = 'yellow'
                        else:
                            fg_class = 'green'
                except Exception:
                    pass
            # Fallback: get BTC price from DB if _state has default 0
            if _state.get('btc_price', 0) == 0:
                try:
                    row = conn.execute(
                        "SELECT close FROM ohlcv WHERE symbol='BTC/USDT:USDT' AND timeframe='1d' "
                        "ORDER BY timestamp DESC LIMIT 1"
                    ).fetchone()
                    if row and row[0]:
                        _state['btc_price'] = row[0]
                except Exception:
                    pass
            try:
                db_stats['paper'] = conn.execute("SELECT COUNT(*) FROM paper_signals WHERE status='open'").fetchone()[0]
            except Exception:
                pass
            # Open positions (paper + live)
            try:
                rows = conn.execute(
                    "SELECT bot_type, symbol, side, entry_price, current_price, "
                    "unrealized_pnl_pct, tp_price, sl_price, leverage, signal_time, 'paper' as source "
                    "FROM paper_signals WHERE status='open' "
                    "UNION ALL "
                    "SELECT bot_name, symbol, side, entry_price, current_price, "
                    "unrealized_pnl_pct, take_profit, stop_loss, leverage, entry_time, 'live' "
                    "FROM positions WHERE status='open' "
                    "ORDER BY 10 DESC LIMIT 30"
                ).fetchall()
                for r in rows:
                    open_positions.append({
                        'bot': r[0] or '-',
                        'symbol': (r[1] or '').replace('/USDT:USDT', ''),
                        'symbol_raw': r[1] or '',
                        'side': r[2] or '-',
                        'entry_price': r[3] or 0,
                        'current_price': r[4] or 0,
                        'pnl_pct': r[5] or 0,
                        'tp_price': r[6] or 0,
                        'sl_price': r[7] or 0,
                        'leverage': r[8] or 1,
                        'opened_at': r[9] or '',
                        'source': r[10],
                    })
            except Exception:
                pass
            # Per-bot paper stats
            try:
                rows = conn.execute(
                    "SELECT bot_type, COUNT(*), "
                    "SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN realized_pnl_pct <= 0 AND status='closed' THEN 1 ELSE 0 END), "
                    "COALESCE(SUM(realized_pnl_pct), 0) "
                    "FROM paper_signals GROUP BY bot_type"
                ).fetchall()
                for r in rows:
                    bot_paper_stats[r[0]] = {
                        'signals': r[1] or 0, 'wins': r[2] or 0,
                        'losses': r[3] or 0, 'pnl': r[4] or 0,
                    }
            except Exception:
                pass
            # Recent PnL bars per bot (last 10 closed signals)
            try:
                rows = conn.execute(
                    "SELECT bot_type, realized_pnl_pct FROM paper_signals "
                    "WHERE status='closed' AND realized_pnl_pct IS NOT NULL "
                    "ORDER BY id DESC LIMIT 100"
                ).fetchall()
                for r in rows:
                    bt = r[0]
                    if bt not in recent_pnl_bars:
                        recent_pnl_bars[bt] = []
                    if len(recent_pnl_bars[bt]) < 10:
                        recent_pnl_bars[bt].append(r[1] or 0)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            conn.close()

    # ─── 上段: ライブステータスバー ───
    total_pnl = sum(s.get('pnl', 0) for s in bot_paper_stats.values())
    pnl_class = 'green' if total_pnl >= 0 else 'red'
    pnl_str = f'{total_pnl:+.2f}%'

    live_count = 0
    paper_count = 0
    if _bot_manager:
        s = _bot_manager.get_dashboard_summary()
        live_count = s['live']
        paper_count = s['paper']

    live_bar = f'''
    <div class="live-bar">
      <div class="live-total">
        <span class="live-label">合計損益</span>
        <span class="live-pnl {pnl_class}" id="total-pnl">{pnl_str}</span>
      </div>
      <div class="live-stat">
        <span class="live-label">保有中</span>
        <span class="live-value" id="open-count">{len(open_positions)}</span>
      </div>
      <div class="live-stat">
        <span class="live-label">ペーパー決済</span>
        <span class="live-value" id="realized-today">{db_stats['paper']} 保有中</span>
      </div>
      <div class="live-stat">
        <span class="live-label">稼働Bot</span>
        <span class="live-value" id="active-bots">
          <span class="mode-dot live"></span>{live_count} ライブ
          <span class="mode-dot paper"></span>{paper_count} ペーパー
        </span>
      </div>
      <div class="live-alert hidden" id="danger-alert">
        &#9888;&#65039; <span id="alert-text"></span>
      </div>
    </div>'''

    # ─── 残高カード（30秒自動更新） ───
    live_bar += '''
    <div id="balance-card" class="live-bar" style="margin-top:4px;display:none">
      <div class="live-stat">
        <span class="live-label">総残高</span>
        <span class="live-value" id="bal-total">-</span>
      </div>
      <div class="live-stat">
        <span class="live-label">利用可能</span>
        <span class="live-value" id="bal-free">-</span>
      </div>
      <div class="live-stat">
        <span class="live-label">使用中</span>
        <span class="live-value" id="bal-used">-</span>
      </div>
      <div class="live-stat">
        <span class="live-label">含み損益</span>
        <span class="live-value" id="bal-pnl">-</span>
      </div>
      <div class="live-stat">
        <span class="live-label">取引所</span>
        <span class="live-value" id="bal-exchange">-</span>
      </div>
    </div>
    <script>
    function refreshBalance() {
      fetch('/api/balance').then(r=>r.json()).then(d=>{
        if(!d.available) return;
        var c=document.getElementById('balance-card');
        c.style.display='flex';
        document.getElementById('bal-total').textContent='$'+Number(d.total).toFixed(2);
        document.getElementById('bal-free').textContent='$'+Number(d.free).toFixed(2);
        document.getElementById('bal-used').textContent='$'+Number(d.used).toFixed(2);
        var pnl=Number(d.unrealized_pnl);
        var pnlEl=document.getElementById('bal-pnl');
        pnlEl.textContent=(pnl>=0?'+':'')+pnl.toFixed(2);
        pnlEl.style.color=pnl>=0?'var(--green)':'var(--red)';
        document.getElementById('bal-exchange').textContent=d.exchange||'';
      }).catch(()=>{});
    }
    refreshBalance();
    setInterval(refreshBalance, 30000);
    </script>'''

    # ─── イベントバナー（Bot停止・連敗等） ───
    live_bar += '''
    <div id="event-banner" style="display:none;margin-top:4px"></div>
    <script>
    function refreshEvents() {
      fetch('/api/bot_events').then(r=>r.json()).then(d=>{
        var el=document.getElementById('event-banner');
        var evts=d.events||[];
        // disabledは除外（多すぎるため）、danger/warningのみ表示
        evts=evts.filter(e=>e.severity!=='info');
        if(!evts.length){el.style.display='none';return;}
        el.style.display='block';
        var html='';
        evts.forEach(function(e){
          var bg=e.severity==='danger'?'#ff4444':'#ff8800';
          var icon=e.severity==='danger'?'&#9888;&#65039;':'&#9889;';
          html+='<div style="background:'+bg+';color:#fff;padding:6px 12px;border-radius:4px;margin-bottom:2px;font-size:13px;display:flex;align-items:center;gap:8px">';
          html+='<span>'+icon+'</span>';
          html+='<span style="font-weight:600">['+e.bot+']</span>';
          html+='<span>'+e.message+'</span>';
          if(e.timestamp){html+='<span style="margin-left:auto;opacity:0.7;font-size:11px">'+e.timestamp.slice(11,19)+'</span>';}
          html+='</div>';
        });
        el.innerHTML=html;
      }).catch(()=>{});
    }
    refreshEvents();
    setInterval(refreshEvents, 10000);
    </script>'''

    # ─── 上段直下: オープンポジション ───
    pos_rows = ''
    for p in open_positions:
        side_cls = 'green' if p['side'] == 'long' else 'red'
        side_arrow = 'ロング &#8593;' if p['side'] == 'long' else 'ショート &#8595;'
        source_cls = 'live' if p['source'] == 'live' else 'paper'
        pnl = p['pnl_pct']
        pnl_cls = 'green' if pnl >= 0 else 'red'
        pnl_str = f'{pnl:+.2f}%' if p['current_price'] else '-'
        cur_str = f'${p["current_price"]:,.6f}' if p['current_price'] else '-'

        # TP/SL progress bar
        tp = p['tp_price']
        sl = p['sl_price']
        entry = p['entry_price']
        cur = p['current_price'] or entry
        if tp and sl and tp != sl:
            total_range = tp - sl
            cur_pos_pct = max(0, min(100, (cur - sl) / total_range * 100))
            tp_sl_label = f'SL ${sl:,.4f} | TP ${tp:,.4f}'
        else:
            cur_pos_pct = 50
            tp_sl_label = '監視中'

        # Hold time
        hold_str = '-'
        if p['opened_at']:
            try:
                opened = datetime.fromisoformat(str(p['opened_at']).replace('Z', '+00:00').split('+')[0])
                delta = datetime.now() - opened
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                hold_str = f'{hours}h {mins}m' if hours > 0 else f'{mins}m'
            except Exception:
                pass

        lev_str = f'{int(p["leverage"])}x' if p['leverage'] > 1 else ''
        # Entry time display
        entry_time_str = ''
        if p['opened_at']:
            try:
                entry_time_str = str(p['opened_at'])[:16].replace('T', ' ')
            except Exception:
                pass
        pos_rows += f'''
        <tr class="position-row" onclick="window.location='/positions'" style="cursor:pointer">
          <td><span class="mode-dot {source_cls}"></span>{get_display_name(p['bot'])}</td>
          <td><strong>{p['symbol']}</strong> <span class="small">{lev_str}</span></td>
          <td class="{side_cls}">{side_arrow}</td>
          <td>${p['entry_price']:,.6f}</td>
          <td>{cur_str}</td>
          <td class="{pnl_cls}"><strong>{pnl_str}</strong></td>
          <td><div class="tp-sl-bar"><div class="sl-zone" style="width:10%"></div><div class="tp-zone" style="width:10%"></div><div class="current-pos" style="left:{cur_pos_pct:.0f}%">&#9679;</div></div><span class="small">{tp_sl_label}</span></td>
          <td><span class="small">{entry_time_str}</span><br>{hold_str}</td>
        </tr>'''

    if not pos_rows:
        pos_table_body = '<tr><td colspan="8" style="color:var(--muted);text-align:center;padding:20px">保有ポジションなし &mdash; 全Botシグナル待機中</td></tr>'
    else:
        pos_table_body = pos_rows

    positions_html = f'''
    <div class="section">
      <h2>保有ポジション</h2>
      <div class="card">
        <table class="position-table" id="positions-table">
          <tr><th>Bot</th><th>銘柄</th><th>方向</th><th>エントリー</th><th>現在値</th><th>損益</th><th>TP/SL</th><th>エントリー時刻 / 保有</th></tr>
          {pos_table_body}
        </table>
      </div>
    </div>'''

    # ─── 中段: Bot成績ダッシュボード ───
    perf_tabs = '''
    <div class="perf-tabs">
      <button class="perf-tab active" onclick="showPerf('all')">全Bot</button>
      <button class="perf-tab" onclick="showPerf('live')">ライブ</button>
      <button class="perf-tab" onclick="showPerf('paper')">ペーパー</button>
    </div>'''

    perf_cards = ''
    if _bot_manager:
        for b in _bot_manager.get_all_states():
            name = b['name']
            mode = b['mode']
            ps = bot_paper_stats.get(name, {})
            pnl = ps.get('pnl', 0)
            wins = ps.get('wins', 0)
            losses = ps.get('losses', 0)
            sigs = ps.get('signals', 0)
            wr = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            pnl_color = 'green' if pnl >= 0 else 'red'

            # Mini PnL chart bars
            bars = recent_pnl_bars.get(name, [])
            bars_html = ''
            for v in reversed(bars):
                bar_cls = 'green' if v >= 0 else 'red'
                h = min(100, max(5, abs(v) * 10))
                bars_html += f'<div class="bar {bar_cls}" style="height:{h}%"></div>'
            if not bars_html:
                bars_html = '<div style="color:var(--muted);font-size:0.75em;width:100%;text-align:center">データなし</div>'

            # Mode-specific switch button
            if mode == 'live':
                switch_btn = f"<button class=\"btn-switch\" onclick=\"event.stopPropagation();switchMode('{name}','paper')\">&#8594;ペーパー</button>"
                badge = '<span class="mode-badge live">ライブ</span>'
            elif mode == 'paper':
                switch_btn = f"<button class=\"btn-switch\" onclick=\"event.stopPropagation();if(confirm('\\u26a0\\ufe0f {name} をライブに切替えますか？'))switchMode('{name}','live')\">&#8594;ライブ</button>"
                badge = '<span class="mode-badge paper">ペーパー</span>'
            else:
                switch_btn = f"<button class=\"btn-switch\" onclick=\"event.stopPropagation();switchMode('{name}','paper')\">有効化</button>"
                badge = '<span class="mode-badge disabled">停止</span>'

            from src.core.bot_display_names import get_prefix, get_jp_name
            _prefix = get_prefix(name)
            _jp = get_jp_name(name)
            perf_cards += f'''
            <div class="bot-perf-card" data-bot="{name}" data-mode="{mode}" onclick="window.location='/control'">
              <div class="bpc-header">
                <span class="mode-dot {mode}"></span>
                <code style="color:var(--cyan);font-size:0.85em;margin-right:4px">{_prefix}</code>
                <span style="font-weight:bold;font-size:0.85em">{_jp}</span>
                {badge}
              </div>
              <div class="bpc-main">
                <div class="bpc-pnl {pnl_color}">{pnl:+.2f}%</div>
                <div class="bpc-wr">勝率 {wr:.0f}% ({wins}勝/{losses}敗)</div>
              </div>
              <div class="bpc-sub">
                <span>シグナル: {sigs}</span>
              </div>
              <div class="bpc-chart">{bars_html}</div>
              <div class="bpc-actions" onclick="event.stopPropagation()">
                <button class="btn-detail" onclick="window.location='/control'">詳細</button>
                {switch_btn}
              </div>
            </div>'''

    if not perf_cards:
        perf_cards = '<div class="card"><p style="color:var(--muted)">BotManager未初期化</p></div>'

    bot_perf_html = f'''
    <div class="section">
      <h2>Bot成績</h2>
      {perf_tabs}
      <div class="bot-perf-grid" id="bot-perf-grid">{perf_cards}</div>
    </div>'''

    # ─── 下段: 市場情報 + 激アツ + ヘルス ───
    wl = _state.get('watchlist', [])[:5]
    wl_html = ''
    for w in wl:
        sym = w.get('symbol', '').replace('/USDT:USDT', '')
        score = w.get('hot_score', 0)
        direction = w.get('direction', '-')
        sector = w.get('sector', '')
        arrow = '&#8593;' if direction == 'long' else '&#8595;' if direction == 'short' else '-'
        score_color = 'var(--green)' if score >= 80 else 'var(--yellow)' if score >= 60 else 'var(--muted)'
        wl_html += f'<tr><td>{sym}</td><td style="color:{score_color};font-weight:bold">{score}</td><td>{arrow}</td><td>{sector}</td></tr>'
    if not wl_html:
        wl_html = '<tr><td colspan="4" style="color:var(--muted)">監視銘柄なし（Tier2候補待ち）</td></tr>'

    # WebSocket状態カード
    if _ws_feed:
        _ws_stats = _ws_feed.get_stats()
        ws_status = '<span style="color:var(--green)">接続中</span>' if _ws_feed.is_connected else '<span style="color:var(--muted)">切断</span>'
        ws_card = f'''<div class="card"><h3>WebSocket</h3>
          <div class="label">状態: {ws_status}</div>
          <div class="label">銘柄数: {_ws_stats['symbols_count']}</div>
          <div class="label">受信: {_ws_stats['messages_received']:,} / 再接続: {_ws_stats['reconnects']}</div>
        </div>'''
    else:
        ws_card = '''<div class="card"><h3>WebSocket</h3>
          <div class="label">状態: <span style="color:var(--muted)">停止</span></div>
        </div>'''

    market_html = f'''
    <div class="section">
      <h2>市場概況</h2>
      <div class="grid">
        <div class="card"><h3>BTC価格</h3><div class="metric green">${_state.get('btc_price', 0):,.0f}</div></div>
        <div class="card"><h3>恐怖&amp;貪欲指数</h3><div class="metric {fg_class}">{fg}</div></div>
        <div class="card"><h3>BTCドミナンス</h3><div class="metric">{_state.get('btc_d', 0):.1f}%</div></div>
        <div class="card"><h3>レジーム</h3><div class="metric">{_state.get('regime', 'F')}</div></div>
      </div>
    </div>

    <div class="section">
      <h2>注目銘柄 Top 5</h2>
      <div class="card">
        <table><tr><th>銘柄</th><th>スコア</th><th>方向</th><th>セクター</th></tr>{wl_html}</table>
      </div>
    </div>

    <div class="section">
      <h2>システム状態</h2>
      <div class="grid">
        <div class="card"><h3>エンジン</h3>
          <div class="label">サイクル: {_state.get('cycle_count', 0)}</div>
          <div class="label">エラー: {_state.get('error_count', 0)}</div>
        </div>
        <div class="card"><h3>データ</h3>
          <div class="label">日足OHLCV: {db_stats['ohlcv_1d']:,}</div>
          <div class="label">時足OHLCV: {db_stats['ohlcv_1h']:,}</div>
        </div>
        <div class="card"><h3>ポジション</h3>
          <div class="label">保有中: {db_stats['positions']}</div>
          <div class="label">ペーパー: {db_stats['paper']}</div>
        </div>
        {ws_card}
      </div>
    </div>'''

    # ─── JS: Performance filter + live update ───
    perf_js = '''
    <script>
    function showPerf(filter) {
      document.querySelectorAll('.perf-tab').forEach(function(b){b.classList.remove('active')});
      event.target.classList.add('active');
      document.querySelectorAll('.bot-perf-card').forEach(function(c){
        if(filter==='all'||c.dataset.mode===filter) c.style.display='';
        else c.style.display='none';
      });
    }
    function switchMode(name, mode) {
      fetch('/api/bot/' + name + '/mode', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({mode:mode})
      }).then(function(r){return r.json()}).then(function(d){
        if(d.success)location.reload(); else alert('エラー: '+d.error);
      });
    }
    // Live data update (10s)
    function updateLive() {
      fetch('/api/dashboard').then(function(r){return r.json()}).then(function(d){
        var el=document.getElementById('total-pnl');
        if(el){el.textContent=(d.total_pnl>=0?'+':'')+d.total_pnl.toFixed(2)+'%';
          el.className='live-pnl '+(d.total_pnl>=0?'green':'red');}
        var oc=document.getElementById('open-count');
        if(oc)oc.textContent=d.open_count;
        var da=document.getElementById('danger-alert');
        var at=document.getElementById('alert-text');
        if(da&&d.danger_alerts&&d.danger_alerts.length>0){
          da.classList.remove('hidden');at.textContent=d.danger_alerts[0];
        } else if(da){da.classList.add('hidden');}
      }).catch(function(){});
    }
    setInterval(updateLive, 10000);
    </script>'''

    content = live_bar + positions_html + bot_perf_html + market_html + perf_js
    return _page('index', 'Dashboard', content)


@app.route('/positions')
def positions_page():
    """ポジション詳細ページ - Open + Recent Closed"""
    all_positions = []
    conn = get_db()
    if conn:
        try:
            # Paper positions
            try:
                rows = conn.execute(
                    "SELECT id, bot_type, symbol, side, entry_price, current_price, "
                    "unrealized_pnl_pct, tp_price, sl_price, leverage, signal_time, "
                    "status, realized_pnl_pct, 'paper' as source "
                    "FROM paper_signals WHERE status='open' OR "
                    "(status='closed' AND id IN (SELECT id FROM paper_signals WHERE status='closed' ORDER BY id DESC LIMIT 20)) "
                    "ORDER BY status ASC, id DESC"
                ).fetchall()
                for r in rows:
                    all_positions.append({
                        'id': r[0], 'bot': r[1] or '-',
                        'symbol': (r[2] or '').replace('/USDT:USDT', ''),
                        'symbol_raw': r[2] or '',
                        'side': r[3] or '-', 'entry_price': r[4] or 0,
                        'current_price': r[5] or 0, 'pnl_pct': r[6] or 0,
                        'tp_price': r[7] or 0, 'sl_price': r[8] or 0,
                        'leverage': r[9] or 1, 'opened_at': r[10] or '',
                        'status': r[11] or 'unknown', 'realized_pnl': r[12],
                        'source': 'paper',
                    })
            except Exception:
                pass
            # Live positions
            try:
                rows = conn.execute(
                    "SELECT id, bot_name, symbol, side, entry_price, current_price, "
                    "unrealized_pnl_pct, take_profit, stop_loss, leverage, entry_time, "
                    "status, realized_pnl_pct, 'live' as source "
                    "FROM positions WHERE status='open' OR "
                    "(status='closed' AND id IN (SELECT id FROM positions WHERE status='closed' ORDER BY id DESC LIMIT 20)) "
                    "ORDER BY status ASC, id DESC"
                ).fetchall()
                for r in rows:
                    all_positions.append({
                        'id': r[0], 'bot': r[1] or '-',
                        'symbol': (r[2] or '').replace('/USDT:USDT', ''),
                        'symbol_raw': r[2] or '',
                        'side': r[3] or '-', 'entry_price': r[4] or 0,
                        'current_price': r[5] or 0, 'pnl_pct': r[6] or 0,
                        'tp_price': r[7] or 0, 'sl_price': r[8] or 0,
                        'leverage': r[9] or 1, 'opened_at': r[10] or '',
                        'status': r[11] or 'unknown', 'realized_pnl': r[12],
                        'source': 'live',
                    })
            except Exception:
                pass
        except Exception:
            pass
        finally:
            conn.close()

    # Smart price formatter: fewer decimals for larger prices
    def fmt_price(price):
        if not price:
            return '-'
        p = float(price)
        if p >= 1000:
            return f'${p:,.2f}'
        elif p >= 1:
            return f'${p:,.4f}'
        elif p >= 0.01:
            return f'${p:.6f}'
        else:
            return f'${p:.8f}'

    # Separate open and closed
    open_pos = [p for p in all_positions if p['status'] == 'open']
    closed_pos = [p for p in all_positions if p['status'] == 'closed']

    # Build open positions table
    open_rows = ''
    for p in open_pos:
        side_cls = 'green' if p['side'] == 'long' else 'red'
        side_arrow = 'LONG' if p['side'] == 'long' else 'SHORT'
        src_cls = 'live' if p['source'] == 'live' else 'paper'
        pnl = p['pnl_pct']
        pnl_cls = 'green' if pnl >= 0 else 'red'
        pnl_str = f'{pnl:+.2f}%' if p['current_price'] else '-'
        cur_str = fmt_price(p['current_price'])
        lev_str = f'{int(p["leverage"])}x' if p['leverage'] > 1 else '1x'

        # TP/SL
        tp = p['tp_price']
        sl = p['sl_price']
        tp_str = fmt_price(tp)
        sl_str = fmt_price(sl)

        # Hold time
        hold_str = '-'
        if p['opened_at']:
            try:
                opened = datetime.fromisoformat(str(p['opened_at']).replace('Z', '+00:00').split('+')[0])
                delta = datetime.now() - opened
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                hold_str = f'{hours}h {mins}m' if hours > 0 else f'{mins}m'
            except Exception:
                pass

        # TP/SL bar with entry marker
        entry = p['entry_price']
        cur = p['current_price'] or entry
        if tp and sl and tp != sl:
            total_range = tp - sl
            cur_pos_pct = max(0, min(100, (cur - sl) / total_range * 100))
            entry_pos_pct = max(0, min(100, (entry - sl) / total_range * 100))
        else:
            cur_pos_pct = 50
            entry_pos_pct = 50

        # Entry time display
        entry_time_str = ''
        if p['opened_at']:
            try:
                entry_time_str = str(p['opened_at'])[:16].replace('T', ' ')
            except Exception:
                pass

        # TP/SL % from entry
        tp_pct_str = ''
        sl_pct_str = ''
        if tp and entry and entry > 0:
            tp_d = abs((tp - entry) / entry * 100)
            tp_pct_str = f'+{tp_d:.1f}%'
        if sl and entry and entry > 0:
            sl_d = abs((sl - entry) / entry * 100)
            sl_pct_str = f'-{sl_d:.1f}%'

        open_rows += f'''
        <tr class="position-row">
          <td><span class="mode-dot {src_cls}"></span>{p['source'].upper()}</td>
          <td><strong>{get_display_name(p['bot'])}</strong></td>
          <td><strong>{p['symbol']}</strong></td>
          <td class="{side_cls}">{side_arrow} {lev_str}</td>
          <td>{fmt_price(entry)}</td>
          <td>{cur_str}</td>
          <td class="{pnl_cls}"><strong>{pnl_str}</strong></td>
          <td style="min-width:180px">
            <div style="display:flex;justify-content:space-between;font-size:0.7em;margin-bottom:1px">
              <span class="red">{sl_str} <span style="opacity:0.7">({sl_pct_str})</span></span>
              <span class="green">{tp_str} <span style="opacity:0.7">({tp_pct_str})</span></span>
            </div>
            <div class="tp-sl-bar">
              <div class="sl-zone" style="width:10%"></div>
              <div class="tp-zone" style="width:10%"></div>
              <div class="entry-line" style="left:{entry_pos_pct:.0f}%"></div>
              <div class="current-pos" style="left:{cur_pos_pct:.0f}%">&#9679;</div>
            </div>
          </td>
          <td><span class="small">{entry_time_str}</span><br>{hold_str}</td>
          <td>
            <button class="btn-close" onclick="event.stopPropagation();manualClose({p['id']},'{p['source']}','{p['symbol_raw']}','{p['bot']}',{p['current_price']},{pnl})"
              title="手動決済">決済</button>
          </td>
        </tr>'''

    if not open_rows:
        open_rows = '<tr><td colspan="10" style="color:var(--muted);text-align:center;padding:20px">保有ポジションなし</td></tr>'

    # Build closed positions table
    closed_rows = ''
    for p in closed_pos[:20]:
        side_cls = 'green' if p['side'] == 'long' else 'red'
        side_arrow = 'LONG' if p['side'] == 'long' else 'SHORT'
        src_cls = 'live' if p['source'] == 'live' else 'paper'
        rpnl = p['realized_pnl'] or 0
        rpnl_cls = 'green' if rpnl >= 0 else 'red'
        rpnl_str = f'{rpnl:+.2f}%'
        lev_str = f'{int(p["leverage"])}x' if p['leverage'] > 1 else '1x'

        closed_rows += f'''
        <tr>
          <td><span class="mode-dot {src_cls}"></span>{p['source'].upper()}</td>
          <td>{get_display_name(p['bot'])}</td>
          <td>{p['symbol']}</td>
          <td class="{side_cls}">{side_arrow} {lev_str}</td>
          <td>{fmt_price(p['entry_price'])}</td>
          <td>{fmt_price(p['current_price'])}</td>
          <td class="{rpnl_cls}"><strong>{rpnl_str}</strong></td>
        </tr>'''

    if not closed_rows:
        closed_rows = '<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:20px">決済履歴なし</td></tr>'

    # Summary stats
    total_open = len(open_pos)
    live_open = sum(1 for p in open_pos if p['source'] == 'live')
    paper_open = sum(1 for p in open_pos if p['source'] == 'paper')
    avg_pnl = sum(p['pnl_pct'] for p in open_pos) / len(open_pos) if open_pos else 0
    avg_cls = 'green' if avg_pnl >= 0 else 'red'

    content = f'''
    <div class="grid">
      <div class="card"><h3>保有ポジション</h3><div class="metric">{total_open}</div>
        <div class="label"><span class="mode-dot live"></span>{live_open} ライブ <span class="mode-dot paper"></span>{paper_open} ペーパー</div></div>
      <div class="card"><h3>平均含み損益</h3><div class="metric {avg_cls}">{avg_pnl:+.2f}%</div></div>
      <div class="card"><h3>直近の決済</h3><div class="metric">{len(closed_pos)}</div></div>
    </div>

    <div class="section">
      <h2>保有ポジション</h2>
      <div class="card">
        <table class="position-table">
          <tr><th>モード</th><th>Bot</th><th>銘柄</th><th>方向</th><th>エントリー</th><th>現在値</th><th>損益</th><th>SL / TP 進捗</th><th>時間</th><th>操作</th></tr>
          {open_rows}
        </table>
      </div>
    </div>

    <div class="section">
      <h2>直近の決済</h2>
      <div class="card">
        <table class="position-table">
          <tr><th>モード</th><th>Bot</th><th>銘柄</th><th>方向</th><th>エントリー</th><th>決済値</th><th>確定損益</th></tr>
          {closed_rows}
        </table>
      </div>
    </div>

    <script>
    function manualClose(id, source, symbol, bot, currentPrice, pnl) {{
      var pnlStr = pnl >= 0 ? '+' + pnl.toFixed(2) + '%' : pnl.toFixed(2) + '%';
      var msg = symbol.replace('/USDT:USDT','').replace('_USDT','')
        + ' (' + bot + ')\\n\\nPnL: ' + pnlStr
        + '\\nPrice: $' + currentPrice.toFixed(6)
        + '\\n\\nこのポジションを決済しますか？';
      if (!confirm(msg)) return;
      fetch('/api/position/close', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          id: id, source: source, symbol: symbol,
          bot_name: bot, current_price: currentPrice
        }})
      }}).then(function(r){{ return r.json(); }}).then(function(d){{
        if (d.success) {{
          alert(d.message || ('決済完了! 損益: ' + (d.realized_pnl_pct || 0).toFixed(2) + '%'));
          location.reload();
        }} else {{
          alert('エラー: ' + (d.error || '不明'));
        }}
      }}).catch(function(e){{ alert('リクエスト失敗: ' + e); }});
    }}
    </script>'''

    return _page('positions', 'Positions', content)


@app.route('/bots')
def bots():
    """Bot稼働状況詳細（旧ページ → /control にリダイレクト相当の情報も表示）"""
    config = get_config()

    bot_configs = [
        ('bot_alpha', 'アルファ（極限一撃）', 'Fear&lt;10, BTC&#8804;-1%, BTC.D&#8804;-0.5%'),
        ('bot_surge', 'サージ（日常循環）', 'Fear 25-45, BTC&#8804;0%'),
        ('bot_meanrevert', '平均回帰（スタンダード）', 'Fear 50-80, MA20乖離&gt;15%'),
        ('bot_meanrevert_tight', '平均回帰（タイト）', 'Fear 50-80, MA20乖離&gt;22.5%, RSI&gt;70'),
        ('bot_meanrevert_hybrid', '平均回帰（ハイブリッド）', 'Fear 50-80, BTC long threshold'),
        ('bot_meanrevert_adaptive', '平均回帰（アダプティブ）', 'Fear 50-80, MA20乖離&gt;15%'),
        ('bot_weakshort', '弱者空売り', 'Fear 50-75, BTC&#8805;+1%'),
        ('bot_sniper', 'スナイパー（狙撃）', 'Fear&lt;30, BTC&#8804;-3%'),
        ('bot_scalp', 'スキャルピング', 'BB+RSI常時'),
    ]

    rows = ''
    for key, name, condition in bot_configs:
        bc = config.get(key, {})
        leverage = bc.get('leverage', '-')
        tp = bc.get('take_profit_pct', '-')
        sl = bc.get('stop_loss_pct', '-')
        rows += f'<tr><td><strong>{name}</strong></td><td>{condition}</td><td>{leverage}x</td><td>+{tp}%</td><td>-{sl}%</td></tr>'

    # Paper signals history
    paper_html = ''
    conn = get_db()
    if conn:
        try:
            papers = conn.execute(
                "SELECT bot_type, symbol, side, entry_price, realized_pnl_pct, status, exit_reason "
                "FROM paper_signals ORDER BY id DESC LIMIT 20"
            ).fetchall()
            for p in papers:
                pnl = p[4] or 0
                pnl_color = 'var(--green)' if pnl > 0 else 'var(--red)' if pnl < 0 else 'var(--muted)'
                sym = (p[1] or '').replace('/USDT:USDT', '')
                paper_html += f'<tr><td>{get_display_name(p[0])}</td><td>{sym}</td><td>{p[2]}</td><td>${p[3]:,.6f}</td><td style="color:{pnl_color};font-weight:bold">{pnl:+.2f}%</td><td>{p[5]}</td><td>{p[6] or "-"}</td></tr>'
        except Exception:
            pass
        finally:
            conn.close()

    if not paper_html:
        paper_html = '<tr><td colspan="7" style="color:var(--muted)">シグナル履歴なし</td></tr>'

    content = f'''
    <h2 style="color:var(--accent);margin-bottom:15px">Bot設定一覧</h2>
    <div class="card">
      <table>
        <tr><th>Bot</th><th>発火条件</th><th>倍率</th><th>TP</th><th>SL</th></tr>
        {rows}
      </table>
    </div>

    <h2 style="color:var(--accent);margin:20px 0 15px">直近シグナル履歴</h2>
    <div class="card">
      <table>
        <tr><th>Bot</th><th>銘柄</th><th>方向</th><th>価格</th><th>損益</th><th>状態</th><th>理由</th></tr>
        {paper_html}
      </table>
    </div>'''
    return _page('bots', 'Bots', content)


@app.route('/watchlist')
def watchlist():
    """激アツ監視リスト"""
    wl = _state.get('watchlist', [])

    cards = ''
    for w in wl:
        sym = w.get('symbol', '').replace('/USDT:USDT', '')
        score = w.get('hot_score', 0)
        direction = w.get('direction', '-')
        price = w.get('price', 0)
        sector = w.get('sector', '')

        if score >= 80:
            score_color = 'var(--green)'
            fill_color = 'var(--green)'
        elif score >= 60:
            score_color = 'var(--yellow)'
            fill_color = 'var(--yellow)'
        else:
            score_color = 'var(--muted)'
            fill_color = 'var(--gray)'

        arrow = '&#8593; LONG' if direction == 'long' else '&#8595; SHORT' if direction == 'short' else '-'
        arrow_color = 'var(--green)' if direction == 'long' else 'var(--red)'

        tf_html = ''
        tf_data = w.get('tf_analysis', {})
        for tf in ['1h', '4h', '1d']:
            a = tf_data.get(tf, {})
            tf_html += f'<tr><td>{tf}</td><td>{a.get("rsi", "-")}</td><td>{a.get("bb_pos", "-")}</td><td>{a.get("ema_cross", "-")}</td><td>{a.get("vol_ratio", "-")}x</td></tr>'

        cards += f'''
        <div class="bot-card" style="margin-bottom:15px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <h3 style="margin:0">{sym} <span style="color:var(--muted);font-size:0.8em">[{sector}]</span></h3>
            <span style="color:{score_color};font-size:1.5em;font-weight:700">{score}</span>
          </div>
          <div style="display:flex;gap:20px;margin-bottom:10px">
            <span>${price:,.6f}</span>
            <span style="color:{arrow_color}">{arrow}</span>
          </div>
          <div class="score-bar" style="margin-bottom:10px">
            <div class="score-bar-fill" style="width:{score}%;background:{fill_color}"></div>
          </div>
          <table style="font-size:0.85em">
            <tr><th>TF</th><th>RSI</th><th>BB</th><th>EMA</th><th>Vol</th></tr>
            {tf_html}
          </table>
        </div>'''

    if not cards:
        cards = '<div class="card"><p style="color:var(--muted)">監視銘柄なし。Tier2候補待ち。</p></div>'

    content = f'''
    <h2 style="color:var(--accent);margin-bottom:15px">注目シグナル監視リスト ({len(wl)}銘柄)</h2>
    {cards}'''
    return _page('watchlist', 'Watchlist', content)


@app.route('/scores')
def scores():
    """スコアリング詳細"""
    t2_html = ''
    conn = get_db()
    if conn:
        try:
            alerts = conn.execute(
                "SELECT symbol, alert_price, tier1_score, tier2_score, regime, fear_greed, alert_time "
                "FROM alert_log ORDER BY id DESC LIMIT 30"
            ).fetchall()
            for a in alerts:
                sym = (a[0] or '').replace('/USDT:USDT', '')
                total = (a[2] or 0) + (a[3] or 0)
                t2_html += f'<tr><td>{sym}</td><td>${a[1]:,.6f}</td><td>{a[2]:.0f}</td><td>{a[3]:.0f}</td><td style="font-weight:bold">{total:.0f}</td><td>{a[4]}</td><td>{a[5]}</td><td>{a[6][:16] if a[6] else "-"}</td></tr>'
        except Exception:
            pass
        finally:
            conn.close()

    if not t2_html:
        t2_html = '<tr><td colspan="8" style="color:var(--muted)">データなし</td></tr>'

    content = f'''
    <h2 style="color:var(--accent);margin-bottom:15px">スコアリング詳細</h2>
    <div class="card">
      <h3>直近アラートログ (Tier1 + Tier2 スコア)</h3>
      <table>
        <tr><th>銘柄</th><th>価格</th><th>T1</th><th>T2</th><th>合計</th><th>パターン</th><th>恐怖指数</th><th>時刻</th></tr>
        {t2_html}
      </table>
    </div>

    <div class="card" style="margin-top:15px">
      <h3>スコアリングフロー</h3>
      <p style="color:var(--muted);line-height:1.6">870銘柄 &#8594; <strong style="color:var(--text)">Tier1</strong> (L02 聖域 + L03 出来高 + L09 ボラ + L17 相関 + Alpha) &#8594; <strong style="color:var(--text)">Tier2</strong> (L08 FR + L10 板 + L13 清算) &#8594; <strong style="color:var(--accent)">注目スコア</strong> (Tier2 + マルチTFテクニカル)</p>
    </div>'''
    return _page('scores', 'Scores', content)


@app.route('/logs')
def logs():
    """直近ログ"""
    log_path = PROJECT_ROOT / "logs" / "empire_monitor.log"
    log_lines = []
    if log_path.exists():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                log_lines = f.readlines()[-100:]
        except Exception:
            pass

    log_html = ''
    for line in reversed(log_lines):
        escaped = line.rstrip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        log_html += f'<div style="font-family:monospace;font-size:0.8em;padding:3px 0;border-bottom:1px solid var(--border)">{escaped}</div>'
    if not log_html:
        log_html = '<p style="color:var(--muted)">No logs</p>'

    # Order log from DB
    order_log_html = ''
    conn = get_db()
    if conn:
        try:
            rows = conn.execute(
                "SELECT timestamp, bot_name, symbol, order_type, side, amount, price, "
                "exchange_order_id, status, error_message "
                "FROM order_log ORDER BY id DESC LIMIT 50"
            ).fetchall()
            for r in rows:
                ts = (r[0] or '')[:19]
                status_color = 'var(--green)' if r[8] == 'filled' else 'var(--red)' if r[8] in ('failed', 'error') else 'var(--yellow)'
                price_str = f'${r[6]:,.6f}' if r[6] else '-'
                err = f' <span style="color:var(--red)">{r[9]}</span>' if r[9] else ''
                order_log_html += f'<tr><td>{ts}</td><td>{get_display_name(r[1])}</td><td>{(r[2] or "").replace("/USDT:USDT","")}</td><td>{r[3]}</td><td>{r[4]}</td><td>{r[5]:.4f}</td><td>{price_str}</td><td style="color:{status_color};font-weight:bold">{r[8]}</td><td style="font-size:0.75em">{r[7] or "-"}{err}</td></tr>'
        except Exception:
            pass
        finally:
            conn.close()

    if not order_log_html:
        order_log_html = '<tr><td colspan="9" style="color:var(--muted)">注文履歴なし</td></tr>'

    content = f'''
    <h2 style="color:var(--accent);margin-bottom:15px">注文ログ（ライブ取引）</h2>
    <div class="card" style="margin-bottom:20px">
      <table style="font-size:0.85em">
        <tr><th>時刻</th><th>Bot</th><th>銘柄</th><th>種別</th><th>方向</th><th>数量</th><th>価格</th><th>状態</th><th>注文ID</th></tr>
        {order_log_html}
      </table>
    </div>

    <h2 style="color:var(--accent);margin-bottom:15px">システムログ（直近100行）</h2>
    <div class="card" style="max-height:600px;overflow-y:auto">
      {log_html}
    </div>'''
    return _page('logs', 'Logs', content)


@app.route('/bot-stats')
def bot_stats_page():
    """BOT成績一覧 — スプレッドシート形式、動的ソート対応"""
    content = '''
    <div class="section">
      <h2>BOT成績一覧</h2>
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <select id="bs-mode" onchange="loadBotStats()" style="padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px">
          <option value="">全モード</option>
          <option value="paper" selected>ペーパー</option>
          <option value="live">ライブ</option>
        </select>
        <input type="date" id="bs-from" onchange="loadBotStats()" style="padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px">
        <input type="date" id="bs-to" onchange="loadBotStats()" style="padding:4px 8px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:4px">
      </div>
      <div style="overflow-x:auto">
        <table id="bs-table" style="width:100%;border-collapse:collapse;font-size:0.82rem">
          <thead>
            <tr style="background:rgba(59,130,246,0.08);cursor:pointer">
              <th onclick="sortBsTable(0)" style="padding:8px;text-align:left;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">略称</th>
              <th onclick="sortBsTable(1)" style="padding:8px;text-align:left;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">BOT名</th>
              <th onclick="sortBsTable(2)" style="padding:8px;text-align:center;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">Mode</th>
              <th onclick="sortBsTable(3,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">トレード数</th>
              <th onclick="sortBsTable(4,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">勝ち</th>
              <th onclick="sortBsTable(5,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">負け</th>
              <th onclick="sortBsTable(6,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">勝率%</th>
              <th onclick="sortBsTable(7,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">平均勝ち%</th>
              <th onclick="sortBsTable(8,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">平均負け%</th>
              <th onclick="sortBsTable(9,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">PF</th>
              <th onclick="sortBsTable(10,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">合計PnL%</th>
              <th onclick="sortBsTable(11,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">合計PnL$</th>
              <th onclick="sortBsTable(12,'num')" style="padding:8px;text-align:right;color:var(--accent);border-bottom:2px solid rgba(59,130,246,0.2)">MDD%</th>
            </tr>
          </thead>
          <tbody id="bs-body"></tbody>
        </table>
      </div>
      <div id="bs-summary" style="margin-top:12px;color:var(--muted);font-size:0.8rem"></div>
    </div>

    <script>
    var bsSortCol=-1, bsSortAsc=true;

    function loadBotStats(){
      var mode=document.getElementById('bs-mode').value;
      var from=document.getElementById('bs-from').value;
      var to=document.getElementById('bs-to').value;
      var url='/api/bot-stats-table?';
      if(mode) url+='mode='+mode+'&';
      if(from) url+='date_from='+from+'&';
      if(to) url+='date_to='+to+'&';
      fetch(url).then(r=>r.json()).then(function(d){
        var tb=document.getElementById('bs-body');
        var html='';
        d.bots.forEach(function(b){
          var pnlColor=b.total_pnl_pct>=0?'var(--green)':'var(--red)';
          var wrColor=b.win_rate>=50?'var(--green)':b.win_rate>=35?'var(--orange)':'var(--red)';
          var pfColor=b.profit_factor>=1.5?'var(--green)':b.profit_factor>=1.0?'var(--text)':'var(--red)';
          html+='<tr style="border-bottom:1px solid var(--border)">';
          html+='<td style="padding:6px 8px"><code style="color:var(--cyan)">'+b.prefix+'</code></td>';
          html+='<td style="padding:6px 8px;font-weight:500">'+b.jp_name+'</td>';
          html+='<td style="padding:6px 8px;text-align:center"><span class="mode-badge '+b.mode+'">'+b.mode+'</span></td>';
          html+='<td style="padding:6px 8px;text-align:right">'+b.total_trades+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:var(--green)">'+b.wins+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:var(--red)">'+b.losses+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:'+wrColor+';font-weight:600">'+b.win_rate.toFixed(1)+'%</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:var(--green)">'+(b.avg_win_pct?b.avg_win_pct.toFixed(2)+'%':'-')+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:var(--red)">'+(b.avg_loss_pct?b.avg_loss_pct.toFixed(2)+'%':'-')+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:'+pfColor+';font-weight:600">'+b.profit_factor.toFixed(2)+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:'+pnlColor+';font-weight:700">'+(b.total_pnl_pct>=0?'+':'')+b.total_pnl_pct.toFixed(2)+'%</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:'+pnlColor+'">'+(b.total_pnl_amount>=0?'+$':'-$')+Math.abs(b.total_pnl_amount).toFixed(2)+'</td>';
          html+='<td style="padding:6px 8px;text-align:right;color:var(--red)">'+(b.max_drawdown_pct?b.max_drawdown_pct.toFixed(2)+'%':'-')+'</td>';
          html+='</tr>';
        });
        tb.innerHTML=html;
        document.getElementById('bs-summary').textContent=
          'BOT数: '+d.bots.length+' | 合計トレード: '+d.total_trades+' | 合計PnL: '+d.total_pnl.toFixed(2)+'%';
      });
    }

    function sortBsTable(col, type){
      var table=document.getElementById('bs-table');
      var rows=Array.from(table.tBodies[0].rows);
      if(bsSortCol===col){bsSortAsc=!bsSortAsc;}else{bsSortCol=col;bsSortAsc=true;}
      rows.sort(function(a,b){
        var va=a.cells[col].textContent.replace(/[%$+,]/g,'').trim();
        var vb=b.cells[col].textContent.replace(/[%$+,]/g,'').trim();
        if(type==='num'){va=parseFloat(va)||0;vb=parseFloat(vb)||0;}
        if(va<vb)return bsSortAsc?-1:1;
        if(va>vb)return bsSortAsc?1:-1;
        return 0;
      });
      var tb=table.tBodies[0];
      rows.forEach(function(r){tb.appendChild(r);});
      // Update header arrows
      Array.from(table.tHead.rows[0].cells).forEach(function(th,i){
        th.textContent=th.textContent.replace(/ [▲▼]/,'');
        if(i===col) th.textContent+=bsSortAsc?' ▲':' ▼';
      });
    }

    loadBotStats();
    </script>'''
    return _page('bot-stats', 'BOT成績一覧', content)


@app.route('/control')
def control():
    """Bot制御パネル"""
    if _bot_manager:
        summary = _bot_manager.get_dashboard_summary()
        bot_list = summary.get('bots', [])
    else:
        summary = {'total_bots': 0, 'live': 0, 'paper': 0, 'disabled': 0}
        bot_list = []

    # Paper signal stats per bot from DB
    bot_paper_stats = {}
    conn = get_db()
    if conn:
        try:
            rows = conn.execute(
                "SELECT bot_type, COUNT(*) as cnt, "
                "SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN realized_pnl_pct <= 0 AND status='closed' THEN 1 ELSE 0 END) as losses, "
                "COALESCE(SUM(realized_pnl_pct), 0) as total_pnl "
                "FROM paper_signals GROUP BY bot_type"
            ).fetchall()
            for r in rows:
                bot_paper_stats[r[0]] = {
                    'signals': r[1], 'wins': r[2] or 0,
                    'losses': r[3] or 0, 'pnl': r[4] or 0,
                }
        except Exception:
            pass
        finally:
            conn.close()

    # Summary cards
    summary_html = f'''
    <div class="grid">
      <div class="card"><h3>Bot合計</h3><div class="metric">{summary['total_bots']}</div></div>
      <div class="card"><h3>ライブ</h3><div class="metric red">{summary['live']}</div></div>
      <div class="card"><h3>ペーパー</h3><div class="metric green">{summary['paper']}</div></div>
      <div class="card"><h3>停止中</h3><div class="metric" style="color:var(--gray)">{summary['disabled']}</div></div>
    </div>'''

    # Filter bar
    filter_html = f'''
    <div class="filter-bar">
      <div class="filter-group">
        <span class="filter-label">絞込:</span>
        <button class="filter-btn active" data-filter="all" onclick="filterBots('all')">全て</button>
        <button class="filter-btn" data-filter="live" onclick="filterBots('live')">ライブ</button>
        <button class="filter-btn" data-filter="paper" onclick="filterBots('paper')">ペーパー</button>
        <button class="filter-btn" data-filter="disabled" onclick="filterBots('disabled')">停止</button>
      </div>
      <div class="filter-group">
        <span class="filter-label">並替:</span>
        <select class="sort-select" onchange="sortBots(this.value)">
          <option value="name">Bot名</option>
          <option value="pnl-desc">損益 &#8595;</option>
          <option value="pnl-asc">損益 &#8593;</option>
          <option value="signals-desc">シグナル数 &#8595;</option>
          <option value="winrate-desc">勝率 &#8595;</option>
          <option value="status">状態</option>
        </select>
      </div>
      <div class="filter-group">
        <input class="search-input" type="text" placeholder="Bot検索..." oninput="searchBots(this.value)">
      </div>
      <div class="filter-group">
        <span class="filter-label" id="bot-count">{len(bot_list)} / {len(bot_list)}</span>
      </div>
    </div>'''

    # Bot cards with data attributes
    bot_cards = ''
    for b in bot_list:
        name = b['name']
        mode = b['mode']
        running = b['running']
        signals = b['signal_count']
        errors = b['error_count']

        ps = bot_paper_stats.get(name, {})
        pnl = ps.get('pnl', 0)
        wins = ps.get('wins', 0)
        losses = ps.get('losses', 0)
        total_sigs = ps.get('signals', 0)
        winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        dot = 'green' if running else 'gray'

        if mode == 'live':
            badge = '<span class="mode-badge live">LIVE</span>'
        elif mode == 'paper':
            badge = '<span class="mode-badge paper">PAPER</span>'
        else:
            badge = '<span class="mode-badge disabled">OFF</span>'

        paper_cls = 'active-paper' if mode == 'paper' else ''
        live_cls = 'active-live' if mode == 'live' else ''
        off_cls = 'active-disabled' if mode == 'disabled' else ''

        pnl_color = 'var(--green)' if pnl > 0 else 'var(--red)' if pnl < 0 else 'var(--muted)'
        pnl_str = f'{pnl:+.2f}%' if pnl != 0 else '0.00%'

        bot_cards += f'''
        <div class="bot-card" data-bot="{name}" data-mode="{mode}"
             data-pnl="{pnl:.2f}" data-signals="{total_sigs}" data-winrate="{winrate:.1f}"
             onclick="openOverlay('{name}')">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span><span class="status-dot {dot}"></span><strong>{get_display_name(name)}</strong></span>
            {badge}
          </div>
          <div class="label">シグナル: {total_sigs} | 勝率: {winrate:.0f}% | <span style="color:{pnl_color}">{pnl_str}</span></div>
          <div class="label">エラー: {errors}</div>
          <div class="bot-controls" onclick="event.stopPropagation()">
            <button class="mode-btn {paper_cls}" onclick="switchMode('{name}','paper')">ペーパー</button>
            <button class="mode-btn {live_cls}" onclick="if(confirm('\\u26a0\\ufe0f {get_display_name(name)} をリアル口座で稼働させます。よろしいですか？'))switchMode('{name}','live')">ライブ</button>
            <button class="mode-btn {off_cls}" onclick="switchMode('{name}','disabled')">停止</button>
          </div>
        </div>'''

    if not bot_cards:
        bot_cards = '<div class="card"><p style="color:var(--muted)">BotManager未初期化。main.pyで起動してください。</p></div>'

    # Overlay HTML
    overlay_html = '''
    <div id="overlay" class="overlay hidden" onclick="closeOverlay(event)">
      <div class="overlay-content" onclick="event.stopPropagation()">
        <div class="overlay-header">
          <h2 id="overlay-title">Bot</h2>
          <div class="overlay-controls">
            <div id="overlay-mode-toggle" style="display:flex;gap:8px">
              <button class="mode-btn" data-mode="paper" onclick="switchModeFromOverlay(\'paper\')">ペーパー</button>
              <button class="mode-btn" data-mode="live" onclick="switchModeFromOverlay(\'live\')">ライブ</button>
              <button class="mode-btn" data-mode="disabled" onclick="switchModeFromOverlay(\'disabled\')">停止</button>
            </div>
            <button class="close-btn" onclick="closeOverlay()">&times;</button>
          </div>
        </div>
        <div class="overlay-body">
          <div class="perf-grid" id="overlay-stats">
            <div class="perf-card"><div class="perf-label">損益</div><div class="perf-value" id="ov-pnl">---</div></div>
            <div class="perf-card"><div class="perf-label">勝率</div><div class="perf-value" id="ov-winrate">---</div></div>
            <div class="perf-card"><div class="perf-label">シグナル</div><div class="perf-value" id="ov-signals">---</div></div>
            <div class="perf-card"><div class="perf-label">勝 / 敗</div><div class="perf-value" id="ov-wl">---</div></div>
            <div class="perf-card"><div class="perf-label">エラー</div><div class="perf-value" id="ov-errors">---</div></div>
            <div class="perf-card"><div class="perf-label">サイクル</div><div class="perf-value" id="ov-cycles">---</div></div>
          </div>
          <div class="signal-history">
            <h3>直近シグナル</h3>
            <table id="ov-signals-table">
              <tr><th>銘柄</th><th>方向</th><th>価格</th><th>損益</th><th>状態</th><th>理由</th></tr>
            </table>
          </div>
        </div>
      </div>
    </div>'''

    # Generate JS bot display name mapping for overlay
    import json as _json
    from src.core.bot_display_names import BOT_DISPLAY_NAMES
    _ctrl_bot_names_js = _json.dumps(BOT_DISPLAY_NAMES, ensure_ascii=False)

    content = f'''
    <h2 style="color:var(--accent);margin-bottom:15px">Bot操作パネル</h2>
    {summary_html}
    {filter_html}
    <div class="bot-grid">{bot_cards}</div>
    {overlay_html}
    <script>window._botDisplayNames={_ctrl_bot_names_js};</script>
    <script>
    // === Mode Switch ===
    function switchMode(name, mode) {{
      fetch('/api/bot/' + name + '/mode', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{mode: mode}})
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d.success) location.reload();
        else alert('エラー: ' + d.error);
      }})
      .catch(function(e) {{ alert('リクエスト失敗: ' + e); }});
    }}

    // === Filter ===
    function filterBots(mode) {{
      document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
      document.querySelector('[data-filter="' + mode + '"]').classList.add('active');
      document.querySelectorAll('.bot-card').forEach(function(card) {{
        if (mode === 'all' || card.dataset.mode === mode) {{
          card.style.display = '';
        }} else {{
          card.style.display = 'none';
        }}
      }});
      updateCount();
    }}

    // === Sort ===
    function sortBots(criteria) {{
      var grid = document.querySelector('.bot-grid');
      var cards = Array.from(grid.querySelectorAll('.bot-card'));
      cards.sort(function(a, b) {{
        switch(criteria) {{
          case 'name': return a.dataset.bot.localeCompare(b.dataset.bot);
          case 'pnl-desc': return parseFloat(b.dataset.pnl) - parseFloat(a.dataset.pnl);
          case 'pnl-asc': return parseFloat(a.dataset.pnl) - parseFloat(b.dataset.pnl);
          case 'signals-desc': return parseInt(b.dataset.signals) - parseInt(a.dataset.signals);
          case 'winrate-desc': return parseFloat(b.dataset.winrate) - parseFloat(a.dataset.winrate);
          case 'status':
            var order = {{live:0, paper:1, disabled:2}};
            return (order[a.dataset.mode]||9) - (order[b.dataset.mode]||9);
          default: return 0;
        }}
      }});
      cards.forEach(function(card) {{ grid.appendChild(card); }});
    }}

    // === Search ===
    function searchBots(query) {{
      var q = query.toLowerCase();
      document.querySelectorAll('.bot-card').forEach(function(card) {{
        card.style.display = card.dataset.bot.toLowerCase().includes(q) ? '' : 'none';
      }});
      updateCount();
    }}

    // === Count ===
    function updateCount() {{
      var visible = document.querySelectorAll('.bot-card:not([style*="display: none"])').length;
      var total = document.querySelectorAll('.bot-card').length;
      var counter = document.getElementById('bot-count');
      if (counter) counter.textContent = visible + ' / ' + total;
    }}

    // === Overlay ===
    var currentOverlayBot = null;

    function openOverlay(botName) {{
      currentOverlayBot = botName;
      document.getElementById('overlay').classList.remove('hidden');
      document.getElementById('overlay-title').textContent = 'Bot: ' + (window._botDisplayNames && window._botDisplayNames[botName] || botName);

      fetch('/api/bot/' + botName + '/state')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          var stats = data.stats || {{}};
          var pnl = stats.pnl_total || 0;
          var el = document.getElementById('ov-pnl');
          el.textContent = pnl.toFixed(2) + '%';
          el.className = 'perf-value ' + (pnl >= 0 ? 'green' : 'red');

          var wr = stats.win_count + stats.loss_count > 0
            ? ((stats.win_count / (stats.win_count + stats.loss_count)) * 100).toFixed(1) : '---';
          document.getElementById('ov-winrate').textContent = wr + (wr !== '---' ? '%' : '');
          document.getElementById('ov-signals').textContent = data.signal_count || 0;
          document.getElementById('ov-wl').textContent = (stats.win_count||0) + '勝 / ' + (stats.loss_count||0) + '敗';
          document.getElementById('ov-errors').textContent = data.error_count || 0;
          document.getElementById('ov-cycles').textContent = data.cycle_count || 0;

          // Mode toggle highlight
          document.querySelectorAll('#overlay-mode-toggle .mode-btn').forEach(function(btn) {{
            btn.classList.remove('active-live', 'active-paper', 'active-disabled');
            if (btn.dataset.mode === data.mode) {{
              btn.classList.add('active-' + data.mode);
            }}
          }});

          // Signal history
          var table = document.getElementById('ov-signals-table');
          while (table.rows.length > 1) table.deleteRow(1);
          (data.recent_signals || []).forEach(function(s) {{
            var row = table.insertRow();
            var pcolor = (s.pnl||0) >= 0 ? 'green' : 'red';
            row.innerHTML = '<td>' + (s.symbol||'').replace('/USDT:USDT','') + '</td>'
              + '<td>' + (s.side||'-') + '</td>'
              + '<td>$' + (s.entry_price||0).toFixed(6) + '</td>'
              + '<td class="' + pcolor + '">' + ((s.pnl||0).toFixed(2)) + '%</td>'
              + '<td>' + (s.status||'-') + '</td>'
              + '<td>' + (s.exit_reason||'-') + '</td>';
          }});
        }});
    }}

    function closeOverlay(event) {{
      if (!event || event.target.id === 'overlay') {{
        document.getElementById('overlay').classList.add('hidden');
        currentOverlayBot = null;
      }}
    }}

    function switchModeFromOverlay(newMode) {{
      if (!currentOverlayBot) return;
      if (newMode === 'live') {{
        if (!confirm('\\u26a0\\ufe0f ' + currentOverlayBot + ' をリアル口座で稼働させます。よろしいですか？')) return;
      }}
      fetch('/api/bot/' + currentOverlayBot + '/mode', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{mode: newMode}})
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data.success) {{
          openOverlay(currentOverlayBot);
          setTimeout(function() {{ location.reload(); }}, 500);
        }}
      }});
    }}

    // ESC to close overlay
    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') closeOverlay();
    }});
    </script>'''
    return _page('control', 'Control', content)


# ========================================
# JSON APIs
# ========================================

@app.route('/api/status')
def api_status():
    """JSON API: システム状態"""
    return jsonify({
        'btc_price': _state.get('btc_price', 0),
        'fear_greed': _state.get('fear_greed', 50),
        'btc_d': _state.get('btc_d', 0),
        'regime': _state.get('regime', 'F'),
        'cycle_count': _state.get('cycle_count', 0),
        'error_count': _state.get('error_count', 0),
        'watchlist_count': len(_state.get('watchlist', [])),
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/watchlist')
def api_watchlist():
    """JSON API: 監視リスト"""
    return jsonify(_state.get('watchlist', []))


@app.route('/api/bot/<name>/state')
def api_bot_state(name):
    """JSON API: 指定Botの状態（stats + recent_signals付き）"""
    if not _bot_manager:
        return jsonify({'error': 'BotManager not initialized'}), 503
    state = _bot_manager.get_bot_state(name)
    if state is None:
        return jsonify({'error': f'Bot "{name}" not found'}), 404

    # Paper + Live signal stats from DB
    stats = {'pnl_total': 0, 'win_count': 0, 'loss_count': 0, 'signals_generated': 0}
    recent_signals = []
    conn = get_db()
    if conn:
        try:
            # Paper signals stats
            row = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN realized_pnl_pct <= 0 AND status='closed' THEN 1 ELSE 0 END), "
                "COALESCE(SUM(realized_pnl_pct), 0) "
                "FROM paper_signals WHERE bot_type=?", (name,)
            ).fetchone()
            if row:
                stats = {
                    'signals_generated': row[0] or 0,
                    'win_count': row[1] or 0,
                    'loss_count': row[2] or 0,
                    'pnl_total': row[3] or 0,
                }
            # Add live positions stats
            try:
                lrow = conn.execute(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN realized_pnl_pct <= 0 AND status='closed' THEN 1 ELSE 0 END), "
                    "COALESCE(SUM(realized_pnl_pct), 0) "
                    "FROM positions WHERE bot_name=?", (name,)
                ).fetchone()
                if lrow and lrow[0]:
                    stats['signals_generated'] += lrow[0] or 0
                    stats['win_count'] += lrow[1] or 0
                    stats['loss_count'] += lrow[2] or 0
                    stats['pnl_total'] += lrow[3] or 0
            except Exception:
                pass
            # Recent paper signals
            rows = conn.execute(
                "SELECT symbol, side, entry_price, realized_pnl_pct, status, exit_reason "
                "FROM paper_signals WHERE bot_type=? ORDER BY id DESC LIMIT 20", (name,)
            ).fetchall()
            for r in rows:
                recent_signals.append({
                    'symbol': r[0], 'side': r[1], 'entry_price': r[2],
                    'pnl': r[3], 'status': r[4], 'exit_reason': r[5],
                })
            # Recent live positions
            try:
                lrows = conn.execute(
                    "SELECT symbol, side, entry_price, realized_pnl_pct, status, notes "
                    "FROM positions WHERE bot_name=? ORDER BY id DESC LIMIT 10", (name,)
                ).fetchall()
                for r in lrows:
                    recent_signals.append({
                        'symbol': r[0], 'side': r[1], 'entry_price': r[2],
                        'pnl': r[3], 'status': r[4], 'exit_reason': r[5] or 'LIVE',
                    })
            except Exception:
                pass
        except Exception:
            pass
        finally:
            conn.close()

    state['stats'] = stats
    state['recent_signals'] = recent_signals
    return jsonify(state)


@app.route('/api/bot/<name>/mode', methods=['POST'])
def api_bot_mode(name):
    """JSON API: Botモード切替"""
    if not _bot_manager:
        return jsonify({'error': 'BotManager not initialized'}), 503
    data = request.get_json(silent=True) or {}
    new_mode = data.get('mode', '')
    if new_mode not in ('live', 'paper', 'disabled'):
        return jsonify({'error': f'Invalid mode: {new_mode}'}), 400
    ok = _bot_manager.switch_bot_mode(name, new_mode)
    if not ok:
        return jsonify({'error': f'Bot "{name}" not found'}), 404
    return jsonify({'name': name, 'mode': new_mode, 'success': True})


@app.route('/api/bot-stats-table')
def api_bot_stats_table():
    """BOT成績一覧テーブル用API"""
    from src.core.trade_recorder import TradeRecorder
    from src.core.bot_display_names import get_prefix, get_jp_name
    from src.data.database import HistoricalDB

    mode = request.args.get('mode')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    db = HistoricalDB()
    tr = TradeRecorder(db)

    # 全BOT名を取得
    bot_names = set()
    conn = db._get_conn()
    rows = conn.execute("SELECT DISTINCT bot_name FROM trade_records").fetchall()
    for r in rows:
        bot_names.add(r[0])
    if _bot_manager:
        for b in _bot_manager.get_all_states():
            bot_names.add(b['name'])
    conn.close()

    bots = []
    total_trades = 0
    total_pnl = 0

    for name in sorted(bot_names):
        stats = tr.get_performance_stats(
            mode=mode, bot_name=name,
            date_from=date_from, date_to=date_to)

        if stats['total_trades'] == 0 and not _bot_manager:
            continue

        bot_mode = 'unknown'
        if _bot_manager:
            state = _bot_manager.get_bot_state(name)
            if state:
                bot_mode = state.get('mode', 'unknown')

        bots.append({
            'name': name,
            'prefix': get_prefix(name),
            'jp_name': get_jp_name(name),
            'mode': bot_mode,
            'total_trades': stats['total_trades'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': stats['win_rate'],
            'avg_win_pct': stats['avg_win_pct'],
            'avg_loss_pct': stats['avg_loss_pct'],
            'profit_factor': stats['profit_factor'],
            'total_pnl_pct': stats['total_pnl_pct'],
            'total_pnl_amount': stats['total_pnl_amount'],
            'max_drawdown_pct': stats['max_drawdown_pct'],
        })
        total_trades += stats['total_trades']
        total_pnl += stats['total_pnl_pct']

    return jsonify({
        'bots': bots,
        'total_trades': total_trades,
        'total_pnl': round(total_pnl, 2),
    })


@app.route('/api/bots')
def api_bots():
    """JSON API: 全Bot状態"""
    if _bot_manager:
        return jsonify(_bot_manager.get_dashboard_summary())
    # BotManager未初期化時: settings.yamlからBot一覧をフォールバック
    config = get_config()
    bots = config.get('bots', {})
    fallback = {}
    for name, cfg in bots.items():
        fallback[name] = {
            'display_name': get_display_name(name),
            'mode': (cfg or {}).get('mode', 'paper'),
            'status': 'unknown',
            'stats': {},
        }
    return jsonify(fallback)


@app.route('/api/positions')
def api_positions():
    """JSON API: オープンポジション"""
    positions = []
    conn = get_db()
    if conn:
        try:
            rows = conn.execute(
                "SELECT symbol, side, entry_price, unrealized_pnl_pct, status, bot_name "
                "FROM positions WHERE status='open' ORDER BY id DESC LIMIT 50"
            ).fetchall()
            for r in rows:
                positions.append({
                    'symbol': r[0], 'side': r[1], 'entry_price': r[2],
                    'pnl_pct': r[3], 'status': r[4], 'bot_type': r[5],
                    'bot_display_name': get_display_name(r[5]),
                })
        except Exception:
            pass
        finally:
            conn.close()
    return jsonify(positions)


@app.route('/api/dashboard')
def api_dashboard():
    """JSON API: ダッシュボード用の全データ集約"""
    bot_stats = {}
    open_count = 0
    total_pnl = 0.0
    danger_alerts = []

    conn = get_db()
    if conn:
        try:
            # Per-bot stats
            rows = conn.execute(
                "SELECT bot_type, COUNT(*), "
                "SUM(CASE WHEN realized_pnl_pct > 0 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN realized_pnl_pct <= 0 AND status='closed' THEN 1 ELSE 0 END), "
                "COALESCE(SUM(realized_pnl_pct), 0) "
                "FROM paper_signals GROUP BY bot_type"
            ).fetchall()
            for r in rows:
                pnl = r[4] or 0
                total_pnl += pnl
                bot_stats[r[0]] = {
                    'signals': r[1] or 0, 'wins': r[2] or 0,
                    'losses': r[3] or 0, 'pnl_total': pnl,
                }
            # Open count (paper + live)
            try:
                paper_open = conn.execute(
                    "SELECT COUNT(*) FROM paper_signals WHERE status='open'"
                ).fetchone()[0]
                live_open = conn.execute(
                    "SELECT COUNT(*) FROM positions WHERE status='open'"
                ).fetchone()[0]
                open_count = paper_open + live_open
            except Exception:
                pass
            # Include live positions PnL
            try:
                live_pnl_row = conn.execute(
                    "SELECT COALESCE(SUM(realized_pnl_pct), 0) FROM positions WHERE status='closed'"
                ).fetchone()
                total_pnl += (live_pnl_row[0] or 0)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            conn.close()

    # BotManager states
    bots_data = {}
    if _bot_manager:
        for st in _bot_manager.get_all_states():
            name = st['name']
            stats = bot_stats.get(name, {'signals': 0, 'wins': 0, 'losses': 0, 'pnl_total': 0})
            bots_data[name] = {
                'display_name': get_display_name(name),
                'mode': st['mode'],
                'running': st['running'],
                'stats': stats,
            }

    # WebSocket stats
    ws_stats = _ws_feed.get_stats() if _ws_feed else {"is_connected": False}

    return jsonify({
        'total_pnl': total_pnl,
        'open_count': open_count,
        'danger_alerts': danger_alerts,
        'bots': bots_data,
        'websocket': ws_stats,
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/bot_events')
def api_bot_events():
    """JSON API: Bot停止・サーキットブレーカー等のイベント一覧"""
    events = []

    # 1. BotManager: disabled/stopped bots
    if _bot_manager:
        for st in _bot_manager.get_all_states():
            name = st['name']
            mode = st['mode']
            if mode == 'disabled':
                events.append({
                    'type': 'disabled',
                    'bot': get_display_name(name),
                    'message': f'{get_display_name(name)} は無効化されています',
                    'severity': 'info',
                })

    # 2. Circuit breaker status (from order_executor)
    oe = _order_executor or (getattr(_engine, 'order_executor', None) if _engine else None)
    cb = oe.get_circuit_breaker_status() if oe else {}
    if cb.get('circuit_broken'):
        reason_parts = []
        if cb.get('consecutive_losses', 0) >= cb.get('max_consecutive_losses', 5):
            reason_parts.append(f"連敗 {cb['consecutive_losses']}/{cb['max_consecutive_losses']}")
        if cb.get('daily_pnl', 0) <= -cb.get('max_daily_loss_pct', 5):
            reason_parts.append(f"日次損失 {cb['daily_pnl']:.1f}%")
        reason = '、'.join(reason_parts) if reason_parts else 'サーキットブレーカー発動'
        events.append({
            'type': 'circuit_breaker',
            'bot': 'ALL',
            'message': f'新規注文停止中: {reason}',
            'severity': 'danger',
        })

    # 3. Risk events from DB (last 24h)
    conn = get_db()
    if conn:
        try:
            rows = conn.execute(
                "SELECT event_type, trigger_value, limit_value, action_taken, timestamp, portfolio_id "
                "FROM risk_events WHERE timestamp > datetime('now', '-24 hours') "
                "ORDER BY id DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                events.append({
                    'type': 'risk',
                    'bot': f'portfolio#{r[5]}' if r[5] else 'ALL',
                    'message': f'{r[0]}: {r[1]:.2f} (上限{r[2]:.2f}) → {r[3]}',
                    'severity': 'warning',
                    'timestamp': r[4],
                })
        except Exception:
            pass

        # 4. Recent bot losses (consecutive SL from paper_signals)
        try:
            rows = conn.execute(
                "SELECT bot_type, COUNT(*) as cnt FROM paper_signals "
                "WHERE status='closed' AND exit_reason='SL' "
                "AND id > (SELECT COALESCE(MAX(id), 0) FROM paper_signals "
                "          WHERE status='closed' AND exit_reason='TP' "
                "          AND bot_type = paper_signals.bot_type) "
                "GROUP BY bot_type HAVING cnt >= 3"
            ).fetchall()
            for r in rows:
                events.append({
                    'type': 'losing_streak',
                    'bot': get_display_name(r[0]),
                    'message': f'{get_display_name(r[0])}: {r[1]}連敗中（直近SLのみ）',
                    'severity': 'warning',
                })
        except Exception:
            pass
        finally:
            conn.close()

    # Sort: danger first, then warning, then info
    severity_order = {'danger': 0, 'warning': 1, 'info': 2}
    events.sort(key=lambda e: severity_order.get(e['severity'], 3))

    return jsonify({'events': events})


def _resolve_realtime_price(symbol: str) -> float:
    """WS feedからリアルタイム価格を取得。シンボル表記ゆれを吸収。"""
    if not _ws_feed:
        return 0
    # Try original symbol
    price = _ws_feed.get_price(symbol)
    if price and price > 0:
        return price
    # Try alternative formats (MEXC WS: NAORIS_USDT ↔ ccxt: NAORIS/USDT:USDT)
    if '/' in symbol:
        alt = symbol.replace('/USDT:USDT', '_USDT').replace(':USDT', '').replace('/', '_')
    elif '_' in symbol:
        base = symbol.replace('_USDT', '')
        alt = f'{base}/USDT:USDT'
    else:
        return 0
    price = _ws_feed.get_price(alt)
    return price if price and price > 0 else 0


@app.route('/api/position/close', methods=['POST'])
def api_position_close():
    """JSON API: 手動決済（Paper / Live 両対応）
    優先順位: WS feed リアルタイム価格 > リクエスト価格 > DB価格 > エントリー価格
    """
    data = request.get_json(silent=True) or {}
    pos_id = data.get('id')
    source = data.get('source', '')  # 'paper' or 'live'
    symbol = data.get('symbol', '')
    bot_name = data.get('bot_name', '')
    client_price = data.get('current_price', 0)

    if not pos_id or not source:
        return jsonify({'success': False, 'error': 'id and source required'}), 400

    # WS feedからリアルタイム価格取得
    ws_price = _resolve_realtime_price(symbol) if symbol else 0

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'error': 'DB not available'}), 500

    try:
        if source == 'paper':
            row = conn.execute(
                "SELECT id, side, entry_price, leverage, current_price, symbol "
                "FROM paper_signals WHERE id=? AND status='open'", (pos_id,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Paper signal not found or already closed'})

            entry_price = row[2]
            leverage = row[3]
            is_long = row[1] == 'long'
            db_symbol = row[5] or symbol

            # WS price fallback chain: ws_price(from request symbol) > ws_price(from DB symbol) > client > DB > entry
            price = ws_price
            if not price and db_symbol and db_symbol != symbol:
                price = _resolve_realtime_price(db_symbol)
            if not price and client_price > 0:
                price = client_price
            if not price:
                price = row[4] or entry_price

            price_source = 'realtime' if ws_price > 0 else ('client' if client_price > 0 else 'fallback')

            if is_long:
                raw_pnl = (price - entry_price) / entry_price * 100
            else:
                raw_pnl = (entry_price - price) / entry_price * 100
            realized_pnl = round((raw_pnl - ROUND_TRIP_COST_PCT) * leverage, 2)

            conn.execute(
                "UPDATE paper_signals SET status='closed', exit_price=?, exit_time=?, "
                "exit_reason='MANUAL', realized_pnl_pct=?, current_price=? WHERE id=?",
                (price, datetime.now().isoformat(), realized_pnl, price, pos_id)
            )
            conn.commit()
            return jsonify({'success': True, 'realized_pnl_pct': realized_pnl,
                            'exit_price': price, 'price_source': price_source,
                            'message': f'Paper position closed: PnL {realized_pnl:+.2f}% (price: ${price:.6f} [{price_source}])'})

        elif source == 'live':
            row = conn.execute(
                "SELECT id, side, entry_price, leverage, current_price, symbol "
                "FROM positions WHERE id=? AND status='open'", (pos_id,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Live position not found or already closed'})

            entry_price = row[2]
            leverage = row[3]
            is_long = row[1] == 'long'
            live_symbol = row[5] or symbol

            # Try exchange close first (gets real fill price)
            exchange_closed = False
            fill_price = 0
            if _bot_manager:
                try:
                    import asyncio
                    worker = _bot_manager.workers.get(bot_name)
                    if worker and hasattr(worker, 'order_executor') and worker.order_executor:
                        loop = asyncio.new_event_loop()
                        result = loop.run_until_complete(
                            worker.order_executor.close_position(live_symbol, reason='manual_gui')
                        )
                        loop.close()
                        if result.get('success'):
                            exchange_closed = True
                            fill_price = result.get('fill_price', 0)
                except Exception:
                    pass

            # Price: exchange fill > WS realtime > client > DB > entry
            price = fill_price
            if not price:
                price = ws_price or _resolve_realtime_price(live_symbol)
            if not price and client_price > 0:
                price = client_price
            if not price:
                price = row[4] or entry_price

            if is_long:
                raw_pnl = (price - entry_price) / entry_price * 100
            else:
                raw_pnl = (entry_price - price) / entry_price * 100
            realized_pnl = round((raw_pnl - ROUND_TRIP_COST_PCT) * leverage, 2)

            conn.execute(
                "UPDATE positions SET status='closed', exit_price=?, exit_time=?, "
                "realized_pnl_pct=? WHERE id=?",
                (price, datetime.now().isoformat(), realized_pnl, pos_id)
            )
            conn.commit()

            msg = f'Live position closed: PnL {realized_pnl:+.2f}% (price: ${price:.6f})'
            if not exchange_closed:
                msg += ' [DB only - verify exchange manually]'
            return jsonify({'success': True, 'realized_pnl_pct': realized_pnl,
                            'exit_price': price,
                            'exchange_closed': exchange_closed, 'message': msg})

        else:
            return jsonify({'success': False, 'error': f'Unknown source: {source}'}), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()


# ========================================
# Settings Page
# ========================================

@app.route('/settings')
def settings_page():
    """API設定 + ライブ実行設定 + コンフリクト管理ページ"""
    from src.core.config_manager import ConfigManager
    from src.core.api_manager import APIManager

    cm = ConfigManager()
    config = cm.load()
    live_cfg = cm.get_live_execution()

    # デフォルトAPI
    default_api = config.get('exchange', {})
    default_key = default_api.get('api_key', '')
    default_secret = default_api.get('api_secret', '')
    masked_key = cm.mask_key(default_key)
    masked_secret = cm.mask_key(default_secret)

    # Bot別API
    all_bot_apis = cm.get_all_bot_apis()

    # コンフリクトレポート生成
    api_mgr = APIManager(config)
    for bot_name, info in all_bot_apis.items():
        api_mgr.register_bot(bot_name, info.get('api_key', ''))
    conflict_report = api_mgr.get_conflict_report()

    # === Exchange Settings Card ===
    exc_cfg = config.get('exchange', {})
    exc_name = exc_cfg.get('name', 'mexc')
    exc_demo = exc_cfg.get('demo', False)
    exc_exchanges = ['mexc', 'bitmart', 'binance', 'bybit', 'okx']

    html = f'''
<div class="card">
  <h2>取引所設定</h2>
  <p style="color:var(--muted)">取引所の選択とAPI認証設定。変更後は「保存&再読込」で反映されます。</p>

  <div style="display:grid;grid-template-columns:200px 1fr;gap:12px 16px;align-items:center;max-width:700px">

    <label>取引所</label>
    <select id="exc_name" style="width:180px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      {''.join(f'<option value="{e}" {"selected" if e == exc_name else ""}>{e.upper()}</option>' for e in exc_exchanges)}
    </select>

    <label>APIキー環境変数</label>
    <input type="text" id="exc_api_key_env" value="{exc_cfg.get('api_key_env', exc_name.upper() + '_API_KEY')}" placeholder="{exc_name.upper()}_API_KEY"
      style="width:280px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-family:monospace">

    <label>シークレット環境変数</label>
    <input type="text" id="exc_secret_env" value="{exc_cfg.get('secret_env', exc_name.upper() + '_API_SECRET')}" placeholder="{exc_name.upper()}_API_SECRET"
      style="width:280px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-family:monospace">

    <label>Memo環境変数 <span style="color:var(--muted);font-size:11px">(BitMart)</span></label>
    <input type="text" id="exc_memo_env" value="{exc_cfg.get('memo_env', exc_name.upper() + '_MEMO')}" placeholder="{exc_name.upper()}_MEMO"
      style="width:280px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-family:monospace">

    <label>デモ / サンドボックス</label>
    <label style="cursor:pointer;display:inline-flex;align-items:center;gap:6px">
      <input type="checkbox" id="exc_demo" {'checked' if exc_demo else ''} style="width:18px;height:18px">
      <span style="color:var(--muted)">テストネット使用</span>
    </label>

    <div></div>
    <div style="display:flex;gap:8px;margin-top:5px">
      <button type="button" onclick="saveExchange()" style="padding:8px 20px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer;font-weight:bold">保存&amp;再読込</button>
      <button type="button" onclick="testExchangeConnection()" style="padding:8px 16px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">接続テスト</button>
      <span id="excResult" style="line-height:36px"></span>
    </div>
  </div>
  <div id="excTestResult" style="margin-top:12px;display:none"></div>
</div>
'''

    # === Live Execution Settings Card ===
    le = live_cfg
    enabled_checked = 'checked' if le.get('enabled') else ''
    dry_run_checked = 'checked' if le.get('dry_run_first') else ''
    margin_cross = 'selected' if le.get('default_margin_type') == 'cross' else ''
    margin_isolated = 'selected' if le.get('default_margin_type') == 'isolated' else ''
    allowed_bots_str = ', '.join(le.get('allowed_bots', []))

    html += f'''
<div class="card">
  <h2>ライブ実行設定</h2>
  <p style="color:var(--muted)">ライブ注文実行の設定。変更は即座にsettings.yamlに保存されます。<br>
  <strong>注意:</strong> マスタースイッチをONにすると実際の注文が発行されます。</p>

  <div id="liveExecForm" style="display:grid;grid-template-columns:200px 1fr;gap:12px 16px;align-items:center;max-width:700px">

    <label>マスタースイッチ</label>
    <div>
      <label style="cursor:pointer;display:inline-flex;align-items:center;gap:6px">
        <input type="checkbox" id="le_enabled" {enabled_checked} style="width:18px;height:18px">
        <span id="le_enabled_label" style="font-weight:bold;color:var(--{"green" if le.get("enabled") else "red"})">
          {"ON — ライブ実行中" if le.get("enabled") else "OFF — 無効"}
        </span>
      </label>
    </div>

    <label>最大ポジション数</label>
    <input type="number" id="le_max_positions" value="{le.get('max_positions', 3)}" min="1" max="20"
      style="width:80px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>日次損失リミット (%)</label>
    <input type="number" id="le_max_daily_loss_pct" value="{le.get('max_daily_loss_pct', 5.0)}" step="0.5" min="1" max="50"
      style="width:100px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>最大連続負け回数</label>
    <input type="number" id="le_max_consecutive_losses" value="{le.get('max_consecutive_losses', 5)}" min="1" max="20"
      style="width:80px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>最低残高 (USDT)</label>
    <input type="number" id="le_min_balance_usd" value="{le.get('min_balance_usd', 50.0)}" step="10" min="0"
      style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>ポジション上限 (USDT)</label>
    <input type="number" id="le_position_size_cap_usd" value="{le.get('position_size_cap_usd', 500.0)}" step="50" min="10"
      style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>マージンタイプ</label>
    <select id="le_default_margin_type"
      style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <option value="cross" {margin_cross}>クロス</option>
      <option value="isolated" {margin_isolated}>分離</option>
    </select>

    <label>スリッページ許容 (%)</label>
    <input type="number" id="le_slippage_tolerance_pct" value="{le.get('slippage_tolerance_pct', 0.5)}" step="0.1" min="0.1" max="5"
      style="width:100px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>ドライラン優先</label>
    <label style="cursor:pointer;display:inline-flex;align-items:center;gap:6px">
      <input type="checkbox" id="le_dry_run_first" {dry_run_checked} style="width:18px;height:18px">
      <span style="color:var(--muted)">初回シグナルはログのみ</span>
    </label>

    <label>許可Bot</label>
    <div>
      <input type="text" id="le_allowed_bots" value="{allowed_bots_str}" placeholder="空欄=全Bot許可 / カンマ区切り"
        style="width:100%;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <span style="color:var(--muted);font-size:12px">例: alpha, surge, meanrevert_tight</span>
    </div>

    <label>同期間隔 (秒)</label>
    <input type="number" id="le_sync_interval_seconds" value="{le.get('sync_interval_seconds', 60)}" min="10" max="600"
      style="width:100px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <div></div>
    <div style="display:flex;gap:8px;margin-top:5px">
      <button type="button" onclick="saveLiveExec()" style="padding:8px 20px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer;font-weight:bold">保存</button>
      <span id="liveExecResult" style="line-height:36px"></span>
    </div>
  </div>
</div>
'''

    # === Default API Card ===
    html += '''
<div class="card">
  <h2>デフォルトAPI設定</h2>
  <p style="color:var(--muted)">全Botのフォールバック設定。Bot個別APIが未設定の場合にこのキーが使用されます。</p>
  <form id="defaultApiForm" style="display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;max-width:600px">
    <label>API Key</label>
    <div style="display:flex;gap:8px">
      <input type="text" id="defaultApiKeyDisplay" value="{masked_key}" readonly style="flex:1;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--muted);border-radius:4px;font-family:monospace">
      <input type="password" id="defaultApiKey" value="" placeholder="新しいAPIキーを入力" style="flex:1;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    </div>
    <label>API Secret</label>
    <div style="display:flex;gap:8px">
      <input type="text" id="defaultApiSecretDisplay" value="{masked_secret}" readonly style="flex:1;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--muted);border-radius:4px;font-family:monospace">
      <input type="password" id="defaultApiSecret" value="" placeholder="新しいSecretを入力" style="flex:1;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    </div>
    <div></div>
    <div style="display:flex;gap:8px;margin-top:5px">
      <button type="button" onclick="saveDefaultApi()" style="padding:8px 16px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer">保存</button>
      <button type="button" onclick="testApi('default')" style="padding:8px 16px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">接続テスト</button>
      <span id="defaultResult" style="line-height:36px"></span>
    </div>
  </form>
</div>
'''

    # === Bot別API Grid ===
    html += '''
<div class="card">
  <h2>Bot別API設定</h2>
  <p style="color:var(--muted)">Bot個別にAPIキーを設定可能。空欄の場合はデフォルトAPIが使用されます。</p>
  <div style="overflow-x:auto">
  <table class="score-table" style="width:100%">
    <thead><tr>
      <th>Bot</th><th>モード</th><th>APIキー</th><th>ソース</th><th>操作</th>
    </tr></thead>
    <tbody>
'''
    for bot_name, info in sorted(all_bot_apis.items()):
        mode = info.get('mode', 'paper')
        is_custom = info.get('is_custom', False)
        key = info.get('api_key', '')
        masked = cm.mask_key(key)
        source_badge = '<span style="color:var(--green)">カスタム</span>' if is_custom else '<span style="color:var(--muted)">デフォルト</span>'

        html += f'''<tr>
  <td><strong>{bot_name}</strong></td>
  <td><span class="badge" style="background:var(--{'green' if mode == 'live' else 'yellow' if mode == 'paper' else 'gray'})">{mode}</span></td>
  <td style="font-family:monospace">{masked}</td>
  <td>{source_badge}</td>
  <td>
    <button onclick="editBotApi('{bot_name}')" style="padding:4px 10px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">編集</button>
    <button onclick="testApi('{bot_name}')" style="padding:4px 10px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer;margin-left:4px">テスト</button>
  </td>
</tr>'''

    html += '</tbody></table></div></div>'

    # === Conflict Report ===
    html += '''
<div class="card">
  <h2>API競合検知</h2>
  <p style="color:var(--muted)">同一APIキーを共有するBotグループと競合リスク</p>
  <table class="score-table" style="width:100%">
    <thead><tr>
      <th>APIグループ</th><th>Bot</th><th>数</th><th>最大同時</th><th>リスク</th>
    </tr></thead>
    <tbody>
'''
    for group in conflict_report:
        risk = group['risk']
        risk_color = {'safe': 'green', 'warn': 'yellow', 'high': 'red'}.get(risk, 'muted')
        bots_str = ', '.join(group['bots'])
        html += f'''<tr>
  <td style="font-family:monospace">{group['api_key_masked']}</td>
  <td>{bots_str}</td>
  <td>{group['bot_count']}</td>
  <td>{group['max_concurrent']}</td>
  <td><span style="color:var(--{risk_color});font-weight:bold">{risk.upper()}</span></td>
</tr>'''

    html += '</tbody></table></div>'

    # === Bot API Edit Modal ===
    html += '''
<div id="editModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:1000;align-items:center;justify-content:center">
  <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:24px;max-width:500px;width:90%">
    <h3 style="margin-top:0">API編集 - <span id="editBotName"></span></h3>
    <div style="display:grid;grid-template-columns:100px 1fr;gap:10px;align-items:center">
      <label>API Key</label>
      <input type="password" id="editKey" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <label>API Secret</label>
      <input type="password" id="editSecret" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    </div>
    <div style="display:flex;gap:8px;margin-top:15px;justify-content:flex-end">
      <button onclick="closeModal()" style="padding:8px 16px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">キャンセル</button>
      <button onclick="saveBotApi()" style="padding:8px 16px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer">保存</button>
      <span id="editResult"></span>
    </div>
  </div>
</div>

<script>
function togglePwd(id) {
  var el = document.getElementById(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}

function saveDefaultApi() {
  var key = document.getElementById('defaultApiKey').value;
  var secret = document.getElementById('defaultApiSecret').value;
  fetch('/api/settings/api', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({bot_name: 'default', api_key: key, api_secret: secret})
  }).then(r => r.json()).then(d => {
    document.getElementById('defaultResult').innerHTML =
      d.success ? '<span style="color:var(--green)">保存完了!</span>' : '<span style="color:var(--red)">'+d.error+'</span>';
  });
}

function editBotApi(name) {
  document.getElementById('editBotName').textContent = name;
  document.getElementById('editKey').value = '';
  document.getElementById('editSecret').value = '';
  document.getElementById('editResult').innerHTML = '';
  document.getElementById('editModal').style.display = 'flex';
}

function closeModal() {
  document.getElementById('editModal').style.display = 'none';
}

function saveBotApi() {
  var name = document.getElementById('editBotName').textContent;
  var key = document.getElementById('editKey').value;
  var secret = document.getElementById('editSecret').value;
  fetch('/api/settings/api', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({bot_name: name, api_key: key, api_secret: secret})
  }).then(r => r.json()).then(d => {
    if (d.success) { location.reload(); }
    else { document.getElementById('editResult').innerHTML = '<span style="color:var(--red)">'+d.error+'</span>'; }
  });
}

function testApi(botName) {
  fetch('/api/settings/test', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({bot_name: botName})
  }).then(r => r.json()).then(d => {
    var msg = d.success ? '接続成功! 残高: '+d.balance : 'エラー: '+d.error;
    var color = d.success ? 'var(--green)' : 'var(--red)';
    if (botName === 'default') {
      document.getElementById('defaultResult').innerHTML = '<span style="color:'+color+'">'+msg+'</span>';
    } else {
      alert(msg);
    }
  });
}

function saveExchange() {
  var data = {
    name: document.getElementById('exc_name').value,
    api_key_env: document.getElementById('exc_api_key_env').value,
    secret_env: document.getElementById('exc_secret_env').value,
    memo_env: document.getElementById('exc_memo_env').value,
    demo: document.getElementById('exc_demo').checked,
  };
  var el = document.getElementById('excResult');
  el.innerHTML = '<span style="color:var(--muted)">保存中...</span>';
  fetch('/api/settings/exchange', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  }).then(r => r.json()).then(d => {
    el.innerHTML = d.success ? '<span style="color:var(--green)">保存完了! エンジン再起動で反映されます。</span>'
      : '<span style="color:var(--red)">'+d.error+'</span>';
  }).catch(err => { el.innerHTML = '<span style="color:var(--red)">ネットワークエラー</span>'; });
}

function testExchangeConnection() {
  var el = document.getElementById('excTestResult');
  el.style.display = 'block';
  el.innerHTML = '<span style="color:var(--muted)">接続テスト中...</span>';
  fetch('/api/settings/exchange_test', {method: 'POST'}).then(r => r.json()).then(d => {
    if (d.error) { el.innerHTML = '<span style="color:var(--red)">'+d.error+'</span>'; return; }
    var rows = '';
    var checks = [
      ['公開REST', d.public_ok], ['秘密鍵REST', d.private_ok],
      ['FR取得', d.fr_ok], ['ポジションモード', d.position_mode_ok]
    ];
    for (var c of checks) {
      var ok = c[1];
      rows += '<div style="display:flex;gap:8px;align-items:center">'
        + '<span style="color:var(--'+(ok?'green':'red')+')">&#x'+(ok?'2705':'274c')+';</span>'
        + '<span>'+c[0]+'</span></div>';
    }
    rows += '<div style="margin-top:6px;color:var(--muted)">レイテンシ: '+d.latency_ms+'ms</div>';
    if (d.errors && d.errors.length > 0) {
      rows += '<div style="margin-top:6px;color:var(--red);font-size:12px">'+d.errors.join('<br>')+'</div>';
    }
    el.innerHTML = rows;
  }).catch(err => { el.innerHTML = '<span style="color:var(--red)">ネットワークエラー</span>'; });
}

function saveLiveExec() {
  var data = {
    enabled: document.getElementById('le_enabled').checked,
    max_positions: parseInt(document.getElementById('le_max_positions').value),
    max_daily_loss_pct: parseFloat(document.getElementById('le_max_daily_loss_pct').value),
    max_consecutive_losses: parseInt(document.getElementById('le_max_consecutive_losses').value),
    min_balance_usd: parseFloat(document.getElementById('le_min_balance_usd').value),
    position_size_cap_usd: parseFloat(document.getElementById('le_position_size_cap_usd').value),
    default_margin_type: document.getElementById('le_default_margin_type').value,
    slippage_tolerance_pct: parseFloat(document.getElementById('le_slippage_tolerance_pct').value),
    dry_run_first: document.getElementById('le_dry_run_first').checked,
    allowed_bots: document.getElementById('le_allowed_bots').value,
    sync_interval_seconds: parseInt(document.getElementById('le_sync_interval_seconds').value),
  };
  var el = document.getElementById('liveExecResult');
  el.innerHTML = '<span style="color:var(--muted)">保存中...</span>';

  fetch('/api/settings/live_execution', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  }).then(r => r.json()).then(d => {
    if (!d.success) {
      el.innerHTML = '<span style="color:var(--red)">\u274c エラー: '+d.error+'</span>';
      return;
    }
    // 保存後にGETで再読込して実際の値を検証
    fetch('/api/settings/live_execution').then(r => r.json()).then(saved => {
      var mismatches = [];
      if (saved.enabled !== data.enabled) mismatches.push('enabled');
      if (saved.max_positions !== data.max_positions) mismatches.push('max_positions');
      if (saved.max_daily_loss_pct !== data.max_daily_loss_pct) mismatches.push('max_daily_loss_pct');
      if (saved.max_consecutive_losses !== data.max_consecutive_losses) mismatches.push('max_consecutive_losses');
      if (saved.min_balance_usd !== data.min_balance_usd) mismatches.push('min_balance_usd');
      if (saved.position_size_cap_usd !== data.position_size_cap_usd) mismatches.push('position_size_cap_usd');
      if (saved.default_margin_type !== data.default_margin_type) mismatches.push('default_margin_type');

      if (mismatches.length > 0) {
        el.innerHTML = '<span style="color:var(--red)">\u26a0\ufe0f \u4fdd\u5b58\u306f\u3055\u308c\u307e\u3057\u305f\u304c\u4e00\u90e8\u4e0d\u4e00\u81f4: '+mismatches.join(', ')+'</span>';
      } else {
        el.innerHTML = '<span style="color:var(--green)">\u2705 保存&検証完了</span>';
      }

      // フォームを実際の保存値で上書き（ズレ防止）
      document.getElementById('le_enabled').checked = saved.enabled;
      document.getElementById('le_max_positions').value = saved.max_positions;
      document.getElementById('le_max_daily_loss_pct').value = saved.max_daily_loss_pct;
      document.getElementById('le_max_consecutive_losses').value = saved.max_consecutive_losses;
      document.getElementById('le_min_balance_usd').value = saved.min_balance_usd;
      document.getElementById('le_position_size_cap_usd').value = saved.position_size_cap_usd;
      document.getElementById('le_default_margin_type').value = saved.default_margin_type;
      document.getElementById('le_slippage_tolerance_pct').value = saved.slippage_tolerance_pct;
      document.getElementById('le_dry_run_first').checked = saved.dry_run_first;
      document.getElementById('le_allowed_bots').value = (saved.allowed_bots || []).join(', ');
      document.getElementById('le_sync_interval_seconds').value = saved.sync_interval_seconds;

      // enabledラベル更新
      var lbl = document.getElementById('le_enabled_label');
      if (saved.enabled) {
        lbl.textContent = 'ON \u2014 \u30e9\u30a4\u30d6\u5b9f\u884c\u4e2d';
        lbl.style.color = 'var(--green)';
      } else {
        lbl.textContent = 'OFF \u2014 \u7121\u52b9';
        lbl.style.color = 'var(--red)';
      }

      setTimeout(function(){ el.innerHTML = ''; }, 5000);
    });
  }).catch(function(err) {
    el.innerHTML = '<span style="color:var(--red)">\u274c ネットワークエラー: '+err+'</span>';
  });
}
</script>
'''

    # === Risk Management Settings Card ===
    rm_cfg = cm.get_risk_management()

    html += f'''
<div class="card">
  <h2>Risk Management</h2>
  <p style="color:var(--muted)">日次/累積損失リミット設定。リミット超過時のアクション(新規注文停止 or Bot停止)を選択。</p>

  <div style="display:grid;grid-template-columns:200px 1fr;gap:12px 16px;align-items:center;max-width:700px">

    <label>Daily Loss Limit (%)</label>
    <input type="number" id="rm_daily_loss_limit_pct" value="{rm_cfg.get('daily_loss_limit_pct', 5.0)}" step="0.5" min="0.5" max="50"
      style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>Cumulative Loss Limit (%)</label>
    <input type="number" id="rm_cumulative_loss_limit_pct" value="{rm_cfg.get('cumulative_loss_limit_pct', 20.0)}" step="1" min="1" max="100"
      style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">

    <label>Limit Action</label>
    <select id="rm_limit_action" style="width:200px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <option value="order_stop" {"selected" if rm_cfg.get('limit_action') == 'order_stop' else ""}>order_stop (新規注文停止)</option>
      <option value="bot_stop" {"selected" if rm_cfg.get('limit_action') == 'bot_stop' else ""}>bot_stop (Bot完全停止)</option>
    </select>

    <div></div>
    <div style="display:flex;gap:8px;margin-top:5px">
      <button type="button" onclick="saveRiskManagement()" style="padding:8px 20px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer;font-weight:bold">Save</button>
      <span id="rmResult" style="line-height:36px"></span>
    </div>
  </div>
</div>

<script>
function saveRiskManagement() {{
  var data = {{
    daily_loss_limit_pct: parseFloat(document.getElementById('rm_daily_loss_limit_pct').value),
    cumulative_loss_limit_pct: parseFloat(document.getElementById('rm_cumulative_loss_limit_pct').value),
    limit_action: document.getElementById('rm_limit_action').value,
  }};
  var el = document.getElementById('rmResult');
  el.innerHTML = '<span style="color:var(--muted)">保存中...</span>';
  fetch('/api/settings/risk_management', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(data)
  }}).then(r => r.json()).then(d => {{
    if (d.success) {{
      el.innerHTML = '<span style="color:var(--green)">Saved!</span>';
      setTimeout(function(){{ el.innerHTML = ''; }}, 3000);
    }} else {{
      el.innerHTML = '<span style="color:var(--red)">'+d.error+'</span>';
    }}
  }}).catch(function(err) {{
    el.innerHTML = '<span style="color:var(--red)">ネットワークエラー</span>';
  }});
}}
</script>
'''

    return _page('settings', 'Settings', html)


@app.route('/api/settings/api', methods=['POST'])
def api_settings_save():
    """API設定を保存"""
    from src.core.config_manager import ConfigManager
    data = request.get_json(silent=True) or {}
    bot_name = data.get('bot_name', '')
    api_key = data.get('api_key', '')
    api_secret = data.get('api_secret', '')

    if not bot_name:
        return jsonify({'success': False, 'error': 'bot_name required'}), 400

    try:
        cm = ConfigManager()
        cm.update_bot_api(bot_name, api_key, api_secret)
        return jsonify({'success': True, 'bot_name': bot_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/settings/test', methods=['POST'])
def api_settings_test():
    """API接続テスト（取引所対応）"""
    from src.core.config_manager import ConfigManager
    data = request.get_json(silent=True) or {}
    bot_name = data.get('bot_name', 'default')

    try:
        cm = ConfigManager()
        api_cfg = cm.get_bot_api(bot_name)
        api_key = api_cfg.get('api_key', '')
        api_secret = api_cfg.get('api_secret', '')

        if not api_key:
            return jsonify({'success': False, 'error': 'No API key configured'})

        # 取引所設定に応じてccxtインスタンス生成
        config = cm.load()
        exc_name = config.get('exchange', {}).get('name', 'mexc')
        import ccxt
        exchange_class = getattr(ccxt, exc_name, ccxt.mexc)
        ccxt_config = {
            'apiKey': api_key,
            'secret': api_secret,
            'options': {'defaultType': 'swap'},
        }
        # BitMart memo対応
        if exc_name == 'bitmart':
            import os
            memo_env = config.get('exchange', {}).get('memo_env', 'BITMART_MEMO')
            memo = os.getenv(memo_env, '')
            if memo:
                ccxt_config['uid'] = memo
        exchange = exchange_class(ccxt_config)
        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {}).get('total', 0)
        return jsonify({'success': True, 'balance': f'{usdt:.2f} USDT', 'exchange': exc_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/settings/exchange', methods=['POST'])
def api_settings_exchange_save():
    """取引所設定を保存"""
    from src.core.config_manager import ConfigManager
    data = request.get_json(silent=True) or {}
    try:
        cm = ConfigManager()
        config = cm.load()
        exc = config.get('exchange', {})
        exc['name'] = data.get('name', exc.get('name', 'mexc'))
        exc['api_key_env'] = data.get('api_key_env', exc.get('api_key_env', ''))
        exc['secret_env'] = data.get('secret_env', exc.get('secret_env', ''))
        exc['memo_env'] = data.get('memo_env', exc.get('memo_env', ''))
        exc['demo'] = data.get('demo', exc.get('demo', False))
        config['exchange'] = exc
        cm.save(config)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/settings/exchange_test', methods=['POST'])
def api_settings_exchange_test():
    """取引所接続テスト（詳細）"""
    import asyncio
    try:
        config = get_config()
        exc_cfg = config.get('exchange', {'name': 'mexc'})
        from src.exchange.exchange_factory import create_exchange
        from src.exchange.exchange_utils import test_connection

        async def _run_test():
            exchange = create_exchange(exc_cfg)
            try:
                result = await test_connection(exchange)
                return result
            finally:
                await exchange.close()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run_test())
        finally:
            loop.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/balance')
def api_balance():
    """残高取得API（ダッシュボード残高カード用）"""
    import asyncio
    try:
        config = get_config()
        exc_cfg = config.get('exchange', {'name': 'mexc'})
        from src.exchange.exchange_factory import create_exchange

        async def _fetch():
            exchange = create_exchange(exc_cfg)
            try:
                balance = await exchange.fetch_balance()
                usdt = balance.get('USDT', {})
                total = float(usdt.get('total', 0) or 0)
                free = float(usdt.get('free', 0) or 0)
                used = float(usdt.get('used', 0) or 0)

                # Unrealized PnL from positions
                unrealized_pnl = 0
                try:
                    positions = await exchange.fetch_positions()
                    for pos in positions:
                        pnl = float(pos.get('unrealizedPnl', 0) or 0)
                        unrealized_pnl += pnl
                except Exception:
                    pass

                return {
                    'available': True,
                    'exchange': exchange.id,
                    'total': round(total, 2),
                    'free': round(free, 2),
                    'used': round(used, 2),
                    'unrealized_pnl': round(unrealized_pnl, 2),
                }
            finally:
                await exchange.close()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_fetch())
        finally:
            loop.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'available': False, 'error': str(e)})


@app.route('/api/settings/live_execution', methods=['GET', 'POST'])
def api_settings_live_execution():
    """ライブ実行設定のGET/POST"""
    from src.core.config_manager import ConfigManager
    cm = ConfigManager()

    if request.method == 'GET':
        return jsonify(cm.get_live_execution())

    # POST: 更新
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    try:
        cm.update_live_execution(data)
        return jsonify({'success': True, 'updated': list(data.keys())})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/settings/conflicts')
def api_settings_conflicts():
    """コンフリクト状況API"""
    from src.core.config_manager import ConfigManager
    from src.core.api_manager import APIManager

    cm = ConfigManager()
    config = cm.load()
    all_bot_apis = cm.get_all_bot_apis()

    api_mgr = APIManager(config)
    for bot_name, info in all_bot_apis.items():
        api_mgr.register_bot(bot_name, info.get('api_key', ''))

    return jsonify({
        'groups': api_mgr.get_conflict_report(),
        'api_groups': api_mgr.get_api_groups(),
    })


# ========================================
# Helper
# ========================================

def create_app(manager=None, ws_feed=None, order_executor=None, engine=None):
    """ファクトリ関数。BotManager / WebSocketFeed / OrderExecutor / Engineを注入してappを返す。"""
    global _bot_manager, _ws_feed, _order_executor, _engine
    if manager is not None:
        _bot_manager = manager
    if ws_feed is not None:
        _ws_feed = ws_feed
    if order_executor is not None:
        _order_executor = order_executor
    if engine is not None:
        _engine = engine
    return app


# ========== Trades Page ==========

@app.route('/trades')
def trades_page():
    """トレード履歴・パフォーマンス分析ページ"""
    # Generate JS bot display name mapping from Python dict
    from src.core.bot_display_names import BOT_DISPLAY_NAMES
    import json as _json
    _bot_names_js = _json.dumps(BOT_DISPLAY_NAMES, ensure_ascii=False)
    _bot_names_script = f'<script>var BOT_DISPLAY_NAMES={_bot_names_js};function botDisplayName(n){{return BOT_DISPLAY_NAMES[n]||n;}}</script>'

    html = _bot_names_script + '''
<div class="card">
  <h2>取引履歴</h2>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
    <select id="tf_mode" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <option value="">全モード</option><option value="paper">ペーパー</option><option value="live">ライブ</option>
    </select>
    <select id="tf_bot" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <option value="">全Bot</option>
    </select>
    <input type="text" id="tf_symbol" placeholder="銘柄" style="width:120px;padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    <input type="date" id="tf_from" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    <input type="date" id="tf_to" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
    <select id="tf_status" style="padding:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px">
      <option value="">全状態</option><option value="open">保有中</option><option value="closed">決済済</option>
    </select>
    <button onclick="loadTrades()" style="padding:6px 16px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer">絞込</button>
    <button onclick="exportTradesCsv()" style="padding:6px 16px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">CSV出力</button>
  </div>
  <div id="trades-table" style="overflow-x:auto"></div>
  <div id="trades-pagination" style="margin-top:8px;display:flex;gap:8px;align-items:center"></div>
</div>

<div class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card">
    <h2>パフォーマンス統計</h2>
    <div id="perf-stats"></div>
  </div>
  <div class="card">
    <h2>損益チャート（日次）</h2>
    <div id="pnl-chart" style="height:250px;position:relative"></div>
  </div>
</div>

<div class="card">
  <h2>リスクイベント</h2>
  <div id="risk-events"></div>
</div>

<script>
var tradesPage=0, tradesLimit=50;

function loadBotList(){
  fetch('/api/bots').then(r=>r.json()).then(d=>{
    var sel=document.getElementById('tf_bot');
    Object.keys(d).forEach(b=>{
      var o=document.createElement('option');o.value=b;o.textContent=botDisplayName(b);sel.appendChild(o);
    });
  });
}

function loadTrades(page){
  if(page!==undefined) tradesPage=page;
  var p=new URLSearchParams();
  var m=document.getElementById('tf_mode').value; if(m)p.set('mode',m);
  var b=document.getElementById('tf_bot').value; if(b)p.set('bot_name',b);
  var s=document.getElementById('tf_symbol').value; if(s)p.set('symbol',s);
  var df=document.getElementById('tf_from').value; if(df)p.set('date_from',df);
  var dt=document.getElementById('tf_to').value; if(dt)p.set('date_to',dt);
  var st=document.getElementById('tf_status').value; if(st)p.set('status',st);
  p.set('limit',tradesLimit);p.set('offset',tradesPage*tradesLimit);

  fetch('/api/trades?'+p.toString()).then(r=>r.json()).then(d=>{
    window._tradesData=d.trades;
    var t='<table class="score-table" style="width:100%;font-size:13px"><thead><tr>';
    t+='<th>Serial</th><th>エントリー時刻</th><th>決済時刻</th><th>モード</th><th>Bot</th><th>銘柄</th><th>方向</th><th>倍率</th>';
    t+='<th>エントリー</th><th>決済値</th><th>損益%</th><th>損益$</th><th>手数料</th><th>理由</th></tr></thead><tbody>';
    d.trades.forEach(function(r,idx){
      var pc=(r.pnl_pct||0)>=0?'green':'red';
      var entryTime=(r.entry_time||'').substring(0,16);
      var exitTime=(r.exit_time||'').substring(0,16);
      // 損益$: DB値優先、なければ position_size_pct × $10,000 base で概算
      var pnlAmt=r.pnl_amount;
      if(pnlAmt===null && r.pnl_pct!==null){var posPct=r.position_size_pct||1;var notional=10000*posPct/100;pnlAmt=Math.round(notional*r.pnl_pct/100*100)/100;}
      // 手数料: DB値優先、なければ概算(0.22% of notional)
      var feeAmt=r.fee_amount;
      if(feeAmt===null && r.status==='closed'){var fPosPct=r.position_size_pct||1;var fNotional=10000*fPosPct/100;feeAmt=Math.round(fNotional*0.22/100*10000)/10000;}
      t+='<tr style="cursor:pointer" onclick="showTradeDetail('+idx+')">';
      t+='<td><code style="font-size:0.75em;color:var(--cyan)">'+(r.trade_serial||'-')+'</code></td>';
      t+='<td>'+entryTime+'</td>';
      t+='<td>'+(exitTime||'-')+'</td>';
      t+='<td><span class="badge" style="background:var(--'+(r.mode==='live'?'green':'yellow')+')">'+r.mode+'</span></td>';
      t+='<td>'+botDisplayName(r.bot_name)+'</td><td>'+r.symbol+'</td>';
      t+='<td style="color:var(--'+(r.side==='long'?'green':'red')+')">'+r.side.toUpperCase()+'</td>';
      t+='<td>'+r.leverage+'x</td>';
      t+='<td>'+(r.entry_price?'$'+Number(r.entry_price).toFixed(8):'-')+'</td>';
      t+='<td>'+(r.exit_price?'$'+Number(r.exit_price).toFixed(8):'-')+'</td>';
      t+='<td style="color:var(--'+pc+')">'+(r.pnl_pct!==null?(r.pnl_pct>=0?'+':'')+r.pnl_pct+'%':'-')+'</td>';
      t+='<td style="color:var(--'+pc+')">'+(pnlAmt!==null?(pnlAmt>=0?'+$':'-$')+Math.abs(pnlAmt).toFixed(2):'-')+'</td>';
      t+='<td>'+(feeAmt!==null?'$'+Number(feeAmt).toFixed(4):'-')+'</td>';
      t+='<td>'+(r.exit_reason||r.status)+'</td></tr>';
    });
    t+='</tbody></table>';
    document.getElementById('trades-table').innerHTML=t;

    // Pagination
    var total=d.total, pages=Math.ceil(total/tradesLimit);
    var pg='<span style="color:var(--muted)">'+total+'件</span> ';
    if(tradesPage>0) pg+='<button onclick="loadTrades('+(tradesPage-1)+')" style="padding:4px 8px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">前へ</button> ';
    pg+='<span>'+(tradesPage+1)+'/'+Math.max(pages,1)+'ページ</span> ';
    if(tradesPage<pages-1) pg+='<button onclick="loadTrades('+(tradesPage+1)+')" style="padding:4px 8px;background:var(--gray);border:none;color:var(--text);border-radius:4px;cursor:pointer">次へ</button>';
    document.getElementById('trades-pagination').innerHTML=pg;
  });

  // Stats
  var sp=new URLSearchParams(p);sp.delete('limit');sp.delete('offset');sp.delete('status');
  fetch('/api/trades/stats?'+sp.toString()).then(r=>r.json()).then(s=>{
    var h='<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">';
    h+='<div><span style="color:var(--muted)">取引数</span><br><strong>'+s.total_trades+'</strong></div>';
    h+='<div><span style="color:var(--muted)">勝率</span><br><strong>'+s.win_rate+'%</strong></div>';
    h+='<div><span style="color:var(--muted)">プロフィットファクター</span><br><strong>'+s.profit_factor+'</strong></div>';
    h+='<div><span style="color:var(--muted)">最大DD</span><br><strong style="color:var(--red)">'+s.max_drawdown_pct+'%</strong></div>';
    h+='<div><span style="color:var(--muted)">平均利益</span><br><strong style="color:var(--green)">+'+s.avg_win_pct+'%</strong></div>';
    h+='<div><span style="color:var(--muted)">平均損失</span><br><strong style="color:var(--red)">'+s.avg_loss_pct+'%</strong></div>';
    h+='<div><span style="color:var(--muted)">合計損益%</span><br><strong style="color:var(--'+(s.total_pnl_pct>=0?'green':'red')+')">'+s.total_pnl_pct+'%</strong></div>';
    h+='<div><span style="color:var(--muted)">合計損益$</span><br><strong style="color:var(--'+(s.total_pnl_amount>=0?'green':'red')+')">$'+s.total_pnl_amount+'</strong></div>';
    h+='</div>';
    document.getElementById('perf-stats').innerHTML=h;
  });

  // PNL Chart
  fetch('/api/trades/daily_pnl?'+sp.toString()).then(r=>r.json()).then(data=>{
    if(!data.length){document.getElementById('pnl-chart').innerHTML='<span style="color:var(--muted)">データなし</span>';return;}
    var maxAbs=Math.max(...data.map(d=>Math.abs(d.cumulative_pnl||0)),1);
    var w=document.getElementById('pnl-chart').offsetWidth||600;
    var h=240;
    var svg='<svg width="'+w+'" height="'+h+'" style="overflow:visible">';
    svg+='<line x1="0" y1="'+h/2+'" x2="'+w+'" y2="'+h/2+'" stroke="var(--border)" stroke-dasharray="4"/>';
    var pts=data.map((d,i)=>{
      var x=i/(data.length-1||1)*w;
      var y=h/2-(d.cumulative_pnl||0)/maxAbs*h*0.45;
      return x+','+y;
    }).join(' ');
    svg+='<polyline points="'+pts+'" fill="none" stroke="var(--accent)" stroke-width="2"/>';
    svg+='</svg>';
    document.getElementById('pnl-chart').innerHTML=svg;
  });

  // Risk events
  fetch('/api/risk/events').then(r=>r.json()).then(evts=>{
    if(!evts.length){document.getElementById('risk-events').innerHTML='<span style="color:var(--muted)">リスクイベントなし</span>';return;}
    var t='<table class="score-table" style="width:100%"><thead><tr><th>時刻</th><th>種別</th><th>発動値</th><th>リミット</th><th>アクション</th></tr></thead><tbody>';
    evts.forEach(e=>{
      t+='<tr><td>'+(e.timestamp||'').substring(0,19)+'</td><td>'+e.event_type+'</td>';
      t+='<td>'+Number(e.trigger_value).toFixed(2)+'%</td><td>'+Number(e.limit_value).toFixed(2)+'%</td>';
      t+='<td>'+e.action_taken+'</td></tr>';
    });
    t+='</tbody></table>';
    document.getElementById('risk-events').innerHTML=t;
  });
}

function exportTradesCsv(){
  var p=new URLSearchParams();
  var m=document.getElementById('tf_mode').value; if(m)p.set('mode',m);
  var b=document.getElementById('tf_bot').value; if(b)p.set('bot_name',b);
  window.open('/api/trades/export_csv?'+p.toString(),'_blank');
}

function showTradeDetail(idx){
  var r=window._tradesData[idx];if(!r)return;
  var pnlAmt=r.pnl_amount;
  if(pnlAmt===null && r.pnl_pct!==null){var posPct=r.position_size_pct||1;var notional=10000*posPct/100;pnlAmt=Math.round(notional*r.pnl_pct/100*100)/100;}
  var feeAmt=r.fee_amount;
  if(feeAmt===null && r.status==='closed'){var fPosPct2=r.position_size_pct||1;var fNotional2=10000*fPosPct2/100;feeAmt=Math.round(fNotional2*0.22/100*10000)/10000;}
  var pc=(r.pnl_pct||0)>=0?'green':'red';
  var h='<div id="trade-modal-overlay" onclick="closeTradeDetail(event)" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center">';
  h+='<div style="background:#1a2332;border:1px solid #334155;border-radius:12px;padding:24px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.8)" onclick="event.stopPropagation()">';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #334155">';
  h+='<h3 style="margin:0;color:#e2e8f0;font-size:1.1em">トレード詳細 #'+r.id+'</h3>';
  h+='<button onclick="closeTradeDetail()" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;font-size:16px;cursor:pointer;border-radius:6px;width:32px;height:32px;display:flex;align-items:center;justify-content:center">✕</button></div>';
  h+='<table style="width:100%;border-collapse:collapse;background:#111827;border-radius:8px;overflow:hidden">';
  function row(label,val,color){
    h+='<tr style="border-bottom:1px solid #1e293b"><td style="padding:8px 12px;color:#94a3b8;width:40%;font-size:0.9em;background:#0f1729">'+label+'</td>';
    h+='<td style="padding:8px 12px;font-weight:600;color:'+(color?'var(--'+color+')':'#e2e8f0')+';font-size:0.9em">'+(val!==null&&val!==undefined?val:'-')+'</td></tr>';
  }
  row('Serial', r.trade_serial||'-');
  row('ID', r.id);
  row('モード', r.mode==='live'?'ライブ':'ペーパー');
  row('Bot', botDisplayName(r.bot_name));
  row('銘柄', r.symbol);
  row('方向', r.side.toUpperCase(), r.side==='long'?'green':'red');
  row('レバレッジ', r.leverage+'x');
  row('エントリー価格', r.entry_price?'$'+Number(r.entry_price).toFixed(8):'-');
  row('TP価格', r.tp_price?'$'+Number(r.tp_price).toFixed(8):'-');
  row('SL価格', r.sl_price?'$'+Number(r.sl_price).toFixed(8):'-');
  row('決済価格', r.exit_price?'$'+Number(r.exit_price).toFixed(8):'-');
  row('エントリー時刻', (r.entry_time||'').replace('T',' ').substring(0,19));
  row('決済時刻', r.exit_time?(r.exit_time||'').replace('T',' ').substring(0,19):'-');
  row('決済理由', r.exit_reason||'-');
  row('状態', r.status==='closed'?'決済済':r.status==='open'?'保有中':r.status);
  var dPosPct=r.position_size_pct||1;var dNotional=10000*dPosPct/100;
  row('ポジション%', dPosPct+'% ($'+dNotional.toFixed(0)+')');
  row('損益%', r.pnl_pct!==null?(r.pnl_pct>=0?'+':'')+r.pnl_pct+'%':'-', pc);
  row('損益$', pnlAmt!==null?(pnlAmt>=0?'+$':'-$')+Math.abs(pnlAmt).toFixed(2)+(r.pnl_amount===null?' (概算)':''):'-', pc);
  row('手数料', feeAmt!==null?'$'+Number(feeAmt).toFixed(4)+(r.fee_amount===null?' (概算)':''):'-');
  row('FR', r.funding_rate!==null?r.funding_rate:'-');
  row('注文ID', r.exchange_order_id||'-');
  h+='</table></div></div>';
  document.body.insertAdjacentHTML('beforeend',h);
}
function closeTradeDetail(e){
  if(e&&e.target.id!=='trade-modal-overlay')return;
  var m=document.getElementById('trade-modal-overlay');if(m)m.remove();
}

loadBotList();
loadTrades();
</script>
'''
    return _page('trades', 'Trades', html)


# ========== Portfolios Page ==========

@app.route('/portfolios')
def portfolios_page():
    """ポートフォリオ管理ページ — Paper: シミュレーション / Live: 実績閲覧"""

    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    import html as html_mod
    _db = HistoricalDB()
    _pm = PortfolioManager(_db)

    portfolios = _pm.list_all()
    bot_list = []
    config = {}
    try:
        config = get_config()
        bot_list = sorted(config.get('bots', {}).keys())
    except Exception:
        pass

    # 設定画面でlive稼働中のBot一覧を取得
    live_bots = []
    bots_section = config.get('bots', {})
    for bname in bot_list:
        bmode = (bots_section.get(bname) or {}).get('mode', 'disabled')
        if bmode == 'live':
            live_bots.append(bname)

    # 各Paperポートフォリオのbalance + 割当Bot（liveタイプはDB管理しない）
    pf_data = []
    for p in portfolios:
        if p.get('portfolio_type') == 'live':
            continue  # 旧liveデータはスキップ
        bal = _pm.get_balance(p['id'])
        bots = _pm.get_bots(p['id'])
        pf_data.append({'p': p, 'bal': bal, 'bots': bots})

    # ── Liveセクション（DB不要、設定から直接描画）──
    live_html = ''
    if live_bots:
        bot_tags = ''.join(
            f'<span style="display:inline-block;padding:3px 10px;background:var(--bg);border:1px solid var(--border);border-radius:4px;font-size:0.82em;margin:2px">{get_display_name(b)}</span>'
            for b in live_bots)
        live_html = f'''<div class="pf-card pf-card-live">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <h3 style="margin:0">Live Trading</h3>
            <span class="badge" style="background:#e74c3c">LIVE</span>
          </div>
          <div style="font-size:0.85em;color:var(--muted);margin-bottom:6px">
            設定画面でライブ稼働中のBot。操作は設定画面から行ってください。
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">{bot_tags}</div>
          <p style="font-size:0.8em;color:var(--muted);margin:0">
            実績はダッシュボードの保有ポジション・取引履歴で確認できます
          </p>
        </div>'''

    # ── PaperカードHTML生成 ──
    cards_html = ''
    for item in pf_data:
        p = item['p']
        b = item['bal']
        assigned = item['bots']
        pid = p['id']

        pnl_color = 'green' if b['total_pnl'] >= 0 else 'red'
        pnl_sign = '+' if b['total_pnl'] >= 0 else ''
        u_color = 'green' if b['unrealized_pnl'] >= 0 else 'red'
        safe_name = html_mod.escape(p['name'])
        js_name = p['name'].replace("'", "\\'").replace('"', '&quot;')

        bot_cbs = ''
        for bot in bot_list:
            chk = 'checked' if bot in assigned else ''
            bot_cbs += f'<label class="pf-bot-label"><input type="checkbox" name="bots_{pid}" value="{bot}" {chk}> {get_display_name(bot)}</label>'

        cards_html += f'''<div class="pf-card" id="pf-{pid}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <h3 style="margin:0">{safe_name}</h3>
            <div style="display:flex;gap:6px;align-items:center">
              <span class="badge" style="background:var(--accent)">PAPER</span>
              <span style="color:var(--muted);font-size:0.8em">{(p.get('created_at',''))[:10]}</span></div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px;padding:8px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin-bottom:8px">
            <div><div style="font-size:0.7em;color:var(--muted)">原資</div><div style="font-weight:bold">${b['initial_capital']:,.0f}</div></div>
            <div><div style="font-size:0.7em;color:var(--muted)">残高</div><div style="font-weight:bold">${b['current_balance']:,.0f}</div></div>
            <div><div style="font-size:0.7em;color:var(--muted)">確定損益</div><div style="font-weight:bold;color:var(--{pnl_color})">{pnl_sign}${b['total_pnl']}</div></div>
            <div><div style="font-size:0.7em;color:var(--muted)">含み損益</div><div style="font-weight:bold;color:var(--{u_color})">${b['unrealized_pnl']}</div></div>
            <div><div style="font-size:0.7em;color:var(--muted)">損益率</div><div style="font-weight:bold;color:var(--{pnl_color})">{pnl_sign}{b['pnl_pct']}%</div></div>
            <div><div style="font-size:0.7em;color:var(--muted)">勝率</div><div style="font-weight:bold">{b['win_rate']}% ({b['closed_trades']}件)</div></div>
          </div>
          <div style="font-size:0.85em;color:var(--muted);font-weight:bold;margin-bottom:4px">Bot割当:</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">{bot_cbs}</div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:8px">
            <button onclick="pfSave({pid})" style="padding:5px 14px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer">保存</button>
            <button onclick="pfReset({pid},'{js_name}')" style="padding:5px 14px;background:var(--orange);border:none;color:#fff;border-radius:4px;cursor:pointer">リセット</button>
            <button onclick="pfDelete({pid},'{js_name}')" style="padding:5px 14px;background:var(--red);border:none;color:#fff;border-radius:4px;cursor:pointer">削除</button>
            <span id="pf-msg-{pid}" style="font-size:0.85em"></span>
          </div>
        </div>'''

    if not cards_html and not live_html:
        cards_html = '<p style="color:var(--muted)">ポートフォリオがありません。下のフォームから作成してください。</p>'

    html = f'''
<style>
.pf-card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px}}
.pf-card:hover{{border-color:var(--accent)}}
.pf-card-live{{border-left:3px solid #e74c3c}}
.pf-bot-label{{display:inline-flex;align-items:center;gap:4px;cursor:pointer;padding:3px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;font-size:0.82em}}
</style>

<div class="card">
  <h2>ポートフォリオ管理</h2>
  <p style="color:var(--muted);font-size:0.85em;margin-bottom:12px">
    Paper: Botを自由に組み合わせてシミュレーション / Live: 設定画面のライブBotの実績を自動表示
  </p>
  {live_html}
  <div id="portfolio-list">{cards_html}</div>

  <div style="margin-top:16px;padding:12px;background:var(--bg);border-radius:8px;border:1px solid var(--border)">
    <h3 style="margin:0 0 8px 0;font-size:1em">Paperポートフォリオ作成</h3>
    <form id="create-form" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <div>
        <div style="font-size:0.75em;color:var(--muted);margin-bottom:2px">名前</div>
        <input type="text" name="pf_name" required placeholder="例: Alpha+Surge テスト" style="padding:8px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:4px;width:220px">
      </div>
      <div>
        <div style="font-size:0.75em;color:var(--muted);margin-bottom:2px">初期資金 (USD)</div>
        <input type="number" name="pf_capital" value="10000" min="1" step="1" style="padding:8px;background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:4px;width:120px">
      </div>
      <button type="submit" style="padding:8px 24px;background:var(--accent);border:none;color:#fff;border-radius:4px;cursor:pointer;font-weight:bold">+ 新規作成</button>
      <span id="pf-result" style="font-size:0.85em"></span>
    </form>
  </div>
</div>

<script>
// Paper新規作成
document.getElementById('create-form').onsubmit = function(e) {{
  e.preventDefault();
  var f = this;
  var name = f.pf_name.value.trim();
  var cap = parseFloat(f.pf_capital.value) || 10000;
  var result = document.getElementById('pf-result');
  if (!name) {{ result.innerHTML = '<span style="color:var(--red)">名前を入力</span>'; return; }}
  result.innerHTML = '<span style="color:var(--muted)">作成中...</span>';
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/portfolios');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.onload = function() {{
    if (xhr.status === 200) {{
      var d = JSON.parse(xhr.responseText);
      if (d.error) {{ result.innerHTML = '<span style="color:var(--red)">' + d.error + '</span>'; return; }}
      result.innerHTML = '<span style="color:var(--green)">作成完了!</span>';
      setTimeout(function(){{ location.reload(); }}, 500);
    }} else {{
      result.innerHTML = '<span style="color:var(--red)">エラー: HTTP ' + xhr.status + '</span>';
    }}
  }};
  xhr.onerror = function() {{ result.innerHTML = '<span style="color:var(--red)">通信エラー</span>'; }};
  xhr.send(JSON.stringify({{name: name, initial_capital: cap, portfolio_type: 'paper'}}));
}};

// Paper Bot保存
function pfSave(pid) {{
  var cbs = document.querySelectorAll('input[name="bots_' + pid + '"]:checked');
  var bots = [];
  for (var i = 0; i < cbs.length; i++) bots.push(cbs[i].value);
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/portfolios/' + pid + '/bots');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.onload = function() {{ pfMsg(pid, '保存完了!', 'green'); }};
  xhr.onerror = function() {{ pfMsg(pid, '通信エラー', 'red'); }};
  xhr.send(JSON.stringify({{bots: bots}}));
}}

// リセット
function pfReset(pid, name) {{
  var input = prompt('リセットすると全取引履歴が削除されます。\\nポートフォリオ名「' + name + '」を入力:');
  if (input !== name) {{ alert('名前が一致しません'); return; }}
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/portfolios/' + pid + '/reset');
  xhr.onload = function() {{ pfMsg(pid, 'リセット完了', 'green'); setTimeout(function(){{ location.reload(); }}, 1000); }};
  xhr.send();
}}

// 削除
function pfDelete(pid, name) {{
  var input = prompt('完全削除すると復元できません。\\nポートフォリオ名「' + name + '」を入力:');
  if (input !== name) {{ alert('名前が一致しません'); return; }}
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/portfolios/' + pid + '/delete');
  xhr.onload = function() {{ location.reload(); }};
  xhr.send();
}}

function pfMsg(pid, text, color) {{
  var el = document.getElementById('pf-msg-' + pid);
  if (el) {{ el.innerHTML = '<span style="color:var(--' + color + ')">' + text + '</span>'; setTimeout(function(){{ el.innerHTML = ''; }}, 3000); }}
}}
</script>
'''
    return _page('portfolios', 'ポートフォリオ', html)


# ========== Trade & Portfolio & Risk API Endpoints ==========

@app.route('/api/trades')
def api_trades():
    """トレード履歴取得（フィルター・ページネーション対応）"""
    from src.core.trade_recorder import TradeRecorder
    from src.data.database import HistoricalDB
    db = HistoricalDB()
    tr = TradeRecorder(db)
    return jsonify(tr.get_trades(
        mode=request.args.get('mode'),
        bot_name=request.args.get('bot_name'),
        symbol=request.args.get('symbol'),
        portfolio_id=int(request.args['portfolio_id']) if request.args.get('portfolio_id') else None,
        status=request.args.get('status'),
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'),
        limit=int(request.args.get('limit', 50)),
        offset=int(request.args.get('offset', 0)),
    ))


@app.route('/api/trades/stats')
def api_trades_stats():
    """パフォーマンス統計"""
    from src.core.trade_recorder import TradeRecorder
    from src.data.database import HistoricalDB
    db = HistoricalDB()
    tr = TradeRecorder(db)
    return jsonify(tr.get_performance_stats(
        mode=request.args.get('mode'),
        bot_name=request.args.get('bot_name'),
        portfolio_id=int(request.args['portfolio_id']) if request.args.get('portfolio_id') else None,
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'),
    ))


@app.route('/api/trades/daily_pnl')
def api_trades_daily_pnl():
    """日次PNL推移"""
    from src.core.trade_recorder import TradeRecorder
    from src.data.database import HistoricalDB
    db = HistoricalDB()
    tr = TradeRecorder(db)
    return jsonify(tr.get_daily_pnl(
        portfolio_id=int(request.args['portfolio_id']) if request.args.get('portfolio_id') else None,
        mode=request.args.get('mode'),
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'),
    ))


@app.route('/api/trades/export_csv')
def api_trades_export_csv():
    """CSVエクスポート"""
    from src.core.trade_recorder import TradeRecorder
    from src.data.database import HistoricalDB
    import tempfile
    db = HistoricalDB()
    tr = TradeRecorder(db)
    filepath = tempfile.mktemp(suffix='.csv')
    count = tr.export_trades_csv(filepath,
        mode=request.args.get('mode'),
        bot_name=request.args.get('bot_name'))
    if count == 0:
        return jsonify({'error': 'no trades'}), 404
    from flask import send_file
    return send_file(filepath, as_attachment=True,
                     download_name=f'trades_{datetime.now().strftime("%Y%m%d")}.csv')


@app.route('/api/portfolios', methods=['GET', 'POST'])
def api_portfolios():
    """ポートフォリオ一覧 / 作成"""
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    db = HistoricalDB()
    pm = PortfolioManager(db)

    if request.method == 'GET':
        return jsonify(pm.list_all(include_archived=request.args.get('archived') == 'true'))

    data = request.get_json(silent=True) or {}
    try:
        result = pm.create(
            name=data.get('name', ''),
            initial_capital=float(data.get('initial_capital', 10000)),
            description=data.get('description', ''),
            portfolio_type=data.get('portfolio_type', 'paper'),
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolios/<int:pid>/balance')
def api_portfolio_balance(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())
    return jsonify(pm.get_balance(pid))


@app.route('/api/portfolios/<int:pid>/bots', methods=['GET', 'POST'])
def api_portfolio_bots(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())

    if request.method == 'GET':
        return jsonify(pm.get_bots(pid))

    data = request.get_json(silent=True) or {}
    pm.assign_bots(pid, data.get('bots', []))
    return jsonify({'success': True})


@app.route('/api/portfolios/<int:pid>/update', methods=['POST'])
def api_portfolio_update(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())
    data = request.get_json(silent=True) or {}
    pm.update(pid, **data)
    return jsonify({'success': True})


@app.route('/api/portfolios/<int:pid>/archive', methods=['POST'])
def api_portfolio_archive(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())
    pm.archive(pid)
    return jsonify({'success': True})


@app.route('/api/portfolios/<int:pid>/delete', methods=['POST'])
def api_portfolio_delete(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())
    pm.delete(pid)
    return jsonify({'success': True})


@app.route('/api/portfolios/<int:pid>/reset', methods=['POST'])
def api_portfolio_reset(pid):
    from src.core.portfolio_manager import PortfolioManager
    from src.data.database import HistoricalDB
    pm = PortfolioManager(HistoricalDB())
    pm.reset(pid)
    return jsonify({'success': True})


@app.route('/api/portfolios/<int:pid>/daily_pnl')
def api_portfolio_daily_pnl(pid):
    from src.core.trade_recorder import TradeRecorder
    from src.data.database import HistoricalDB
    tr = TradeRecorder(HistoricalDB())
    return jsonify(tr.get_daily_pnl(portfolio_id=pid))


@app.route('/api/risk/events')
def api_risk_events():
    from src.core.risk_manager import RiskManager
    from src.data.database import HistoricalDB
    db = HistoricalDB()
    rm = RiskManager(db)
    pid = int(request.args['portfolio_id']) if request.args.get('portfolio_id') else None
    return jsonify(rm.get_events(portfolio_id=pid))


@app.route('/api/settings/risk_management', methods=['GET', 'POST'])
def api_settings_risk_management():
    from src.core.config_manager import ConfigManager
    cm = ConfigManager()
    if request.method == 'GET':
        return jsonify(cm.get_risk_management())
    data = request.get_json(silent=True) or {}
    try:
        cm.update_risk_management(data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/activity/logs')
def api_activity_logs():
    """Bot活動ログ取得"""
    from src.core.bot_activity_logger import BotActivityLogger
    from src.data.database import HistoricalDB
    al = BotActivityLogger(HistoricalDB())
    return jsonify(al.get_logs(
        bot_name=request.args.get('bot_name'),
        event_type=request.args.get('event_type'),
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'),
        limit=int(request.args.get('limit', 200)),
    ))


@app.route('/api/activity/summary')
def api_activity_summary():
    """Bot活動サマリー"""
    from src.core.bot_activity_logger import BotActivityLogger
    from src.data.database import HistoricalDB
    al = BotActivityLogger(HistoricalDB())
    hours = int(request.args.get('hours', 24))
    return jsonify(al.get_summary(hours=hours))


@app.route('/api/activity/export_csv')
def api_activity_export_csv():
    """Bot活動ログCSVエクスポート"""
    from src.core.bot_activity_logger import BotActivityLogger
    from src.data.database import HistoricalDB
    import tempfile
    al = BotActivityLogger(HistoricalDB())
    filepath = tempfile.mktemp(suffix='.csv')
    count = al.export_csv(filepath,
        bot_name=request.args.get('bot_name'),
        event_type=request.args.get('event_type'),
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'))
    if count == 0:
        return jsonify({'error': 'データなし'}), 404
    from flask import send_file
    return send_file(filepath, as_attachment=True,
                     download_name=f'bot_activity_{datetime.now().strftime("%Y%m%d")}.csv')


@app.route('/api/activity/report_html')
def api_activity_report_html():
    """Bot活動HTMLレポート生成"""
    from src.core.bot_activity_logger import BotActivityLogger
    from src.data.database import HistoricalDB
    al = BotActivityLogger(HistoricalDB())
    hours = int(request.args.get('hours', 12))
    html = al.generate_html_report(hours=hours)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


def main():
    """スタンドアロン起動"""
    config = get_config()
    dc = config.get('dashboard', {})
    host = dc.get('host', '127.0.0.1')
    port = dc.get('port', 8080)
    print(f"Empire Monitor Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
