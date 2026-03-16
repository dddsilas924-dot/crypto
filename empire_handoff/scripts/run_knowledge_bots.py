"""ナレッジBot 5種 バックテスト + WF + キャップ複利 + Telegram通知

Phase 3: バックテスト (5 new bots)
Phase 4: WF検証 (PF>1.5 のみ)
Phase 5: キャップ付き複利 (MeanRevert比較)
Phase 6: Telegram通知
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


def safe_pf(r):
    pf = r.get('profit_factor', 0)
    return 999.0 if pf == float('inf') else pf


def run_wf_oos(bot_type, bot_config, db):
    """WF: OOS 5ウィンドウのみ"""
    WINDOWS = [
        {"name": "W1", "oos_start": "2025-01-01", "oos_end": "2025-03-31"},
        {"name": "W2", "oos_start": "2025-04-01", "oos_end": "2025-06-30"},
        {"name": "W3", "oos_start": "2025-07-01", "oos_end": "2025-09-30"},
        {"name": "W4", "oos_start": "2025-10-01", "oos_end": "2025-12-31"},
        {"name": "W5", "oos_start": "2026-01-01", "oos_end": "2026-03-01"},
    ]
    total_profit = 0.0
    total_loss = 0.0
    oos_pf_positive = 0
    n_with_trades = 0
    results = []

    for w in WINDOWS:
        engine = BacktestEngine(bot_type, bot_config, db)
        r = engine.run(w['oos_start'], w['oos_end'])
        pf = safe_pf(r)
        trades = r.get('total_trades', 0)

        if trades > 0:
            n_with_trades += 1
            if pf > 1.0:
                oos_pf_positive += 1

        for t in r.get('trades', []):
            pnl = t.get('pnl_amount', 0)
            if pnl > 0:
                total_profit += pnl
            else:
                total_loss += abs(pnl)

        results.append({'window': w['name'], 'trades': trades, 'pf': pf,
                         'ret': r.get('total_return_pct', 0)})
        print(f"    {w['name']}: trades={trades:3d}  PF={pf:5.2f}  ret={r.get('total_return_pct', 0):+6.1f}%")

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
        'results': results, 'agg_pf': agg_pf,
        'oos_pf_positive': oos_pf_positive, 'n_with_trades': n_with_trades,
        'verdict': verdict,
    }


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()
    start, end = '2024-01-01', '2026-03-01'

    telegram_lines = ["<b>📊 ナレッジBot 5種 全結果</b>", ""]

    # ========================================
    # Phase 3: バックテスト
    # ========================================
    print("=" * 70)
    print("  Phase 3: ナレッジBot 5種 バックテスト")
    print("=" * 70)

    new_bots = ['volexhaust', 'fearflat', 'domshift', 'gaptrap', 'sectorsync']
    bot_labels = {
        'volexhaust': 'VolumeExhaust（出来高枯渇反転）',
        'fearflat': 'FearFlat（恐怖×低ボラ底固め）',
        'domshift': 'DomShift（BTC独走→アルト回転）',
        'gaptrap': 'GapTrap（窓埋めトラップ）',
        'sectorsync': 'SectorSync（クロスセクター同期）',
    }
    bot_paradox = {
        'volexhaust': '出来高「減少」を買いシグナルに（全既存Botは出来高増加のみ注目）',
        'fearflat': 'Fear低×ATR低の「矛盾」= パニック終了後の静寂こそ底',
        'domshift': 'BTC独走中にアルトを買う（L01ドミナンスを初Bot化）',
        'gaptrap': 'ギャップを「偽物」と判定して逆張り（窓パターン初使用）',
        'sectorsync': '通常無相関セクターの「同期」を検知（L17を逆用）',
    }

    bt_results = {}
    telegram_lines.append("<b>📈 Phase 3: バックテスト結果</b>")

    for bot in new_bots:
        label = bot_labels[bot]
        bot_config = config.get(f'bot_{bot}', {})
        print(f"\n  --- {label} ---")
        engine = BacktestEngine(bot, bot_config, db)
        r = engine.run(start, end)
        bt_results[bot] = r

        trades = r.get('total_trades', 0)
        wr = r.get('win_rate', 0)
        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        sharpe = r.get('sharpe_ratio', 0)
        min_cap = r.get('min_capital', 0)

        pf_str = f"{pf:.2f}" if pf < 999 else "inf"
        print(f"  Trades={trades}  WR={wr:.1f}%  PF={pf_str}  Return={ret:+.1f}%  MDD={mdd:.1f}%  Sharpe={sharpe:.2f}  MinCap=¥{min_cap:,.0f}")

        short_label = bot.capitalize()
        telegram_lines.append(f"  {short_label}: T={trades} WR={wr:.1f}% PF={pf_str} Ret={ret:+.1f}% MDD={mdd:.1f}%")

    telegram_lines.append("")

    # ========================================
    # Phase 4: WF検証
    # ========================================
    print("\n" + "=" * 70)
    print("  Phase 4: WF検証 (PF > 1.5 のみ)")
    print("=" * 70)

    telegram_lines.append("<b>📈 Phase 4: WF検証</b>")
    wf_results = {}

    for bot in new_bots:
        r = bt_results[bot]
        pf = safe_pf(r)
        trades = r.get('total_trades', 0)

        if trades > 0 and pf >= 1.5:
            label = bot_labels[bot]
            print(f"\n  --- {label} (PF={pf:.2f}) → WF実施 ---")
            bot_config = config.get(f'bot_{bot}', {})
            wf = run_wf_oos(bot, bot_config, db)
            wf_results[bot] = wf
            print(f"  OOS集計PF={wf['agg_pf']:.2f}  PF>1.0: {wf['oos_pf_positive']}/{wf['n_with_trades']}win")
            print(f"  判定: {wf['verdict']}")
            telegram_lines.append(f"  {bot.capitalize()}: OOS_PF={wf['agg_pf']:.2f} ({wf['oos_pf_positive']}/{wf['n_with_trades']}win) → {wf['verdict']}")
        else:
            pf_str = f"{pf:.2f}" if pf < 999 else "inf"
            reason = "トレードなし" if trades == 0 else f"PF={pf_str}未達"
            print(f"  {bot}: {reason} → WFスキップ")
            telegram_lines.append(f"  {bot.capitalize()}: {reason} → WFスキップ")

    telegram_lines.append("")

    # ========================================
    # Phase 5: キャップ付き複利
    # ========================================
    print("\n" + "=" * 70)
    print("  Phase 5: キャップ付き複利 (MeanRevert lev=2)")
    print("=" * 70)

    telegram_lines.append("<b>📈 Phase 5: キャップ付き複利</b>")
    mr_config_base = config.get('bot_meanrevert', {})
    cap_configs = [
        ('キャップなし', None),
        ('500万円', 5_000_000),
        ('1000万円', 10_000_000),
    ]

    print(f"  {'設定':>12s} {'Trades':>7s} {'PF':>7s} {'Return':>10s} {'MDD':>8s} {'Final':>14s} {'MinCap':>12s}")

    for label, cap in cap_configs:
        mr_config = copy.deepcopy(mr_config_base)
        if cap is not None:
            mr_config['max_position_jpy'] = cap
        engine = BacktestEngine('meanrevert', mr_config, db)
        r = engine.run(start, end)

        trades = r.get('total_trades', 0)
        pf = safe_pf(r)
        ret = r.get('total_return_pct', 0)
        mdd = r.get('max_drawdown_pct', 0)
        final = r.get('final_capital', 0)
        min_cap_val = r.get('min_capital', 0)

        pf_str = f"{pf:.2f}" if pf < 999 else "inf"
        print(f"  {label:>12s} {trades:7d} {pf_str:>7s} {ret:+9.1f}% {mdd:7.1f}% {final:>14,.0f} {min_cap_val:>12,.0f}")
        telegram_lines.append(f"  {label}: Ret={ret:+.1f}% MDD={mdd:.1f}% Final=¥{final:,.0f}")

    telegram_lines.append("")

    # ========================================
    # 全Bot総合ランキング
    # ========================================
    print("\n" + "=" * 70)
    print("  全Bot総合PFランキング（既存+新規）")
    print("=" * 70)

    all_bots = ['alpha', 'surge', 'momentum', 'rebound', 'stability',
                'trend', 'cascade', 'meanrevert', 'breakout', 'btcfollow', 'weakshort',
                'feardip', 'sectorlead', 'shortsqueeze', 'sniper', 'scalp', 'event']

    rankings = []
    for bot in all_bots:
        bot_config = config.get(f'bot_{bot}', {})
        engine = BacktestEngine(bot, bot_config, db)
        r = engine.run(start, end)
        rankings.append({
            'bot': bot, 'pf': safe_pf(r),
            'trades': r.get('total_trades', 0),
            'wr': r.get('win_rate', 0),
            'ret': r.get('total_return_pct', 0),
        })

    # 新規5Botも追加
    for bot in new_bots:
        r = bt_results[bot]
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
        new_mark = " ★" if r['bot'] in new_bots else ""
        print(f"  {i:>4d} {r['bot']:>15s} {pf_str:>7s} {r['trades']:7d} {r['wr']:5.1f}% {r['ret']:+9.1f}%{new_mark}")
        if i <= 15:
            mark = "★" if r['bot'] in new_bots else ""
            telegram_lines.append(f"  {i}. {r['bot']}: PF={pf_str} T={r['trades']} Ret={r['ret']:+.1f}% {mark}")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    # ========================================
    # 未使用ナレッジサマリー
    # ========================================
    telegram_lines.insert(2, "<b>📚 未使用ナレッジ要素（今回Bot化）</b>")
    telegram_lines.insert(3, "  L01(ドミナンス) → DomShift")
    telegram_lines.insert(4, "  L03逆(出来高減少) → VolumeExhaust")
    telegram_lines.insert(5, "  L06×L11矛盾(Fear低×ATR低) → FearFlat")
    telegram_lines.insert(6, "  L12+窓(ギャップ) → GapTrap")
    telegram_lines.insert(7, "  L17逆(相関上昇) → SectorSync")
    telegram_lines.insert(8, "")

    telegram_lines.append(f"\n⏱️ {elapsed:.1f}秒")

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
