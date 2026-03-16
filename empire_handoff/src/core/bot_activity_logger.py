"""Bot活動ログ — 発火・エントリー・決済・SL/TPヒットを記録、CSV/HTMLレポート生成"""
import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from src.core.bot_display_names import get_display_name

logger = logging.getLogger("empire")


class BotActivityLogger:
    """Bot活動をDBに記録し、CSV出力・HTMLレポート生成を行う"""

    def __init__(self, db):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        conn = self.db._get_conn()
        conn.execute('''CREATE TABLE IF NOT EXISTS bot_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            symbol TEXT,
            side TEXT,
            leverage REAL,
            entry_price REAL,
            exit_price REAL,
            tp_price REAL,
            sl_price REAL,
            pnl_pct REAL,
            pnl_amount REAL,
            exit_reason TEXT,
            mode TEXT DEFAULT 'paper',
            session_id TEXT,
            details TEXT
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_activity_ts ON bot_activity_log(timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_activity_bot ON bot_activity_log(bot_name)')
        conn.commit()
        conn.close()

    # ── ログ記録 ──

    def log_signal(self, bot_name: str, symbol: str, side: str, leverage: float,
                   entry_price: float, tp_price: float = 0, sl_price: float = 0,
                   mode: str = 'paper', session_id: str = '', details: str = ''):
        """シグナル発火（エントリー）を記録"""
        self._insert('signal', bot_name, symbol=symbol, side=side, leverage=leverage,
                     entry_price=entry_price, tp_price=tp_price, sl_price=sl_price,
                     mode=mode, session_id=session_id, details=details)

    def log_exit(self, bot_name: str, symbol: str, side: str, entry_price: float,
                 exit_price: float, pnl_pct: float, pnl_amount: float = 0,
                 exit_reason: str = '', mode: str = 'paper', session_id: str = '',
                 leverage: float = 0):
        """決済を記録"""
        self._insert('exit', bot_name, symbol=symbol, side=side, leverage=leverage,
                     entry_price=entry_price, exit_price=exit_price,
                     pnl_pct=pnl_pct, pnl_amount=pnl_amount,
                     exit_reason=exit_reason, mode=mode, session_id=session_id)

    def log_event(self, bot_name: str, event_type: str, details: str = '',
                  symbol: str = '', mode: str = 'paper', session_id: str = ''):
        """任意イベントを記録（起動、停止、エラー等）"""
        self._insert(event_type, bot_name, symbol=symbol, mode=mode,
                     session_id=session_id, details=details)

    def _insert(self, event_type: str, bot_name: str, **kwargs):
        conn = self.db._get_conn()
        conn.execute(
            '''INSERT INTO bot_activity_log
               (timestamp, bot_name, event_type, symbol, side, leverage,
                entry_price, exit_price, tp_price, sl_price,
                pnl_pct, pnl_amount, exit_reason, mode, session_id, details)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (datetime.now().isoformat(), bot_name, event_type,
             kwargs.get('symbol', ''), kwargs.get('side', ''),
             kwargs.get('leverage', 0), kwargs.get('entry_price', 0),
             kwargs.get('exit_price', 0), kwargs.get('tp_price', 0),
             kwargs.get('sl_price', 0), kwargs.get('pnl_pct', 0),
             kwargs.get('pnl_amount', 0), kwargs.get('exit_reason', ''),
             kwargs.get('mode', 'paper'), kwargs.get('session_id', ''),
             kwargs.get('details', ''))
        )
        conn.commit()
        conn.close()

    # ── クエリ ──

    def get_logs(self, bot_name: str = None, event_type: str = None,
                 date_from: str = None, date_to: str = None,
                 limit: int = 200) -> List[dict]:
        conn = self.db._get_conn()
        sql = "SELECT * FROM bot_activity_log WHERE 1=1"
        params = []
        if bot_name:
            sql += " AND bot_name=?"
            params.append(bot_name)
        if event_type:
            sql += " AND event_type=?"
            params.append(event_type)
        if date_from:
            sql += " AND timestamp>=?"
            params.append(date_from)
        if date_to:
            sql += " AND timestamp<=?"
            params.append(date_to)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM bot_activity_log LIMIT 0").description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]

    def get_summary(self, hours: int = 24) -> dict:
        """直近N時間のサマリー"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self.db._get_conn()
        signals = conn.execute(
            "SELECT bot_name, COUNT(*) FROM bot_activity_log WHERE event_type='signal' AND timestamp>=? GROUP BY bot_name",
            (since,)
        ).fetchall()
        exits = conn.execute(
            "SELECT bot_name, COUNT(*), "
            "SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN exit_reason LIKE '%SL%' OR exit_reason LIKE '%stop_loss%' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN exit_reason LIKE '%TP%' OR exit_reason LIKE '%take_profit%' THEN 1 ELSE 0 END), "
            "SUM(pnl_pct), SUM(pnl_amount) "
            "FROM bot_activity_log WHERE event_type='exit' AND timestamp>=? GROUP BY bot_name",
            (since,)
        ).fetchall()
        conn.close()

        bot_stats = {}
        for bot, count in signals:
            bot_stats.setdefault(bot, {})['signals'] = count
        for bot, count, wins, sl_hits, tp_hits, total_pnl_pct, total_pnl_amt in exits:
            s = bot_stats.setdefault(bot, {})
            s['exits'] = count
            s['wins'] = wins or 0
            s['sl_hits'] = sl_hits or 0
            s['tp_hits'] = tp_hits or 0
            s['total_pnl_pct'] = round(total_pnl_pct or 0, 2)
            s['total_pnl_amount'] = round(total_pnl_amt or 0, 2)

        return bot_stats

    # ── CSV出力 ──

    def export_csv(self, filepath: str, **filters) -> int:
        logs = self.get_logs(**filters)
        if not logs:
            return 0
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=logs[0].keys())
            writer.writeheader()
            writer.writerows(logs)
        return len(logs)

    # ── HTMLレポート生成 ──

    def generate_html_report(self, hours: int = 12) -> str:
        """直近N時間のHTMLレポートを生成"""
        now = datetime.now()
        since = (now - timedelta(hours=hours)).isoformat()
        logs = self.get_logs(date_from=since, limit=500)
        summary = self.get_summary(hours=hours)

        # サマリーテーブル
        summary_rows = ''
        total_pnl = 0
        for bot, stats in sorted(summary.items()):
            signals = stats.get('signals', 0)
            exits = stats.get('exits', 0)
            wins = stats.get('wins', 0)
            sl = stats.get('sl_hits', 0)
            tp = stats.get('tp_hits', 0)
            pnl = stats.get('total_pnl_pct', 0)
            total_pnl += pnl
            wr = f'{wins/exits*100:.0f}%' if exits > 0 else '-'
            pnl_cls = 'green' if pnl >= 0 else 'red'
            summary_rows += f'''<tr>
                <td><strong>{bot}</strong></td>
                <td>{signals}</td><td>{exits}</td><td>{wr}</td>
                <td>{tp}</td><td>{sl}</td>
                <td style="color:{pnl_cls}"><strong>{pnl:+.2f}%</strong></td>
            </tr>'''

        # ログ詳細テーブル
        log_rows = ''
        for log in logs[:100]:
            ts = log['timestamp'][:19].replace('T', ' ')
            evt = log['event_type']
            sym = (log['symbol'] or '').replace('/USDT:USDT', '').replace('_USDT', '')
            pnl = log.get('pnl_pct') or 0
            pnl_str = f'{pnl:+.2f}%' if evt == 'exit' else ''
            pnl_cls = 'green' if pnl >= 0 else 'red'
            reason = log.get('exit_reason', '') or ''
            side = log.get('side', '')
            lev = f"{log.get('leverage', 0):.0f}x" if log.get('leverage') else ''
            entry_p = f"${log['entry_price']:,.6f}" if log.get('entry_price') else ''
            exit_p = f"${log['exit_price']:,.6f}" if log.get('exit_price') else ''
            mode = log.get('mode', '')

            evt_badge = {
                'signal': '<span style="background:#0d6efd;color:#fff;padding:2px 6px;border-radius:3px;font-size:0.8em">発火</span>',
                'exit': '<span style="background:#dc3545;color:#fff;padding:2px 6px;border-radius:3px;font-size:0.8em">決済</span>',
                'start': '<span style="background:#198754;color:#fff;padding:2px 6px;border-radius:3px;font-size:0.8em">起動</span>',
                'error': '<span style="background:#ffc107;color:#000;padding:2px 6px;border-radius:3px;font-size:0.8em">エラー</span>',
            }.get(evt, f'<span style="background:#6c757d;color:#fff;padding:2px 6px;border-radius:3px;font-size:0.8em">{evt}</span>')

            log_rows += f'''<tr>
                <td style="white-space:nowrap">{ts}</td>
                <td>{log['bot_name']}</td>
                <td>{evt_badge}</td>
                <td>{mode}</td>
                <td><strong>{sym}</strong></td>
                <td>{side} {lev}</td>
                <td>{entry_p}</td><td>{exit_p}</td>
                <td style="color:{pnl_cls}">{pnl_str}</td>
                <td>{reason}</td>
            </tr>'''

        total_cls = 'green' if total_pnl >= 0 else 'red'
        period = f'{now.strftime("%Y-%m-%d %H:%M")} (直近{hours}時間)'

        html = f'''<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><title>Bot Activity Report</title>
<style>
body{{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}}
h1,h2{{color:#58a6ff}}
table{{width:100%;border-collapse:collapse;margin-bottom:20px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #21262d;font-size:0.9em}}
th{{background:#161b22;color:#8b949e;text-transform:uppercase;font-size:0.8em}}
tr:hover{{background:rgba(88,166,255,0.05)}}
.green{{color:#3fb950}} .red{{color:#f85149}}
.summary-card{{display:inline-block;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 24px;margin:8px;text-align:center}}
.summary-card .value{{font-size:1.8em;font-weight:bold}}
.summary-card .label{{color:#8b949e;font-size:0.85em}}
</style></head>
<body>
<h1>Bot Activity Report</h1>
<p style="color:#8b949e">{period}</p>

<div>
<div class="summary-card"><div class="label">合計シグナル</div><div class="value">{sum(s.get("signals",0) for s in summary.values())}</div></div>
<div class="summary-card"><div class="label">合計決済</div><div class="value">{sum(s.get("exits",0) for s in summary.values())}</div></div>
<div class="summary-card"><div class="label">合計PNL</div><div class="value {total_cls}">{total_pnl:+.2f}%</div></div>
</div>

<h2>Bot別サマリー</h2>
<table>
<tr><th>Bot</th><th>シグナル</th><th>決済</th><th>勝率</th><th>TP</th><th>SL</th><th>PNL</th></tr>
{summary_rows}
</table>

<h2>活動ログ詳細</h2>
<table>
<tr><th>時間</th><th>Bot</th><th>イベント</th><th>モード</th><th>銘柄</th><th>方向</th><th>エントリー</th><th>決済値</th><th>PNL</th><th>理由</th></tr>
{log_rows}
</table>

<p style="color:#8b949e;font-size:0.8em;margin-top:30px">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} JST</p>
</body></html>'''
        return html

    def generate_telegram_summary(self, hours: int = 12) -> str:
        """Telegram送信用テキストサマリー"""
        summary = self.get_summary(hours=hours)
        if not summary:
            return ''

        lines = [f'📊 <b>Bot活動レポート (直近{hours}h)</b>', '']
        total_pnl = 0
        for bot, stats in sorted(summary.items()):
            signals = stats.get('signals', 0)
            exits = stats.get('exits', 0)
            wins = stats.get('wins', 0)
            sl = stats.get('sl_hits', 0)
            tp = stats.get('tp_hits', 0)
            pnl = stats.get('total_pnl_pct', 0)
            total_pnl += pnl
            wr = f'{wins/exits*100:.0f}%' if exits > 0 else '-'
            pnl_str = f'{pnl:+.2f}%'
            emoji = '🟢' if pnl >= 0 else '🔴'
            lines.append(f'{emoji} <b>{get_display_name(bot)}</b>: {signals}発火 → {exits}決済 (勝率{wr}) TP:{tp} SL:{sl} PNL:{pnl_str}')
        total_emoji = '📈' if total_pnl >= 0 else '📉'
        lines.append(f'\n{total_emoji} <b>合計PNL: {total_pnl:+.2f}%</b>')
        lines.append(f'⏰ {datetime.now().strftime("%Y-%m-%d %H:%M")}')
        return '\n'.join(lines)
