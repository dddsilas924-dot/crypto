"""
一括バックテスト実行スクリプト
指定Bot群を1年分バックテスト → 結果比較テーブル出力

使い方:
  python scripts/run_batch_backtest.py
"""
import asyncio
import sys
import yaml
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# ── 対象Bot ──
TARGET_BOTS = [
    'levburn_sec',              # LevBurn-Sec Standard (10x, TP1.5%, SL0.5%)
    'levburn_sec_aggressive',   # LevBurn-Sec Aggressive (15x, TP3%, SL1%)
    'levburn_sec_conservative', # LevBurn-Sec Conservative (7x, TP1%, SL0.3%)
    'meanrevert_tight',         # MeanRevert-Tight
    'meanrevert',               # MeanRevert
    'scalp',                    # Scalp
    'surge',                    # Surge
    'weakshort',                # WeakShort
]

START = '2025-03-13'
END   = '2026-03-13'


def print_comparison(all_results: dict):
    """全Bot比較テーブル"""
    print(f"\n{'═' * 110}")
    print(f"  バックテスト比較 ({START} 〜 {END})")
    print(f"{'═' * 110}")
    print(f"  {'Bot':<30s} {'Trades':>7s} {'WR%':>6s} {'PF':>6s} {'Return':>10s} {'MDD':>7s} {'AvgPnL':>8s} {'Sharpe':>7s} {'Final¥':>14s}")
    print(f"  {'─' * 30} {'─' * 7} {'─' * 6} {'─' * 6} {'─' * 10} {'─' * 7} {'─' * 8} {'─' * 7} {'─' * 14}")

    # Sort by total return descending
    sorted_bots = sorted(all_results.items(),
                         key=lambda x: x[1].get('total_return_pct', -999), reverse=True)

    for bot, r in sorted_bots:
        if r.get('error') or r.get('total_trades', 0) == 0:
            print(f"  {bot:<30s} {'N/A':>7s}   (トレードなし or エラー)")
            continue
        print(f"  {bot:<30s} {r['total_trades']:>7d} {r['win_rate']:>5.1f}% {r['profit_factor']:>6.2f} "
              f"{r['total_return_pct']:>+9.1f}% {r['max_drawdown_pct']:>6.1f}% "
              f"{r['avg_pnl_pct']:>+7.2f}% {r['sharpe_ratio']:>6.2f} ¥{r.get('final_capital', 0):>13,.0f}")

    print(f"{'═' * 110}")


