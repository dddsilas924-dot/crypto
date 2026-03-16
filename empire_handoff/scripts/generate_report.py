"""バックテストレポート生成: HTML + 埋め込みグラフ"""
import base64
import io
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# 日本語フォント設定
try:
    from matplotlib import font_manager
    jp_fonts = [f.name for f in font_manager.fontManager.ttflist
                if any(k in f.name for k in ["Yu Gothic", "Meiryo", "MS Gothic", "Hiragino"])]
    if jp_fonts:
        plt.rcParams["font.family"] = jp_fonts[0]
    else:
        plt.rcParams["font.family"] = "sans-serif"
except Exception:
    plt.rcParams["font.family"] = "sans-serif"

plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
BT_DIR = VAULT / "backtest_results"
WF_DIR = BT_DIR / "walkforward"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def fig_to_base64(fig, dpi=120):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def style_chart(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor("#16213e")
    ax.figure.set_facecolor("#1a1a2e")
    ax.set_title(title, color="white", fontsize=13, fontweight="bold", pad=10)
    ax.set_xlabel(xlabel, color="#aaa", fontsize=10)
    ax.set_ylabel(ylabel, color="#aaa", fontsize=10)
    ax.tick_params(colors="#aaa", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#444")
    ax.spines["left"].set_color("#444")
    ax.grid(True, alpha=0.15, color="#888")


COLORS = ["#4361ee", "#06d6a0", "#ef476f", "#ffd166", "#118ab2",
          "#8338ec", "#ff6b6b", "#48bfe3", "#72efdd", "#f8961e"]

# ═══════════════════════════════════════════════
# データ読込
# ═══════════════════════════════════════════════

lev_df = pd.read_csv(BT_DIR / "leverage_test_results.csv")
bot_ab_df = pd.read_csv(BT_DIR / "bot_ab_results.csv")
full_df = pd.read_csv(BT_DIR / "full_analysis_10patterns.csv")
grid_top5 = pd.read_csv(BT_DIR / "grid_top5.csv")
quarterly_df = pd.read_csv(BT_DIR / "quarterly_top5_comparison.csv")
four_src_df = pd.read_csv(BT_DIR / "4source_experiment.csv")
hybrid_df = pd.read_csv(BT_DIR / "hybrid_experiment.csv")
wf_df = pd.read_csv(WF_DIR / "walkforward_summary.csv")
grid_s2_df = pd.read_csv(BT_DIR / "grid_stage2_all.csv")
t5t9_df = pd.read_csv(BT_DIR / "t5t9_comparison.csv")

# ═══════════════════════════════════════════════
# ロジック数カウント
# ═══════════════════════════════════════════════

logics_dir = VAULT / "logics"
s_count = len(list(logics_dir.glob("S*_*.md")))
e_count = len(list(logics_dir.glob("E*_*.md")))
t_count = len(list(logics_dir.glob("T*_*.md")))
other_count = (len(list(logics_dir.glob("V*_*.md")))
               + len(list(logics_dir.glob("M*_*.md")))
               + len(list(logics_dir.glob("N*_*.md")))
               + len(list(logics_dir.glob("X*_*.md"))))
total_logics = s_count + e_count + t_count + other_count

tested_patterns = (
    len(four_src_df) + len(hybrid_df) + len(grid_s2_df)
    + len(bot_ab_df) + len(lev_df)
)

# ═══════════════════════════════════════════════
# グラフ1: 四半期PnL推移（折れ線）
# ═══════════════════════════════════════════════

quarters = [q for q in quarterly_df["Quarter"].tolist() if q != "TOTAL"]
q_data = quarterly_df[quarterly_df["Quarter"] != "TOTAL"]

fig1, ax1 = plt.subplots(figsize=(14, 5))
style_chart(ax1, "四半期PnL%推移（Top5パターン）", "四半期", "PnL %")

patterns_q = [c for c in q_data.columns if c != "Quarter"]
for i, p in enumerate(patterns_q):
    vals = q_data[p].astype(float).tolist()
    ax1.plot(range(len(quarters)), vals, marker="o", markersize=4,
             label=p, color=COLORS[i % len(COLORS)], linewidth=1.5)

ax1.axhline(0, color="#666", linestyle="--", linewidth=0.8)
ax1.set_xticks(range(len(quarters)))
ax1.set_xticklabels(quarters, rotation=45, ha="right", fontsize=8)
ax1.legend(loc="upper left", fontsize=8, facecolor="#16213e",
           edgecolor="#444", labelcolor="white")
chart1_b64 = fig_to_base64(fig1)

# ═══════════════════════════════════════════════
# グラフ2: Return% 全期間 vs Q2除外（棒グラフ）
# ═══════════════════════════════════════════════

chart2_data = [
    ("S1xE16xT6", 12.4, 12.4 * (1 - 21.3/100)),
    ("S1xE16xT14", 157.9, 110.6),
    ("S1xE16xT63\n(レバ2倍)", 158.9, 112.8),
    ("S1xE16xT60\n(レバ3倍)", 574.7, 293.1),
    ("S12xE16xT50", 11.7, 10.3),
    ("S12xE16xT62\n(レバ3倍)", 63.7, 55.9),
    ("S15xE18xT33", 91.2, 91.2 * (1 - 69.0/100)),
    ("S5xE20xT33", 150.4, 150.4 * (1 - 244.2/100)),
]

fig2, ax2 = plt.subplots(figsize=(12, 5))
style_chart(ax2, "リターン%: 全期間 vs 2025Q2除外", "", "リターン %")

x = np.arange(len(chart2_data))
names = [d[0] for d in chart2_data]
full_ret = [d[1] for d in chart2_data]
exq2_ret = [d[2] for d in chart2_data]

w = 0.35
ax2.bar(x - w/2, full_ret, w, label="全期間", color="#4361ee", alpha=0.85)
ax2.bar(x + w/2, exq2_ret, w, label="Q2除外", color="#06d6a0", alpha=0.85)
ax2.axhline(0, color="#666", linestyle="--", linewidth=0.8)
ax2.set_xticks(x)
ax2.set_xticklabels(names, fontsize=8, color="#ccc")
ax2.legend(facecolor="#16213e", edgecolor="#444", labelcolor="white", fontsize=9)
chart2_b64 = fig_to_base64(fig2)

# ═══════════════════════════════════════════════
# グラフ3: レバレッジ散布図（Return% vs MDD%）
# ═══════════════════════════════════════════════

fig3, ax3 = plt.subplots(figsize=(10, 6))
style_chart(ax3, "レバレッジテスト: リターン% vs 最大DD%", "最大DD %", "リターン %")

bot_a_lev = lev_df[lev_df["Pattern"].str.startswith("A")]
bot_b_lev = lev_df[lev_df["Pattern"].str.startswith("B")]

ax3.scatter(bot_a_lev["MDD%"], bot_a_lev["Return%"], c="#4361ee", s=100,
            label="BOT-A (S1xE16)", zorder=5, edgecolors="white", linewidth=0.5)
ax3.scatter(bot_b_lev["MDD%"], bot_b_lev["Return%"], c="#ef476f", s=100,
            label="BOT-B (S12xE16)", zorder=5, edgecolors="white", linewidth=0.5)

for _, row in lev_df.iterrows():
    ax3.annotate(row["Pattern"], (row["MDD%"], row["Return%"]),
                 fontsize=7, color="#ddd", textcoords="offset points",
                 xytext=(5, 5))

t63_a = lev_df[lev_df["Pattern"] == "A_T63"]
if len(t63_a) > 0:
    ax3.scatter(t63_a["MDD%"], t63_a["Return%"], c="#ffd166", s=200,
                marker="*", zorder=10, label="A_T63（推奨）")

ax3.legend(facecolor="#16213e", edgecolor="#444", labelcolor="white", fontsize=9)
chart3_b64 = fig_to_base64(fig3)

# ═══════════════════════════════════════════════
# グラフ4: 2025Q2依存度（棒グラフ）
# ═══════════════════════════════════════════════

dep_data = [
    ("P01 ベースライン\nS1xE16xT6", 21.8),
    ("P04 リターン王\nS1xE16xT14", 19.3),
    ("P05 品質王\nS15xE18xT12", 69.0),
    ("P07 S12ベスト\nS12xE16xT6", 11.0),
    ("P10 S5多取引\nS5xE16xT31", 244.2),
    ("A_T63\nS1xE16xT63", 29.0),
    ("B_T62\nS12xE16xT62", 12.2),
]

fig4, ax4 = plt.subplots(figsize=(11, 5))
style_chart(ax4, "2025年Q2依存度（%）", "", "依存度 %")

x4 = np.arange(len(dep_data))
names4 = [d[0] for d in dep_data]
vals4 = [d[1] for d in dep_data]
bar_colors = ["#06d6a0" if v < 30 else "#ffd166" if v < 70 else "#ef476f" for v in vals4]
ax4.bar(x4, vals4, color=bar_colors, alpha=0.85, edgecolor="#333")
ax4.axhline(30, color="#ffd166", linestyle="--", linewidth=0.8, alpha=0.6)
ax4.axhline(100, color="#ef476f", linestyle="--", linewidth=0.8, alpha=0.6)
ax4.set_xticks(x4)
ax4.set_xticklabels(names4, fontsize=7, color="#ccc")
for i, v in enumerate(vals4):
    ax4.text(i, v + 3, f"{v}%", ha="center", fontsize=8, color="#ddd")
chart4_b64 = fig_to_base64(fig4)

# ═══════════════════════════════════════════════
# グラフ5: ウォークフォワード OOS棒グラフ
# ═══════════════════════════════════════════════

wf_oos = wf_df[wf_df["Type"] == "OOS"]
fig5, ax5 = plt.subplots(figsize=(10, 4))
style_chart(ax5, "ウォークフォワード OOSリターン%（S1xE16xT63）", "ウィンドウ", "リターン %")

wf_colors = ["#06d6a0" if r > 0 else "#ef476f" for r in wf_oos["Return%"]]
ax5.bar(range(len(wf_oos)), wf_oos["Return%"].tolist(), color=wf_colors, alpha=0.85, edgecolor="#333")
ax5.axhline(0, color="#666", linestyle="--", linewidth=0.8)
ax5.set_xticks(range(len(wf_oos)))
ax5.set_xticklabels([f"W{i+1}" for i in range(len(wf_oos))], fontsize=9, color="#ccc")
for i, row in enumerate(wf_oos.itertuples()):
    ax5.text(i, row._8 + 2, f"{row._8:.1f}%", ha="center", fontsize=8, color="#ddd")
chart5_b64 = fig_to_base64(fig5)


# ═══════════════════════════════════════════════
# HTML組み立て
# ═══════════════════════════════════════════════

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 主要パターン比較テーブルデータ
main_table = [
    # (パターン, 分類, S, E, T, レバ, Pos%, 実質%, 取引数, WR%, PF, Return%, MDD%, MaxSDD%, PF_exQ2, Ret%_exQ2, 依存度%)
    # BOT-A候補群
    ("S1xE16xT6", "BOT-A 安全型", "S1", "E16", "T6", 1.0, 15, 15, 29, 62.1, 1.94, 12.4, 4.9, -2.76, 2.09, 9.8, 21.3),
    ("S1xE16xT14", "BOT-A 標準型", "S1", "E16", "T14", 1.0, 80, 80, 29, 51.7, 2.32, 157.9, 23.3, -14.74, 2.09, 110.6, 29.9),
    ("S1xE16xT63", "BOT-A 推奨", "S1", "E16", "T63", 2.0, 50, 100, 29, 55.2, 2.13, 158.9, 30.7, -18.42, 1.96, 112.8, 29.0),
    ("S1xE16xT60", "BOT-A 攻撃型", "S1", "E16", "T60", 3.0, 80, 240, 29, 51.7, 2.32, 574.7, 63.7, -44.21, 2.09, 293.1, 49.0),
    ("S1xE16xT65", "BOT-A 限界型", "S1", "E16", "T65", 3.0, 100, 300, 29, 51.7, 2.32, 597.7, 75.4, -55.26, 2.09, 264.6, 55.7),
    # BOT-B候補群
    ("S12xE16xT6", "BOT-B 安全型", "S12", "E16", "T6", 1.0, 15, 15, 58, 50.0, 1.35, 11.7, 14.2, -3.52, 1.35, 10.3, 11.6),
    ("S12xE16xT63", "BOT-B レバ2倍", "S12", "E16", "T63", 2.0, 50, 100, 58, 44.8, 1.38, 70.0, 64.9, -23.45, 1.36, 53.1, 24.1),
    ("S12xE16xT62", "BOT-B レバ3倍30%", "S12", "E16", "T62", 3.0, 30, 90, 58, 50.0, 1.39, 63.7, 61.5, -21.1, 1.39, 55.9, 12.2),
    # 高スコア群
    ("S15xE18xT33", "グリッド1位", "S15", "E18", "T33", 1.0, 50, 50, 21, 57.1, 3.11, 91.2, 24.5, -10.55, "-", "-", 69.0),
    ("S15xE18xT31", "グリッド5位", "S15", "E18", "T31", 1.0, 20, 20, 21, 57.1, 3.11, 33.9, 10.4, -4.22, "-", "-", "-"),
    ("S5xE20xT33", "グリッド2位", "S5", "E20", "T33", 1.0, 50, 50, 234, 36.3, 1.33, 150.4, 61.0, -11.72, "-", "-", 244.2),
]


def build_main_table_html():
    rows_html = []
    for r in main_table:
        pattern, source, s, e, t, lev, pos, eff, trades, wr, pf, ret, mdd, msdd, pf_exq2, ret_exq2, dep = r
        if isinstance(pf, (int, float)):
            if pf >= 2.0:
                row_cls = "row-green"
            elif pf >= 1.5:
                row_cls = "row-lightgreen"
            elif pf < 1.0:
                row_cls = "row-red"
            else:
                row_cls = ""
        else:
            row_cls = ""

        mdd_cls = ' class="red-text"' if isinstance(mdd, (int, float)) and mdd > 50 else ""
        ret_cls = ' class="bold-text"' if isinstance(ret, (int, float)) and ret > 100 else ""

        rows_html.append(f"""<tr class="{row_cls}">
            <td>{esc(pattern)}</td><td>{esc(source)}</td>
            <td>{esc(s)}</td><td>{esc(e)}</td><td>{esc(t)}</td>
            <td>{lev}x</td><td>{pos}%</td><td>{eff}%</td>
            <td>{trades}</td><td>{wr}%</td><td>{pf}</td>
            <td{ret_cls}>{ret}%</td><td{mdd_cls}>{mdd}%</td>
            <td>{msdd}%</td>
            <td>{pf_exq2}</td><td>{ret_exq2}{'%' if isinstance(ret_exq2, (int, float)) else ''}</td>
            <td>{dep}{'%' if isinstance(dep, (int, float)) else ''}</td>
        </tr>""")
    return "\n".join(rows_html)


def build_wf_table_html():
    rows = []
    for _, r in wf_df.iterrows():
        type_cls = "oos" if r["Type"] == "OOS" else "is"
        pf_str = "inf" if r["PF"] == float("inf") or (isinstance(r["PF"], float) and r["PF"] > 100) else f"{r['PF']:.2f}"
        ret_cls = ' class="bold-text"' if r["Return%"] > 100 else ""
        rows.append(f"""<tr class="wf-{type_cls}">
            <td>{r['Window']}</td><td>{r['Period']}</td><td>{r['Type']}</td>
            <td>{int(r['Trades'])}</td><td>{r['WR%']:.1f}%</td>
            <td>{pf_str}</td><td{ret_cls}>{r['Return%']:.1f}%</td>
            <td>{r['MDD%']:.1f}%</td><td>{r['AvgPnL%']:.2f}%</td>
        </tr>""")
    return "\n".join(rows)


def build_4source_table_html():
    rows = []
    for _, r in four_src_df.iterrows():
        pf = r["PF"]
        if pf >= 2.0:
            cls = "row-green"
        elif pf >= 1.5:
            cls = "row-lightgreen"
        elif pf < 1.0:
            cls = "row-red"
        else:
            cls = ""
        rows.append(f"""<tr class="{cls}">
            <td>{esc(r['Pattern'])}</td><td>{esc(r['Source'])}</td>
            <td>{esc(r['S'])}</td><td>{esc(r['E'])}</td><td>{esc(r['T'])}</td>
            <td>{int(r['Trades'])}</td><td>{r['WR%']:.1f}%</td>
            <td>{r['PF']:.2f}</td><td>{r['Return%']:.1f}%</td>
            <td>{r['MDD%']:.1f}%</td><td>{esc(r.get('Extra', ''))}</td>
        </tr>""")
    return "\n".join(rows)


def build_gd_risk_table():
    rows = []
    for _, r in lev_df.sort_values("WorstLevLoss%").iterrows():
        loss_cls = ' class="red-text"' if r["WorstLevLoss%"] < -30 else ""
        rows.append(f"""<tr>
            <td>{r['Pattern']}</td><td>{r['Lev']}x</td><td>{r['Pos%']}%</td>
            <td>{r['実質投入%']}%</td><td>{r['WorstTrade']}</td>
            <td>{r['WorstPnL%']:.2f}%</td><td{loss_cls}>{r['WorstLevLoss%']:.2f}%</td>
            <td>{'Y' if r.get('破産', 'N') == 'Y' else 'N'}</td>
        </tr>""")
    return "\n".join(rows)


# ナレッジ対応表
knowledge_refs = [
    ("S1（先生基準）", "screening_criteria, screening_process"),
    ("E1-E8（初期エントリー）", "sma200_break, sma5_rule, entry_execution"),
    ("E16（チャンピオン）", "sma200_break, sma5_rule"),
    ("T4-T9（Exit/資金管理）", "loss_cut_rule, profit_target, sma5_rule"),
    ("T60-T65（レバレッジ）", "leverage_rule, mindset"),
    ("M1（地合い）", "nikkei_vs_smallcap, s_market_score"),
    ("N1（センチメント）", "s_pts_block, dilution_risk"),
    ("S20/S21（B2b GU制限）", "g_gu_limit（+15%ブロック）"),
    ("E20/E21（GU必須）", "g_entry（GU必須エントリー）"),
    ("T20-T25（Gemini独自）", "g_fixed_sl, g_fixed_tp, g_dd_lock"),
    ("S22（SURF）", "s_four_rules, s_board_thickness"),
    ("E30（SURF）", "s_four_rules（SMA25/75クロスオーバー）"),
]


html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>バックテストレポート - 全自動株取引マシン</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", "Segoe UI", sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.6;
    padding: 20px;
    max-width: 1400px;
    margin: 0 auto;
}}
h1 {{
    color: #4361ee;
    font-size: 2em;
    border-bottom: 3px solid #4361ee;
    padding-bottom: 10px;
    margin: 30px 0 15px;
}}
h2 {{
    color: #06d6a0;
    font-size: 1.5em;
    margin: 25px 0 10px;
    border-left: 4px solid #06d6a0;
    padding-left: 12px;
}}
h3 {{
    color: #ffd166;
    font-size: 1.15em;
    margin: 18px 0 8px;
}}
p {{ margin: 8px 0; color: #ccc; }}
.header {{
    text-align: center;
    padding: 30px 0;
    border-bottom: 2px solid #333;
    margin-bottom: 30px;
}}
.header h1 {{ border: none; font-size: 2.5em; margin: 0; }}
.header .subtitle {{ color: #888; font-size: 1.1em; margin-top: 5px; }}
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin: 20px 0;
}}
.summary-card {{
    background: #16213e;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 18px;
    text-align: center;
}}
.summary-card .num {{
    font-size: 2em;
    font-weight: bold;
    color: #4361ee;
}}
.summary-card .label {{
    color: #888;
    font-size: 0.85em;
    margin-top: 4px;
}}
.rec-box {{
    background: linear-gradient(135deg, #16213e, #1a2744);
    border: 1px solid #4361ee;
    border-radius: 8px;
    padding: 18px;
    margin: 15px 0;
}}
.rec-box .bot-name {{
    color: #4361ee;
    font-size: 1.2em;
    font-weight: bold;
}}
.rec-box .config {{
    color: #06d6a0;
    font-size: 1.1em;
    margin: 5px 0;
}}
.rec-box .detail {{ color: #aaa; font-size: 0.9em; }}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 15px 0;
    font-size: 0.85em;
    background: #16213e;
    border-radius: 8px;
    overflow: hidden;
}}
th {{
    background: #0f3460;
    color: #4cc9f0;
    padding: 10px 8px;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
    border-bottom: 2px solid #4361ee;
}}
td {{
    padding: 8px;
    border-bottom: 1px solid #222;
    white-space: nowrap;
}}
tr:nth-child(even) {{ background: #1a2744; }}
tr:hover {{ background: #243b6a !important; }}
.row-green {{ background: rgba(6, 214, 160, 0.15) !important; }}
.row-green:hover {{ background: rgba(6, 214, 160, 0.25) !important; }}
.row-lightgreen {{ background: rgba(6, 214, 160, 0.08) !important; }}
.row-red {{ background: rgba(239, 71, 111, 0.15) !important; }}
.row-red:hover {{ background: rgba(239, 71, 111, 0.25) !important; }}
.red-text {{ color: #ef476f !important; font-weight: bold; }}
.bold-text {{ font-weight: bold; color: #ffd166; }}
.wf-oos {{ background: rgba(67, 97, 238, 0.1) !important; }}
.wf-is {{ background: rgba(255, 255, 255, 0.02); }}
.timeline {{
    position: relative;
    margin: 20px 0;
    padding-left: 30px;
}}
.timeline::before {{
    content: "";
    position: absolute;
    left: 10px;
    top: 0;
    bottom: 0;
    width: 3px;
    background: linear-gradient(to bottom, #4361ee, #06d6a0);
    border-radius: 2px;
}}
.tl-item {{
    position: relative;
    margin-bottom: 20px;
    padding: 12px 18px;
    background: #16213e;
    border-radius: 8px;
    border-left: 3px solid #4361ee;
}}
.tl-item::before {{
    content: "";
    position: absolute;
    left: -26px;
    top: 16px;
    width: 12px;
    height: 12px;
    background: #4361ee;
    border-radius: 50%;
    border: 2px solid #1a1a2e;
}}
.tl-item .phase {{ color: #4361ee; font-weight: bold; font-size: 0.9em; }}
.tl-item .desc {{ color: #ccc; margin-top: 3px; }}
.tl-item .result {{ color: #06d6a0; font-size: 0.85em; margin-top: 3px; }}
.chart-container {{
    margin: 20px 0;
    text-align: center;
}}
.chart-container img {{
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid #333;
}}
.section-divider {{
    border: none;
    height: 1px;
    background: linear-gradient(to right, transparent, #4361ee, transparent);
    margin: 40px 0;
}}
.knowledge-table td:first-child {{ color: #4cc9f0; font-weight: 600; }}
.tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    margin: 1px;
}}
.tag-pass {{ background: #06d6a022; color: #06d6a0; border: 1px solid #06d6a044; }}
.tag-fail {{ background: #ef476f22; color: #ef476f; border: 1px solid #ef476f44; }}
.tag-warn {{ background: #ffd16622; color: #ffd166; border: 1px solid #ffd16644; }}
.next-steps {{
    background: #16213e;
    border: 1px solid #4361ee;
    border-radius: 8px;
    padding: 20px;
    margin: 20px 0;
}}
.next-steps li {{
    margin: 8px 0;
    padding-left: 5px;
    list-style: none;
}}
.next-steps li::before {{
    content: "\\25B6";
    color: #4361ee;
    margin-right: 8px;
    font-size: 0.8em;
}}
footer {{
    text-align: center;
    color: #555;
    padding: 30px 0 10px;
    font-size: 0.85em;
    border-top: 1px solid #333;
    margin-top: 40px;
}}
</style>
</head>
<body>

<!-- ヘッダー -->
<div class="header">
    <h1>バックテストレポート</h1>
    <div class="subtitle">全自動株取引マシン / データ期間: 2020-10 ~ 2026-03 / 生成日: 2026-03-09</div>
</div>

<!-- セクション1: エグゼクティブサマリー -->
<h1>1. エグゼクティブサマリー</h1>
<p>
テンプレート駆動型の全自動日本株売買システム。Markdownファイル内のYAMLロジックをパースし、
スクリーニング・エントリー・手仕舞い条件を動的に構築する。
5年超のデータ（2020-10 ~ 2026-03）で{tested_patterns}以上のパターン組み合わせをバックテスト。
{total_logics}個のロジックファイル（S系{s_count}個 / E系{e_count}個 / T系{t_count}個）を検証済み。
小型株（3桁銘柄、時価総額50億以下）の短期モメンタム狙い。
</p>

<div class="summary-grid">
    <div class="summary-card">
        <div class="num">{s_count}</div>
        <div class="label">スクリーニング (S系)</div>
    </div>
    <div class="summary-card">
        <div class="num">{e_count}</div>
        <div class="label">エントリー (E系)</div>
    </div>
    <div class="summary-card">
        <div class="num">{t_count}</div>
        <div class="label">トレード管理 (T系)</div>
    </div>
    <div class="summary-card">
        <div class="num">{tested_patterns}+</div>
        <div class="label">テスト済みパターン</div>
    </div>
    <div class="summary-card">
        <div class="num">5.4年</div>
        <div class="label">データ期間</div>
    </div>
    <div class="summary-card">
        <div class="num">7</div>
        <div class="label">WFウィンドウ</div>
    </div>
</div>

<h3>現時点の推奨構成</h3>
<div class="rec-box">
    <div class="bot-name">BOT-A（メイン）</div>
    <div class="config">S1 x E16 x T63（レバ2倍、ポジション50%、実質投入100%）</div>
    <div class="detail">PF=2.13 | リターン=+158.9% | MDD=30.7% | WF 5/7窓プラス | Q2依存度=29.0%</div>
</div>
<div class="rec-box">
    <div class="bot-name">BOT-B（サブ・暫定）</div>
    <div class="config">S12 x E16 x T62（レバ3倍、ポジション30%、実質投入90%）</div>
    <div class="detail">PF=1.39 | リターン=+63.7% | MDD=61.5% | Q2依存度=12.2% | 要改善</div>
</div>

<hr class="section-divider">

<!-- セクション2: ロジック進化の経緯 -->
<h1>2. ロジック進化の経緯</h1>
<div class="timeline">
    <div class="tl-item">
        <div class="phase">Phase 1: 初期エントリーテスト（E1-E8）</div>
        <div class="desc">S1スクリーニングで8種のエントリーロジックを2年データ（2024-2026）でテスト。</div>
        <div class="result">結果: E1（200MA突破＋出来高急増）が初代チャンピオン。PF=1.90</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 2: ループ改良（E9-E13）</div>
        <div class="desc">反復的にエントリー条件を改善。E10はRSIフィルタ＋モメンタム条件を追加。</div>
        <div class="result">結果: E10は2年データで王者だが、全期間では崩壊（PF=0.93）</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 3: 全期間検証（E14-E18）</div>
        <div class="desc">5年全期間データで再検証。シンプルな条件ほどロバストと判明。</div>
        <div class="result">結果: E16（200MAクロスオーバー＋RSI&le;58）= 真のチャンピオン。PF=1.94</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 4: スクリーニング比較（S1-S15）</div>
        <div class="desc">15種のS系: 先生基準(S1)、Gemini(S20-21)、SURF(S22)、複合(S5/S10/S12/S15)。</div>
        <div class="result">結果: S1（先生基準）が最高品質。S12/S15は取引量で優位。</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 5: Exit/資金管理設計（T5-T9）</div>
        <div class="desc">pos%、SL/TP比率、トレーリングストップ、最大保有日数を体系的に変動。</div>
        <div class="result">結果: T6（pos15%/SL3.5%/TP9%/TS2%）がMDD3%達成。T7（pos20%）がPF=2.0で最良。</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 6: 4ソース対照実験（A/B1/B2/C）</div>
        <div class="desc">先生(A) vs Gemini解釈(B1) vs Gemini独自(B2) vs SURF(C)の統制比較。</div>
        <div class="result">結果: 先生ベースラインが優勝。GU+15%ブロック(B2b)が有効。SURF(C) PF=0.98で失敗。</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 7: グリッドサーチ（140パターン）</div>
        <div class="desc">S x E x T フルグリッド: Stage1（12E選別）→ Stage2（上位6E x 10S x 4T）。</div>
        <div class="result">結果: S15xE18xT33がスコア1位（PF=3.11、リターン91.2%）。2025Q2依存度が深刻。</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 8: レバレッジテスト（T60-T65）</div>
        <div class="desc">レバ1.5倍〜3倍をBOT-A（S1xE16）とBOT-B（S12xE16）に適用。</div>
        <div class="result">結果: A_T63（2倍x50%）が最バランス。BOT-Aは3倍に耐える。BOT-Bは高レバで崩壊。</div>
    </div>
    <div class="tl-item">
        <div class="phase">Phase 9: ウォークフォワード検証</div>
        <div class="desc">7ローリングウィンドウ（2年IS＋6ヶ月OOS）。S1xE16xT63を未知データで検証。</div>
        <div class="result">結果: 7窓中5窓がプラス。平均OOSリターン+20.4%/半期。WR劣化率19.6%。PASS</div>
    </div>
</div>

<hr class="section-divider">

<!-- セクション3: 主要パターン比較テーブル -->
<h1>3. 主要パターン比較</h1>
<p>色分け: <span class="tag tag-pass">PF &ge; 2.0</span> <span class="tag tag-warn">PF &ge; 1.5</span> <span class="tag tag-fail">PF &lt; 1.0</span> / MDD&gt;50%は<span class="red-text">赤文字</span> / リターン&gt;100%は<span class="bold-text">太字</span></p>
<div style="overflow-x: auto;">
<table>
<thead>
<tr>
    <th>パターン</th><th>分類</th><th>S</th><th>E</th><th>T</th>
    <th>レバ</th><th>Pos%</th><th>実質%</th><th>取引数</th><th>勝率</th>
    <th>PF</th><th>リターン%</th><th>MDD%</th><th>最大単一DD%</th>
    <th>PF(Q2除)</th><th>リターン%(Q2除)</th><th>依存度%</th>
</tr>
</thead>
<tbody>
{build_main_table_html()}
</tbody>
</table>
</div>

<hr class="section-divider">

<!-- セクション4: 四半期パフォーマンス -->
<h1>4. 四半期パフォーマンス推移</h1>

<h3>Top5グリッドパターンの四半期PnL%</h3>
<div class="chart-container">
    <img src="data:image/png;base64,{chart1_b64}" alt="四半期PnLチャート">
</div>

<div style="overflow-x: auto;">
<table>
<thead>
<tr><th>四半期</th>
{"".join(f'<th>{esc(c)}</th>' for c in quarterly_df.columns if c != "Quarter")}
</tr>
</thead>
<tbody>
{"".join(
    '<tr>' + f'<td>{esc(row["Quarter"])}</td>' +
    ''.join(
        f'<td class="{"bold-text" if isinstance(row[c], (int, float)) and row[c] > 50 else "red-text" if isinstance(row[c], (int, float)) and row[c] < -20 else ""}">{row[c]:.1f}%</td>'
        if row["Quarter"] != "TOTAL"
        else f'<td class="bold-text">{row[c]:.1f}%</td>'
        for c in quarterly_df.columns if c != "Quarter"
    ) + '</tr>'
    for _, row in quarterly_df.iterrows()
)}
</tbody>
</table>
</div>

<h3>リターン%: 全期間 vs 2025Q2除外</h3>
<div class="chart-container">
    <img src="data:image/png;base64,{chart2_b64}" alt="リターン比較">
</div>

<hr class="section-divider">

<!-- セクション5: リスク分析 -->
<h1>5. リスク分析</h1>

<h2>5.1 レバレッジリスク（ギャップダウン最悪ケース）</h2>
<div style="overflow-x: auto;">
<table>
<thead>
<tr><th>パターン</th><th>レバ</th><th>Pos%</th><th>実質%</th><th>最悪トレード</th><th>PnL%</th><th>レバ損失%</th><th>破産</th></tr>
</thead>
<tbody>
{build_gd_risk_table()}
</tbody>
</table>
</div>

<div class="chart-container">
    <img src="data:image/png;base64,{chart3_b64}" alt="レバレッジ散布図">
</div>

<h2>5.2 最大連敗 / 銘柄集中度</h2>
<div style="overflow-x: auto;">
<table>
<thead>
<tr><th>パターン</th><th>S</th><th>E</th><th>T</th><th>取引数</th><th>PF</th><th>最大連敗</th><th>最大連勝</th><th>固有銘柄数</th></tr>
</thead>
<tbody>
{"".join(
    f'<tr><td>{esc(r["Pattern"])}</td><td>{esc(r["S"])}</td><td>{esc(r["E"])}</td><td>{esc(r["T"])}</td>'
    f'<td>{int(r["Trades"])}</td><td>{r["PF"]:.2f}</td>'
    f'<td class="{"red-text" if r["MaxConsecLoss"] >= 5 else ""}">{int(r["MaxConsecLoss"])}</td>'
    f'<td>{int(r["MaxConsecWin"])}</td><td>{int(r["UniqueTickers"])}</td></tr>'
    for _, r in full_df.iterrows()
)}
</tbody>
</table>
</div>

<h2>5.3 2025年Q2依存度</h2>
<div class="chart-container">
    <img src="data:image/png;base64,{chart4_b64}" alt="Q2依存度">
</div>
<p>
<strong>重要な発見:</strong> 多くの高リターンパターンが全リターンの50〜244%を2025年Q2の1四半期のみから得ている。
BOT-A推奨構成（S1xE16xT63）の依存度は29%で許容範囲だが、継続的な監視が必要。
依存度100%超のパターンは、構造的にその1四半期以外では赤字。
</p>

<hr class="section-divider">

<!-- セクション6: ウォークフォワード検証 -->
<h1>6. ウォークフォワード検証（S1xE16xT63）</h1>

<div class="chart-container">
    <img src="data:image/png;base64,{chart5_b64}" alt="WF OOSリターン">
</div>

<div style="overflow-x: auto;">
<table>
<thead>
<tr><th>ウィンドウ</th><th>期間</th><th>種別</th><th>取引数</th><th>勝率</th><th>PF</th><th>リターン%</th><th>MDD%</th><th>平均PnL%</th></tr>
</thead>
<tbody>
{build_wf_table_html()}
</tbody>
</table>
</div>

<h3>安定性指標</h3>
<div class="summary-grid">
    <div class="summary-card">
        <div class="num">5/7</div>
        <div class="label">OOSプラス回数</div>
    </div>
    <div class="summary-card">
        <div class="num">+20.4%</div>
        <div class="label">OOS平均リターン/半期</div>
    </div>
    <div class="summary-card">
        <div class="num">51.8%</div>
        <div class="label">OOS平均勝率</div>
    </div>
    <div class="summary-card">
        <div class="num">19.6%</div>
        <div class="label">勝率劣化率</div>
    </div>
    <div class="summary-card">
        <div class="num">-15.2%</div>
        <div class="label">最悪OOS（W1）</div>
    </div>
    <div class="summary-card">
        <div class="num">+76.9%</div>
        <div class="label">最良OOS（W3）</div>
    </div>
</div>

<hr class="section-divider">

<!-- セクション7: ナレッジベース活用状況 -->
<h1>7. ナレッジベース活用状況</h1>

<h2>7.1 4ソース対照実験（A/B1/B2/C）</h2>
<div style="overflow-x: auto;">
<table>
<thead>
<tr><th>パターン</th><th>ソース</th><th>S</th><th>E</th><th>T</th><th>取引数</th><th>勝率</th><th>PF</th><th>リターン%</th><th>MDD%</th><th>備考</th></tr>
</thead>
<tbody>
{build_4source_table_html()}
</tbody>
</table>
</div>

<p>
<strong>結論:</strong> 先生ベースのロジック(A)が最高品質のベースラインを提供（PF=1.94）。
Gemini B2b派生（GU+15%ブロック）はPFを1.98にわずかに改善。
SURF(C)ロジックは206トレードでPF=0.98、リターン-67.8%と完全に失敗。
</p>

<h2>7.2 ナレッジ - ロジック対応表</h2>
<table class="knowledge-table">
<thead>
<tr><th>ロジック</th><th>参照ナレッジファイル</th></tr>
</thead>
<tbody>
{"".join(f'<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>' for k, v in knowledge_refs)}
</tbody>
</table>

<h3>ナレッジカテゴリ別検証状況（vault/knowledge/）</h3>
<table>
<thead><tr><th>カテゴリ</th><th>出典</th><th>バックテスト検証結果</th></tr></thead>
<tbody>
<tr><td>screening/</td><td>A（先生）</td><td><span class="tag tag-pass">PASS - S1が最高品質</span></td></tr>
<tr><td>chart/</td><td>A（先生）</td><td><span class="tag tag-pass">PASS - 200MA/5MA確認済み</span></td></tr>
<tr><td>entry/</td><td>A（先生）</td><td><span class="tag tag-warn">一部 - GU/板読みは日中データ必要</span></td></tr>
<tr><td>exit/</td><td>A（先生）</td><td><span class="tag tag-pass">PASS - SL/TP/TS有効性確認</span></td></tr>
<tr><td>money_management/</td><td>A（先生）</td><td><span class="tag tag-pass">PASS - 集中投資は有効</span></td></tr>
<tr><td>market_environment/</td><td>A（先生）</td><td><span class="tag tag-warn">保留 - M1未統合</span></td></tr>
<tr><td>gemini_b1/</td><td>B1（Gemini解釈）</td><td><span class="tag tag-warn">一部 - PF=1.65、GU出口は有効</span></td></tr>
<tr><td>gemini_b2/</td><td>B2（Gemini独自）</td><td><span class="tag tag-pass">PASS - GU+15%ブロック有効</span></td></tr>
<tr><td>surf/</td><td>C（SURF）</td><td><span class="tag tag-fail">FAIL - PF=0.98、非現実的パラメータ</span></td></tr>
<tr><td>examples/</td><td>A（先生）</td><td><span class="tag tag-warn">参考資料のみ</span></td></tr>
</tbody>
</table>

<hr class="section-divider">

<!-- セクション8: 推奨と次のステップ -->
<h1>8. 現時点の推奨と次のステップ</h1>

<div class="rec-box">
    <div class="bot-name">BOT-A: S1 x E16 x T63 <span class="tag tag-pass">推奨</span></div>
    <div class="config">レバ2.0倍 | ポジション50% | 実質投入100% | SL3% / TP12% / TS3% / 最大3日保有</div>
    <div class="detail">
        PF=2.13 | リターン+158.9%（5.4年） | MDD 30.7% | WF PASS（7窓中5窓プラス）<br>
        Q2依存度29% | 最悪GD -18.42% | 全29トレード（低頻度）
    </div>
</div>

<div class="rec-box">
    <div class="bot-name">BOT-B: S12 x E16 x T62 <span class="tag tag-warn">暫定</span></div>
    <div class="config">レバ3.0倍 | ポジション30% | 実質投入90% | SL2% / TP9% / TS2% / 最大1日保有</div>
    <div class="detail">
        PF=1.39 | リターン+63.7%（5.4年） | MDD 61.5%（高） | Q2依存度12.2%<br>
        全58トレード | 低PFでレバレッジはリスキー。スクリーニング/エントリーの改善が必要。
    </div>
</div>

<h3>次のアクション</h3>
<div class="next-steps">
    <ul>
        <li>M1（地合いスコア）を実装し、低品質な相場環境をフィルタリング</li>
        <li>N1（センチメント/イベント監視）を統合し、PTS急落によるGDリスクを防止</li>
        <li>BOT-B改善: 代替スクリーニング（S15/S20）× E16でPF向上を検証</li>
        <li>日中データ統合（GUタイミング、板読み、10:30ルール）</li>
        <li>Saxo Bank API連携（デモ口座）でペーパートレード検証</li>
        <li>モンテカルロシミュレーションでDD信頼区間を算出</li>
        <li>3ヶ月間のライブペーパートレードによるフォワード検証</li>
    </ul>
</div>

<footer>
    全自動株取引マシン バックテストレポート | 自動生成: 2026-03-09 | データ: 2020-10 ~ 2026-03
</footer>

</body>
</html>
"""

output_path = REPORTS_DIR / "backtest_report.html"
output_path.write_text(html, encoding="utf-8")
size_mb = output_path.stat().st_size / (1024 * 1024)
print(f"レポート生成完了: {output_path}")
print(f"ファイルサイズ: {size_mb:.2f} MB")
