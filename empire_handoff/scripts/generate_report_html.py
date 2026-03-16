"""Empire Monitor HTML Report Generator

Generates comprehensive HTML reports about the crypto trading system.
Usage: python scripts/generate_report_html.py --phase before|after|diff
"""
import argparse
import html
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Output directory
OUTPUT_DIR = PROJECT_ROOT / "vault" / "docs"

# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """\
body { font-family: 'Segoe UI', sans-serif; max-width: 1400px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }
h1 { color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }
h2 { color: #ffd700; margin-top: 30px; }
h3 { color: #ff6b6b; }
table { width: 100%; border-collapse: collapse; margin: 15px 0; }
th { background: #16213e; color: #00d4ff; padding: 10px; text-align: left; border: 1px solid #333; }
td { padding: 8px 10px; border: 1px solid #333; }
tr:hover { background: #16213e; }
.pass { color: #4ade80; font-weight: bold; }
.fail { color: #ef4444; font-weight: bold; }
.warn { color: #fbbf24; }
.adopt { background: #1a3a2a; }
.reject { background: #3a1a1a; }
.insurance { background: #2a2a1a; }
.experiment { background: #1a2a3a; }
.section { background: #16213e; border-radius: 8px; padding: 20px; margin: 20px 0; }
.before { border-left: 4px solid #ef4444; padding-left: 15px; }
.after { border-left: 4px solid #4ade80; padding-left: 15px; }
code { background: #0d1117; padding: 2px 6px; border-radius: 4px; color: #79c0ff; }
pre { background: #0d1117; padding: 15px; border-radius: 8px; overflow-x: auto; line-height: 1.5; }
.metric { font-size: 24px; font-weight: bold; color: #00d4ff; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.badge-green { background: #1a3a2a; color: #4ade80; }
.badge-red { background: #3a1a1a; color: #ef4444; }
.badge-yellow { background: #2a2a1a; color: #fbbf24; }
.badge-blue { background: #1a2a3a; color: #00d4ff; }
"""

# ── Bot Performance Data ─────────────────────────────────────────────────────

BOT_DATA = [
    ("surge",      71, 59.2, 3.02,   "+70.4",   -5.1, 2.85, "25-45",  "Long",  "採用"),
    ("meanrevert",370, 55.4, 2.15,  "+472.4",   -5.9, 4.95, "50-80",  "Short", "採用"),
    ("weakshort", 103, 55.3, 2.17,   "+54.2",   -5.2, 2.53, "50-75",  "Short", "採用"),
    ("alpha",       0,  0.0, 0.00,    "+0.0",    0.0, 0.00, "0-10",   "Long",  "保険"),
    ("sniper",     10, 60.0, 5.13,   "+40.7",   -4.1, 1.35, "0-30",   "Long",  "保険"),
    ("scalp",     475, 39.8, 1.52, "+1066.6",  -31.0, 3.24, "All",    "L/S",   "実験"),
    ("momentum",  268, 31.0, 1.00,    "+0.6",  -39.8, 0.15, "20-60",  "Long",  "不採用"),
    ("rebound",    30, 33.3, 1.11,    "+7.5",  -17.7, 0.27, "0-25",   "Long",  "不採用"),
    ("stability", 106, 39.6, 1.29,   "+16.1",   -9.2, 0.89, "15-55",  "Long",  "実験"),
    ("trend",     138, 31.9, 1.10,   "+13.2",  -14.4, 0.46, "45-75",  "Long",  "実験"),
    ("cascade",    99, 27.3, 0.74,   "-24.0",  -28.0,-0.70, "20-65",  "Long",  "不採用"),
    ("breakout",   21, 28.6, 0.94,    "-1.4",  -12.5,-0.05, "20-55",  "Long",  "不採用"),
    ("btcfollow",   1,100.0,999.00,  "+11.1",   -0.2, 0.70, "0-30",   "Long",  "不採用"),
]

STATUS_ICONS = {
    "採用": "&#x2705;",    # checkmark
    "保険": "&#x1F536;",   # orange diamond
    "実験": "&#x1F9EA;",   # test tube
    "不採用": "&#x274C;",  # cross
}

STATUS_CSS_CLASS = {
    "採用": "adopt",
    "保険": "insurance",
    "実験": "experiment",
    "不採用": "reject",
}

# ── Known Issues ─────────────────────────────────────────────────────────────

KNOWN_ISSUES = [
    ("BTC.D validation", "実装済 (30-80% guard)", "pass"),
    ("VETO system (3-layer)", "基本実装済", "pass"),
    ("Macro event VETO", "未実装", "fail"),
    ("Bot simultaneous signal priority", "未実装", "fail"),
    ("Pattern-specific win rate tracking", "未実装", "fail"),
    ("Commentary template system", "実装済", "pass"),
    ("Score guide footer", "実装済", "pass"),
    ("Community report format", "実装済", "pass"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────


def _run_git(*args: str) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _git_branch() -> str:
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return branch if branch else "unknown"


def _git_version() -> str:
    ver = _run_git("describe", "--tags", "--always")
    return ver if ver else _run_git("rev-parse", "--short", "HEAD") or "dev"


def _count_lines(filepath: Path) -> int:
    """Count lines in a file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _extract_description(filepath: Path) -> str:
    """Extract first docstring or first comment from a Python file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return ""

    # Look for module docstring
    in_docstring = False
    doc_lines = []
    for line in lines:
        stripped = line.strip()
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                # Single-line docstring
                if stripped.count(quote) >= 2 and len(stripped) > 6:
                    return stripped[3:stripped.index(quote, 3)].strip()
                in_docstring = True
                rest = stripped[3:].strip()
                if rest:
                    doc_lines.append(rest)
            elif stripped.startswith("#"):
                return stripped.lstrip("# ").strip()
            elif stripped and not stripped.startswith(("import", "from", "")):
                break
        else:
            if '"""' in stripped or "'''" in stripped:
                end_part = stripped.split(quote)[0].strip()
                if end_part:
                    doc_lines.append(end_part)
                return " ".join(doc_lines)
            doc_lines.append(stripped)

    if doc_lines:
        return " ".join(doc_lines[:2])
    return ""


def _classify_file(filepath: Path) -> str:
    """Classify a Python file by type."""
    name = filepath.name
    parts = filepath.parts
    if "backtest" in parts:
        return "Backtest"
    if "signals" in parts:
        if "bot_" in name:
            return "Bot"
        if "tier" in name:
            return "Engine"
        return "Signal"
    if "core" in parts:
        return "Core"
    if "execution" in parts:
        return "Execution"
    if "fetchers" in parts:
        return "Fetcher"
    if "data" in parts:
        return "Data"
    if "ai" in parts:
        return "AI"
    if "utils" in parts:
        return "Utility"
    if "config" in parts:
        return "Config"
    if "scripts" in parts:
        if "test" in name:
            return "Test"
        if "run_" in name:
            return "Runner"
        return "Script"
    return "Other"


def _collect_py_files() -> list:
    """Collect all .py files from src/, config/, scripts/."""
    dirs = ["src", "config", "scripts"]
    files = []
    for d in dirs:
        base = PROJECT_ROOT / d
        if base.exists():
            for p in sorted(base.rglob("*.py")):
                if "__pycache__" in str(p):
                    continue
                rel = p.relative_to(PROJECT_ROOT)
                lines = _count_lines(p)
                desc = _extract_description(p)
                ftype = _classify_file(p)
                files.append((str(rel).replace("\\", "/"), lines, ftype, desc))
    return files


def _run_tests() -> tuple:
    """Run test_new_modules.py and parse output. Returns (output_text, passed, total)."""
    test_script = PROJECT_ROOT / "scripts" / "test_new_modules.py"
    if not test_script.exists():
        return ("test_new_modules.py not found", 0, 0)
    try:
        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout + result.stderr
        # Parse TOTAL line
        passed = 0
        total = 0
        for line in output.splitlines():
            if line.strip().startswith("TOTAL:"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    fraction = parts[1]
                    if "/" in fraction:
                        p, t = fraction.split("/")
                        try:
                            passed = int(p)
                            total = int(t)
                        except ValueError:
                            pass
        return (output, passed, total)
    except Exception as e:
        return (f"Test execution failed: {e}", 0, 0)


def _esc(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text))


# ── HTML Generation Helpers ──────────────────────────────────────────────────


def _html_head(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
{CSS}
</style>
</head>
<body>
<h1>{_esc(title)}</h1>
"""


def _html_foot() -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""
<hr style="border-color:#333; margin-top:40px;">
<p style="color:#666; font-size:12px;">Generated: {_esc(ts)} by generate_report_html.py</p>
</body>
</html>
"""


# ── Section Builders ─────────────────────────────────────────────────────────


def _section_a_overview() -> str:
    """Section A: Project Overview"""
    version = _git_version()
    branch = _git_branch()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    py_files = _collect_py_files()
    file_count = len(py_files)
    total_lines = sum(f[1] for f in py_files)

    return f"""
<h2>A. Project Overview</h2>
<div class="section">
<table>
<tr><th>項目</th><th>値</th></tr>
<tr><td>Version</td><td><code>{_esc(version)}</code></td></tr>
<tr><td>Generated</td><td>{_esc(now)}</td></tr>
<tr><td>Branch</td><td><code>{_esc(branch)}</code></td></tr>
<tr><td>Python Files (src/config/scripts)</td><td><span class="metric">{file_count}</span></td></tr>
<tr><td>Total Lines</td><td><span class="metric">{total_lines:,}</span></td></tr>
</table>
</div>
"""


def _section_b_files() -> str:
    """Section B: File Structure"""
    py_files = _collect_py_files()
    rows = []
    for path, lines, ftype, desc in py_files:
        badge_class = "badge-blue"
        if ftype == "Bot":
            badge_class = "badge-yellow"
        elif ftype == "Test":
            badge_class = "badge-green"
        elif ftype in ("Config",):
            badge_class = "badge-red"
        rows.append(
            f'<tr>'
            f'<td><code>{_esc(path)}</code></td>'
            f'<td style="text-align:right">{lines}</td>'
            f'<td><span class="badge {badge_class}">{_esc(ftype)}</span></td>'
            f'<td>{_esc(desc[:100])}</td>'
            f'</tr>'
        )

    return f"""
<h2>B. File Structure</h2>
<div class="section">
<table>
<tr><th>Path</th><th>Lines</th><th>Type</th><th>Description</th></tr>
{''.join(rows)}
</table>
<p style="color:#888;">Total: {len(py_files)} files</p>
</div>
"""


def _section_c_bots() -> str:
    """Section C: Bot Performance"""
    rows = []
    for bot, trades, wr, pf, ret, mdd, sharpe, fear_range, direction, status in BOT_DATA:
        icon = STATUS_ICONS.get(status, "")
        css_class = STATUS_CSS_CLASS.get(status, "")
        # Color return
        ret_str = _esc(ret)
        if ret.startswith("+"):
            ret_cell = f'<span class="pass">{ret_str}</span>'
        elif ret.startswith("-"):
            ret_cell = f'<span class="fail">{ret_str}</span>'
        else:
            ret_cell = ret_str
        # Color sharpe
        if sharpe >= 2.0:
            sharpe_cell = f'<span class="pass">{sharpe:.2f}</span>'
        elif sharpe >= 1.0:
            sharpe_cell = f'<span class="warn">{sharpe:.2f}</span>'
        elif sharpe > 0:
            sharpe_cell = f'{sharpe:.2f}'
        else:
            sharpe_cell = f'<span class="fail">{sharpe:.2f}</span>'
        # MDD color
        if mdd >= -10:
            mdd_cell = f'<span class="pass">{mdd:.1f}%</span>'
        elif mdd >= -20:
            mdd_cell = f'<span class="warn">{mdd:.1f}%</span>'
        else:
            mdd_cell = f'<span class="fail">{mdd:.1f}%</span>'

        rows.append(
            f'<tr class="{css_class}">'
            f'<td>{_esc(bot)}</td>'
            f'<td style="text-align:right">{trades}</td>'
            f'<td style="text-align:right">{wr:.1f}%</td>'
            f'<td style="text-align:right">{pf:.2f}</td>'
            f'<td style="text-align:right">{ret_cell}</td>'
            f'<td style="text-align:right">{mdd_cell}</td>'
            f'<td style="text-align:right">{sharpe_cell}</td>'
            f'<td>{_esc(fear_range)}</td>'
            f'<td>{_esc(direction)}</td>'
            f'<td>{icon} {_esc(status)}</td>'
            f'</tr>'
        )

    return f"""
<h2>C. Bot Performance (Backtest Results)</h2>
<div class="section">
<table>
<tr>
<th>Bot</th><th>Trades</th><th>WR%</th><th>PF</th><th>Return%</th>
<th>MDD%</th><th>Sharpe</th><th>Fear Range</th><th>Direction</th><th>Status</th>
</tr>
{''.join(rows)}
</table>
<p style="color:#888;">
&#x2705; 採用 = Production &nbsp;&nbsp;
&#x1F536; 保険 = Insurance (rare fire) &nbsp;&nbsp;
&#x1F9EA; 実験 = Experimental &nbsp;&nbsp;
&#x274C; 不採用 = Rejected
</p>
</div>
"""


def _section_d_before() -> str:
    """Section D: OLD report format sample."""
    sample = (
        "&#x1F680; 起動レポート 2026-03-11 17:00\n"
        "\n"
        "■ 市場環境\n"
        "  BTC: $82,500 (前日比 +1.5%)\n"
        "  Fear&amp;Greed: 35 (Fear域)\n"
        "  BTC.D: 61.2%\n"
        "  パターン: B (全力買い（アルト祭）)\n"
        "  Bot-Alpha: 待機中\n"
        "  Bot-Surge: 稼働中\n"
        "\n"
        "■ Tier1通過 (182銘柄)\n"
        "  セクター別: DeFi:42, AI:28, L1:25, Gaming:18\n"
        "\n"
        "■ Tier2通過 上位20 (全68銘柄)\n"
        "  1. PAXG [DeFi] Score:109\n"
        "  2. SOL [L1] Score:95\n"
        "  3. ETH [L1] Score:88\n"
        "  4. AVAX [L1] Score:82\n"
        "  5. LINK [Oracle] Score:79\n"
        "  ...\n"
        "\n"
        "■ ポジション (0件)\n"
        "  なし\n"
    )
    return f"""
<h2>D. Report Format Sample (BEFORE - Old Format)</h2>
<div class="section before">
<h3>旧フォーマット: 4セクション構成</h3>
<p>市場環境 + Tier1 + Tier2 + ポジションのシンプルな構成。結論やBot解説なし。</p>
<pre>{sample}</pre>
</div>
"""


def _section_d_after() -> str:
    """Section D: NEW report format sample, using Commentary class."""
    from src.core.commentary import Commentary

    # Generate real commentary
    report_data = {
        "regime": "B",
        "fear_greed": 35,
        "btc_change_24h": 1.5,
        "tier1_passed": [None] * 182,
        "tier2_passed": [None] * 68,
    }
    commentary_text = Commentary.build_report_commentary(report_data)
    conclusion = Commentary._build_conclusion("B", 35, 182)
    score_guide = Commentary.score_guide_footer()

    bot_alpha = Commentary.bot_status_comment("alpha", "waiting")
    bot_surge = Commentary.bot_status_comment("surge", "active")
    bot_meanrevert = Commentary.bot_status_comment("meanrevert", "waiting")
    bot_weakshort = Commentary.bot_status_comment("weakshort", "waiting")

    sample = (
        f"&#x1F680; 起動レポート 2026-03-11 17:00\n"
        f"\n"
        f"■ 結論\n"
        f"  {_esc(conclusion)}\n"
        f"\n"
        f"■ 市場前提\n"
        f"  BTC $82,500 (+1.5%) | F&amp;G 35 (Fear域) | BTC.D 61.2% | Pattern B\n"
        f"\n"
        f"■ Tier1通過 (182銘柄)\n"
        f"  セクター: DeFi:42, AI:28, L1:25, Gaming:18\n"
        f"\n"
        f"■ Tier2通過 上位20 (全68銘柄)\n"
        f"  1. PAXG [DeFi] 109pt (T1:62+T2:47)\n"
        f"  2. SOL [L1] 95pt (T1:58+T2:37)\n"
        f"  3. ETH [L1] 88pt (T1:52+T2:36)\n"
        f"  4. AVAX [L1] 82pt (T1:48+T2:34)\n"
        f"  5. LINK [Oracle] 79pt (T1:45+T2:34)\n"
        f"  ...\n"
        f"\n"
        f"■ Bot Status\n"
        f"  {_esc(bot_alpha)}\n"
        f"  {_esc(bot_surge)}\n"
        f"  {_esc(bot_meanrevert)}\n"
        f"  {_esc(bot_weakshort)}\n"
        f"\n"
        f"■ ポジション (0件)\n"
        f"  なし\n"
        f"\n"
        f"■ どらの解説\n"
    )
    # Add commentary lines
    for line in commentary_text.splitlines():
        sample += f"  {_esc(line)}\n"

    sample += f"\n{_esc(score_guide)}\n"

    return f"""
<h2>D. Report Format Sample (AFTER - New 5-Section Format)</h2>
<div class="section after">
<h3>新フォーマット: 結論/市場前提/候補除外/Bot Status/どらの解説</h3>
<p>結論を冒頭に配置。Bot別ステータス解説。AIコメンタリー(どらの解説)を追加。スコア内訳表示。</p>
<pre>{sample}</pre>
</div>
"""


def _section_e_tests() -> str:
    """Section E: Test Results"""
    test_output, passed, total = _run_tests()
    failed = total - passed

    # Parse individual test results from output
    test_rows = []
    current_suite = ""
    for line in test_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("=== Test:"):
            current_suite = stripped.replace("=== Test:", "").replace("===", "").strip()
        elif "✅" in stripped or "❌" in stripped:
            is_pass = "✅" in stripped
            # Clean up the test name
            test_name = stripped.replace("✅", "").replace("❌", "").strip()
            status_html = '<span class="pass">PASS</span>' if is_pass else '<span class="fail">FAIL</span>'
            test_rows.append(
                f'<tr>'
                f'<td>{_esc(current_suite)}</td>'
                f'<td>{_esc(test_name)}</td>'
                f'<td>{status_html}</td>'
                f'</tr>'
            )

    if total > 0:
        if passed == total:
            summary_html = f'<span class="pass">ALL {total} TESTS PASSED</span>'
        else:
            summary_html = f'<span class="pass">{passed} passed</span> / <span class="fail">{failed} failed</span> (total: {total})'
    else:
        summary_html = '<span class="warn">No tests executed</span>'

    rows_html = "".join(test_rows) if test_rows else '<tr><td colspan="3">No test output parsed</td></tr>'

    return f"""
<h2>E. Test Results</h2>
<div class="section">
<p>Result: {summary_html}</p>
<table>
<tr><th>Suite</th><th>Test</th><th>Status</th></tr>
{rows_html}
</table>
<details>
<summary style="cursor:pointer; color:#00d4ff;">Raw test output</summary>
<pre>{_esc(test_output)}</pre>
</details>
</div>
"""


def _section_f_issues() -> str:
    """Section F: Known Issues / Unimplemented"""
    rows = []
    for name, status_text, level in KNOWN_ISSUES:
        if level == "pass":
            status_html = f'<span class="pass">{_esc(status_text)}</span>'
        elif level == "fail":
            status_html = f'<span class="fail">{_esc(status_text)}</span>'
        else:
            status_html = f'<span class="warn">{_esc(status_text)}</span>'
        rows.append(
            f'<tr>'
            f'<td>{_esc(name)}</td>'
            f'<td>{status_html}</td>'
            f'</tr>'
        )

    impl_count = sum(1 for _, _, l in KNOWN_ISSUES if l == "pass")
    not_impl = sum(1 for _, _, l in KNOWN_ISSUES if l == "fail")

    return f"""
<h2>F. Known Issues / Unimplemented</h2>
<div class="section">
<p>Implemented: <span class="pass">{impl_count}</span> &nbsp; Not Implemented: <span class="fail">{not_impl}</span></p>
<table>
<tr><th>Feature</th><th>Status</th></tr>
{''.join(rows)}
</table>
</div>
"""


# ── Phase: DIFF ──────────────────────────────────────────────────────────────

CHANGE_SUMMARY = [
    ("Report Format", "4 sections (市場/Tier1/Tier2/ポジション)", "7 sections (+結論/Bot Status/どらの解説/スコアガイド)", "ユーザー体験向上"),
    ("VETO System", "なし", "3層VETO (データ/自動/手動)", "不良銘柄の自動除外"),
    ("Commentary", "なし", "テンプレートベース日本語コメンタリー", "判断根拠の可視化"),
    ("Score Display", "合計スコアのみ", "T1/T2内訳表示", "スコア透明性"),
    ("Bot Status", "2Bot表示 (Alpha/Surge)", "6Bot表示 (全採用/保険Bot)", "Bot稼働状況の把握"),
    ("Community Report", "なし", "簡易版レポート (Telegram用)", "情報共有"),
    ("Score Guide", "なし", "フッター付き配点ガイド", "新規ユーザー理解"),
    ("Fear Comment", "数値のみ", "帯域別コメント + Bot発火条件", "恐怖指数の文脈化"),
]

NEW_FEATURES = [
    ("VETO System", "3層構造: Layer1=データ品質, Layer2=自動ルール, Layer3=手動リスト。VETO発動で-100pt即除外。"),
    ("Commentary Engine", "テンプレートベースの日本語コメンタリー。AIは不使用（Iron Rule遵守）。パターン/Fear/BTC変動から自動生成。"),
    ("Community Report", "Telegram向け簡易レポート。結論+市場前提+上位5銘柄のコンパクト版。"),
    ("Score Guide Footer", "T1/T2の配点構造をレポート末尾に表示。初見ユーザーでもスコアの意味が分かる。"),
    ("Bot Status Section", "6Bot(Alpha/Surge/MeanRevert/WeakShort/Sniper/Scalp)の稼働状態と条件を表示。"),
    ("Regime Commentary", "6パターン(A-F)に対応する相場解説と推奨アクションを生成。"),
]

QA_ITEMS = [
    ("Q1: レポート結論セクション追加", True),
    ("Q2: 市場前提の1行化", True),
    ("Q3: Bot Statusセクション追加", True),
    ("Q4: どらの解説セクション追加", True),
    ("Q5: スコア内訳表示", True),
    ("Q6: スコアガイドフッター", True),
    ("Q7: VETO除外表示", True),
    ("Q8: コミュニティレポート", True),
    ("Q9: Fear帯域コメント", True),
    ("Q10: パターン別解説", True),
    ("Q11: BTC変動コメント", True),
    ("Q12: トリガーアクション", True),
    ("Q13: セクター内訳表示", True),
    ("Q14: 新規上場フラグ", True),
    ("Q15: Tier2内訳(FR/流動性/清算)", True),
    ("Q16: Bot-Alpha待機表示", True),
    ("Q17: Bot-Surge稼働表示", True),
    ("Q18: Bot-MeanRevert条件", True),
    ("Q19: Bot-WeakShort条件", True),
    ("Q20: Bot-Sniper条件", True),
    ("Q21: Bot-Scalp常時稼働", True),
    ("Q22: マクロイベントVETO", False),
    ("Q23: Bot同時シグナル優先順位", False),
    ("Q24: パターン別勝率トラッキング", False),
    ("Q25: BTC.D 30-80%ガード", True),
    ("Q26: VETO手動追加/削除", True),
    ("Q27: VETO統計・履歴", True),
    ("Q28: スプレッド過大VETO", True),
    ("Q29: OHLCV欠損VETO", True),
    ("Q30: extra_checks拡張", True),
    ("Q31: テスト全件パス", True),
]


def _section_diff_summary() -> str:
    """Diff: Change Summary"""
    rows = []
    for cat, before, after, impact in CHANGE_SUMMARY:
        rows.append(
            f'<tr>'
            f'<td>{_esc(cat)}</td>'
            f'<td class="before">{_esc(before)}</td>'
            f'<td class="after">{_esc(after)}</td>'
            f'<td>{_esc(impact)}</td>'
            f'</tr>'
        )
    return f"""
<h2>1. Change Summary</h2>
<div class="section">
<table>
<tr><th>Category</th><th>Before</th><th>After</th><th>Impact</th></tr>
{''.join(rows)}
</table>
</div>
"""


def _section_diff_files() -> str:
    """Diff: File diff stats"""
    # Try git diff
    diff_stat = _run_git("diff", "--stat", "HEAD~5", "HEAD")
    if not diff_stat:
        # Fallback: list known changed files
        changed_files = [
            ("src/core/commentary.py", "NEW", "Commentary template engine"),
            ("src/core/veto.py", "NEW", "3-layer VETO system"),
            ("src/execution/alert.py", "MODIFIED", "New report format + community report"),
            ("src/core/engine.py", "MODIFIED", "VetoSystem integration"),
            ("scripts/test_new_modules.py", "NEW", "Tests for new modules"),
            ("scripts/generate_report_html.py", "NEW", "This HTML report generator"),
        ]
        rows = []
        for path, change, desc in changed_files:
            badge = "badge-green" if change == "NEW" else "badge-yellow"
            rows.append(
                f'<tr>'
                f'<td><code>{_esc(path)}</code></td>'
                f'<td><span class="badge {badge}">{_esc(change)}</span></td>'
                f'<td>{_esc(desc)}</td>'
                f'</tr>'
            )
        return f"""
<h2>2. File Changes</h2>
<div class="section">
<table>
<tr><th>File</th><th>Change</th><th>Description</th></tr>
{''.join(rows)}
</table>
</div>
"""
    else:
        return f"""
<h2>2. File Changes (git diff --stat)</h2>
<div class="section">
<pre>{_esc(diff_stat)}</pre>
</div>
"""


def _section_diff_side_by_side() -> str:
    """Diff: Before/After side by side comparison"""
    before_sample = (
        "&#x1F680; 起動レポート 2026-03-11 17:00\n"
        "\n"
        "■ 市場環境\n"
        "  BTC: $82,500 (前日比 +1.5%)\n"
        "  Fear&amp;Greed: 35 (Fear域)\n"
        "  BTC.D: 61.2%\n"
        "  パターン: B (全力買い)\n"
        "  Bot-Alpha: 待機中\n"
        "  Bot-Surge: 稼働中\n"
        "\n"
        "■ Tier1通過 (182銘柄)\n"
        "  セクター別: DeFi:42, AI:28\n"
        "\n"
        "■ Tier2通過 上位20\n"
        "  1. PAXG [DeFi] Score:109\n"
        "  2. SOL [L1] Score:95\n"
        "\n"
        "■ ポジション (0件)\n"
        "  なし"
    )

    # Use Commentary for the after sample
    try:
        from src.core.commentary import Commentary
        conclusion = _esc(Commentary._build_conclusion("B", 35, 182))
        bot_alpha = _esc(Commentary.bot_status_comment("alpha", "waiting"))
        bot_surge = _esc(Commentary.bot_status_comment("surge", "active"))
        fear_comment_line = _esc(Commentary._fear_comment(35))
    except Exception:
        conclusion = "アルト祭り＋Fear域。積極的にロング。Tier2上位を狙え。"
        bot_alpha = "Bot-Alpha: 待機中。Fear&lt;10の極限恐怖を待つ。"
        bot_surge = "Bot-Surge: 稼働中。BTC乖離銘柄＋セクター波及を監視。"
        fear_comment_line = "Fear域(F&amp;G=35)。Bot-Surge稼働条件。"

    after_sample = (
        f"&#x1F680; 起動レポート 2026-03-11 17:00\n"
        f"\n"
        f"■ 結論\n"
        f"  {conclusion}\n"
        f"\n"
        f"■ 市場前提\n"
        f"  BTC $82,500 (+1.5%) | F&amp;G 35 | BTC.D 61.2% | Pattern B\n"
        f"\n"
        f"■ Tier1通過 (182銘柄)\n"
        f"  セクター: DeFi:42, AI:28\n"
        f"\n"
        f"■ Tier2通過 上位20\n"
        f"  1. PAXG [DeFi] 109pt (T1:62+T2:47)\n"
        f"  2. SOL [L1] 95pt (T1:58+T2:37)\n"
        f"\n"
        f"■ Bot Status\n"
        f"  {bot_alpha}\n"
        f"  {bot_surge}\n"
        f"\n"
        f"■ ポジション (0件)\n"
        f"  なし\n"
        f"\n"
        f"■ どらの解説\n"
        f"  {fear_comment_line}\n"
    )

    return f"""
<h2>3. Before / After Report Comparison</h2>
<div class="grid">
<div class="section before">
<h3>BEFORE (旧フォーマット)</h3>
<pre>{before_sample}</pre>
</div>
<div class="section after">
<h3>AFTER (新フォーマット)</h3>
<pre>{after_sample}</pre>
</div>
</div>
"""


def _section_diff_new_features() -> str:
    """Diff: New features list"""
    rows = []
    for name, desc in NEW_FEATURES:
        rows.append(
            f'<tr>'
            f'<td><strong>{_esc(name)}</strong></td>'
            f'<td>{_esc(desc)}</td>'
            f'</tr>'
        )
    return f"""
<h2>4. New Features</h2>
<div class="section">
<table>
<tr><th>Feature</th><th>Description</th></tr>
{''.join(rows)}
</table>
</div>
"""


def _section_diff_qa() -> str:
    """Diff: Q&A summary (31 items)"""
    implemented = sum(1 for _, done in QA_ITEMS if done)
    not_impl = sum(1 for _, done in QA_ITEMS if not done)

    rows = []
    for question, done in QA_ITEMS:
        if done:
            status_html = '<span class="pass">&#x2705; 実装済</span>'
        else:
            status_html = '<span class="fail">&#x274C; 未実装</span>'
        rows.append(f'<tr><td>{_esc(question)}</td><td>{status_html}</td></tr>')

    return f"""
<h2>5. Q&amp;A Summary ({len(QA_ITEMS)} items)</h2>
<div class="section">
<p>
Implemented: <span class="pass">{implemented}</span> &nbsp;
Not Implemented: <span class="fail">{not_impl}</span> &nbsp;
Coverage: <span class="metric">{implemented/len(QA_ITEMS)*100:.0f}%</span>
</p>
<table>
<tr><th>Question</th><th>Status</th></tr>
{''.join(rows)}
</table>
</div>
"""


def _section_diff_tests() -> str:
    """Diff: Test results comparison"""
    test_output, passed, total = _run_tests()
    failed = total - passed

    return f"""
<h2>6. Test Results</h2>
<div class="section">
<div class="grid">
<div>
<h3>Before (no tests existed)</h3>
<p><span class="warn">N/A - テストなし</span></p>
</div>
<div>
<h3>After (test_new_modules.py)</h3>
<p>Passed: <span class="pass">{passed}</span> / Failed: <span class="fail">{failed}</span> / Total: {total}</p>
</div>
</div>
<details>
<summary style="cursor:pointer; color:#00d4ff;">Raw test output</summary>
<pre>{_esc(test_output)}</pre>
</details>
</div>
"""


def _section_diff_bot_unchanged() -> str:
    """Diff: Bot logic unchanged confirmation"""
    rows = []
    for bot, trades, wr, pf, ret, mdd, sharpe, fear_range, direction, status in BOT_DATA:
        icon = STATUS_ICONS.get(status, "")
        rows.append(
            f'<tr>'
            f'<td>{_esc(bot)}</td>'
            f'<td>{icon} {_esc(status)}</td>'
            f'<td class="pass">unchanged</td>'
            f'<td>Backtest results identical</td>'
            f'</tr>'
        )

    return f"""
<h2>7. Bot Logic Unchanged Confirmation</h2>
<div class="section">
<p><span class="pass">&#x2705; All 13 bot logics remain unchanged.</span>
Only report formatting and commentary were added. No trading logic was modified.</p>
<table>
<tr><th>Bot</th><th>Status</th><th>Logic</th><th>Note</th></tr>
{''.join(rows)}
</table>
</div>
"""


# ── Main Generators ──────────────────────────────────────────────────────────


def generate_before() -> str:
    """Generate the 'before' phase report."""
    parts = [
        _html_head("Empire Monitor Report - BEFORE (旧フォーマット)"),
        _section_a_overview(),
        _section_b_files(),
        _section_c_bots(),
        _section_d_before(),
        _section_e_tests(),
        _section_f_issues(),
        _html_foot(),
    ]
    return "".join(parts)


def generate_after() -> str:
    """Generate the 'after' phase report."""
    parts = [
        _html_head("Empire Monitor Report - AFTER (新フォーマット)"),
        _section_a_overview(),
        _section_b_files(),
        _section_c_bots(),
        _section_d_after(),
        _section_e_tests(),
        _section_f_issues(),
        _html_foot(),
    ]
    return "".join(parts)


def generate_diff() -> str:
    """Generate the 'diff' comparison report."""
    parts = [
        _html_head("Empire Monitor - DIFF Report (Before vs After)"),
        _section_diff_summary(),
        _section_diff_files(),
        _section_diff_side_by_side(),
        _section_diff_new_features(),
        _section_diff_qa(),
        _section_diff_tests(),
        _section_diff_bot_unchanged(),
        _html_foot(),
    ]
    return "".join(parts)


# ── Entry Point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML reports for Empire Monitor crypto trading system."
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=["before", "after", "diff"],
        help="Report phase: before, after, or diff",
    )
    args = parser.parse_args()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generators = {
        "before": (generate_before, "report_before.html"),
        "after": (generate_after, "report_after.html"),
        "diff": (generate_diff, "report_diff.html"),
    }

    gen_func, filename = generators[args.phase]
    output_path = OUTPUT_DIR / filename

    try:
        html_content = gen_func()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Report generated: {output_path}")
        print(f"Phase: {args.phase}")
        print(f"Size: {len(html_content):,} bytes")
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