def save_comparison_csv(all_results: dict, path: str):
    """結果をCSVに保存"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['bot', 'trades', 'win_rate', 'profit_factor', 'total_return_pct',
                     'max_drawdown_pct', 'avg_pnl_pct', 'sharpe_ratio', 'avg_hold_days',
                     'final_capital', 'best_trade_pnl', 'worst_trade_pnl'])
        for bot, r in sorted(all_results.items(),
                              key=lambda x: x[1].get('total_return_pct', -999), reverse=True):
            if r.get('error') or r.get('total_trades', 0) == 0:
                w.writerow([bot, 0, '', '', '', '', '', '', '', '', '', ''])
                continue
            best = r.get('best_trade', {})
            worst = r.get('worst_trade', {})
            w.writerow([
                bot, r['total_trades'], r['win_rate'], r['profit_factor'],
                f"{r['total_return_pct']:.2f}", f"{r['max_drawdown_pct']:.2f}",
                f"{r['avg_pnl_pct']:.2f}", f"{r['sharpe_ratio']:.2f}",
                f"{r['avg_holding_days']:.1f}", f"{r.get('final_capital', 0):.0f}",
                f"{best.get('pnl_pct', 0):.2f}", f"{worst.get('pnl_pct', 0):.2f}",
            ])
    print(f"\n📁 比較CSV: {path}")


async def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()

    # F&Gデータ確認
    conn = db._get_conn()
    fg_count = conn.execute("SELECT COUNT(*) FROM fear_greed_history").fetchone()[0]
    fg_range = conn.execute(
        "SELECT MIN(date), MAX(date) FROM fear_greed_history"
    ).fetchone()
    conn.close()

    if fg_count == 0:
        print("❌ Fear&Greedデータなし。先に python scripts/init_fear_history.py を実行")
        return

    print(f"📅 期間: {START} 〜 {END}")
    print(f"📦 Fear&Greed: {fg_count}日分 ({fg_range[0]} 〜 {fg_range[1]})")
    print(f"🤖 対象Bot: {len(TARGET_BOTS)}体")
    print(f"   {', '.join(TARGET_BOTS)}")

    start_time = datetime.now()
    all_results = {}
    telegram_lines = [f"📊 <b>一括バックテスト</b> ({START}〜{END})\n"]

    for bot_type in TARGET_BOTS:
        bot_config = config.get(f'bot_{bot_type}', {}).copy()

        # levburn_sec系: backtest engineはlevburn汎用ロジックを使うが、
        # TP/SL/leverageはバリアント固有configを適用
        if bot_type.startswith('levburn_sec'):
            # TP/SLをbacktest engine用に変換
            if 'tp_pct' in bot_config and 'take_profit_pct' not in bot_config:
                bot_config['take_profit_pct'] = bot_config['tp_pct']
            if 'sl_pct' in bot_config and 'stop_loss_pct' not in bot_config:
                bot_config['stop_loss_pct'] = bot_config['sl_pct']

        lev = bot_config.get('leverage', '?')
        tp = bot_config.get('take_profit_pct', bot_config.get('tp_pct', '?'))
        sl = bot_config.get('stop_loss_pct', bot_config.get('sl_pct', '?'))
        print(f"\n🔄 {bot_type} (lev={lev}x, TP={tp}%, SL={sl}%) ...")

        try:
            engine = BacktestEngine(bot_type, bot_config, db)
            results = engine.run(START, END)
            all_results[bot_type] = results

            if results.get('total_trades', 0) > 0:
                print(f"   ✅ {results['total_trades']}トレード, WR={results['win_rate']}%, "
                      f"Return={results['total_return_pct']:+.1f}%, MDD={results['max_drawdown_pct']:.1f}%, "
                      f"PF={results['profit_factor']}, Sharpe={results['sharpe_ratio']:.2f}")
                telegram_lines.append(
                    f"<b>{bot_type}</b>: {results['total_trades']}T WR{results['win_rate']}% "
                    f"Return{results['total_return_pct']:+.1f}% MDD{results['max_drawdown_pct']:.1f}% "
                    f"Sharpe{results['sharpe_ratio']:.2f}"
                )
            else:
                print(f"   ⚠️ トレードなし")
                telegram_lines.append(f"<b>{bot_type}</b>: トレードなし")

            # 個別CSV
            csv_path = f"vault/backtest_results/bt_{bot_type}_{START.replace('-','')}_{END.replace('-','')}.csv"
            engine.trades_to_csv(csv_path)

        except Exception as e:
            print(f"   ❌ エラー: {e}")
            all_results[bot_type] = {'error': str(e), 'total_trades': 0}
            telegram_lines.append(f"<b>{bot_type}</b>: ❌ {e}")

    elapsed = (datetime.now() - start_time).total_seconds()

    # 比較テーブル出力
    print_comparison(all_results)

    # 比較CSV保存
    csv_compare = f"vault/backtest_results/bt_comparison_{START.replace('-','')}_{END.replace('-','')}.csv"
    save_comparison_csv(all_results, csv_compare)

    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    # Telegram送信
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        telegram_lines.append(f"\n⏱️ {elapsed:.1f}秒")
        await alert.send_message('\n'.join(telegram_lines))
        print("📱 Telegram送信完了")
    except Exception as e:
        print(f"⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
