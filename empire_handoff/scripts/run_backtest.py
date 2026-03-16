"""
バックテスト実行スクリプト

使い方:
  python scripts/run_backtest.py --bot alpha --start 2024-01-01 --end 2026-03-01
  python scripts/run_backtest.py --bot surge --start 2024-01-01 --end 2026-03-01
  python scripts/run_backtest.py --bot both --start 2024-01-01 --end 2026-03-01
"""
import asyncio
import argparse
import sys
import yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine


BOT_LABELS = {
    'alpha': 'Bot-Alpha', 'surge': 'Bot-Surge',
    'momentum': 'Bot-Momentum', 'rebound': 'Bot-Rebound', 'stability': 'Bot-Stability',
    'trend': 'Bot-Trend', 'cascade': 'Bot-Cascade', 'meanrevert': 'Bot-MeanRevert',
    'breakout': 'Bot-Breakout', 'btcfollow': 'Bot-BTCFollow', 'weakshort': 'Bot-WeakShort',
    'feardip': 'Bot-FearDip', 'sectorlead': 'Bot-SectorLead', 'shortsqueeze': 'Bot-ShortSqueeze',
    'sniper': 'Bot-Sniper', 'scalp': 'Bot-Scalp', 'event': 'Bot-Event',
    'volexhaust': 'Bot-VolumeExhaust', 'fearflat': 'Bot-FearFlat', 'domshift': 'Bot-DomShift',
    'gaptrap': 'Bot-GapTrap', 'sectorsync': 'Bot-SectorSync',
    'meanrevert_adaptive': 'Bot-MeanRevert-Adaptive',
    'meanrevert_tight': 'Bot-MeanRevert-Tight',
    'meanrevert_hybrid': 'Bot-MeanRevert-Hybrid',
    'meanrevert_newlist': 'Bot-MeanRevert-NewList',
    'meanrevert_tuned': 'Bot-MeanRevert-Tuned',
    'ico_meanrevert': 'Bot-ICO-MeanRevert',
    'ico_rebound': 'Bot-ICO-Rebound',
    'ico_surge': 'Bot-ICO-Surge',
}
ALL_NEW_BOTS = ['trend', 'cascade', 'meanrevert', 'breakout', 'btcfollow', 'weakshort']

def print_results(bot_type: str, results: dict):
    """結果をコンソール表示"""
    label = BOT_LABELS.get(bot_type, f"Bot-{bot_type.title()}")
    print(f"\n{'═' * 50}")
    print(f"  {label} バックテスト結果")
    print(f"{'═' * 50}")

    if results.get('error'):
        print(f"  ❌ エラー: {results['error']}")
        return

    if results['total_trades'] == 0:
        print(f"  トレードなし（条件成立日なし）")
        return

    best = results.get('best_trade', {})
    worst = results.get('worst_trade', {})

    print(f"  総トレード数:       {results['total_trades']}")
    print(f"  勝率:              {results['win_rate']}%")
    print(f"  プロフィットファクター: {results['profit_factor']}")
    print(f"  総リターン:         {results['total_return_pct']:+.1f}%")
    print(f"  最大ドローダウン:    {results['max_drawdown_pct']:.1f}%")
    print(f"  平均損益(レバ後):    {results['avg_pnl_pct']:+.2f}%")
    print(f"  平均保有日数:       {results['avg_holding_days']:.1f}日")
    print(f"  シャープレシオ:      {results['sharpe_ratio']:.2f}")
    if best:
        print(f"  最高トレード:       {best.get('pnl_pct', 0):+.1f}% ({best.get('symbol', '?')} {best.get('date', '')})")
    if worst:
        print(f"  最悪トレード:       {worst.get('pnl_pct', 0):+.1f}% ({worst.get('symbol', '?')} {worst.get('date', '')})")
    print(f"  最終資金:           ¥{results.get('final_capital', 0):,.0f}")
    print(f"{'═' * 50}")

    # トレード一覧
    trades = results.get('trades', [])
    if trades:
        print(f"\n  トレード一覧:")
        for i, t in enumerate(trades, 1):
            pnl = t.get('pnl_leveraged_pct', 0)
            mark = '✅' if pnl > 0 else '❌'
            print(f"    {mark} #{i} {t['symbol'].split('/')[0]:12s} "
                  f"{t['entry_date']}→{t.get('exit_date', '?'):10s} "
                  f"{t.get('exit_reason', '?'):7s} {pnl:+6.1f}%")


def build_telegram_text(bot_type: str, results: dict, start: str, end: str) -> str:
    """Telegram送信用テキスト"""
    label = BOT_LABELS.get(bot_type, f"Bot-{bot_type.title()}")
    if results.get('error') or results['total_trades'] == 0:
        return f"📊 <b>{label} BT</b>: トレードなし ({start}〜{end})"

    return (
        f"📊 <b>{label} バックテスト</b>\n"
        f"期間: {start} 〜 {end}\n\n"
        f"トレード数: {results['total_trades']}\n"
        f"勝率: {results['win_rate']}%\n"
        f"PF: {results['profit_factor']}\n"
        f"総リターン: {results['total_return_pct']:+.1f}%\n"
        f"最大DD: {results['max_drawdown_pct']:.1f}%\n"
        f"Sharpe: {results['sharpe_ratio']:.2f}\n"
        f"最終資金: ¥{results.get('final_capital', 0):,.0f}"
    )


async def main():
    parser = argparse.ArgumentParser(description="Empire Monitor バックテスト")
    parser.add_argument('--bot', choices=list(BOT_LABELS.keys()) + ['both', 'all_new'], default='both')
    parser.add_argument('--start', default='2024-01-01')
    parser.add_argument('--end', default='2026-03-01')
    parser.add_argument('--pyramid', choices=['on', 'off'], default='off')
    parser.add_argument('--leverage', type=int, default=None, help='Override leverage')
    parser.add_argument('--verbose', action='store_true', help='Show monthly equity')
    args = parser.parse_args()

    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start_time = datetime.now()

    # Fear&Greedデータ確認
    conn = db._get_conn()
    fg_count = conn.execute("SELECT COUNT(*) FROM fear_greed_history").fetchone()[0]
    conn.close()
    if fg_count == 0:
        print("❌ Fear&Greedヒストリカルデータがありません")
        print("   先に実行: python scripts/init_fear_history.py")
        return

    print(f"📅 期間: {args.start} 〜 {args.end}")
    print(f"📦 Fear&Greed: {fg_count}日分")

    all_results = {}
    telegram_texts = []

    if args.bot == 'both':
        bots = ['alpha', 'surge']
    elif args.bot == 'all_new':
        bots = ALL_NEW_BOTS
    else:
        bots = [args.bot]

    pyramid_on = args.pyramid == 'on'

    for bot_type in bots:
        bot_config = config.get(f'bot_{bot_type}', {}).copy()
        if pyramid_on:
            bot_config['pyramid'] = True
        if args.leverage is not None:
            bot_config['leverage'] = args.leverage
        print(f"\n🔄 {bot_type.upper()} バックテスト実行中... (pyramid={'on' if pyramid_on else 'off'}, lev={bot_config.get('leverage', '?')}x)")
        engine = BacktestEngine(bot_type, bot_config, db)
        results = engine.run(args.start, args.end)
        all_results[bot_type] = results

        print_results(bot_type, results)

        # --verbose: 月末残高推移
        if args.verbose and results.get('equity_curve'):
            print(f"\n  月末残高推移:")
            monthly_equity = {}
            for ec in results['equity_curve']:
                month = ec['date'][:7]
                monthly_equity[month] = ec['capital']
            for month, eq in sorted(monthly_equity.items()):
                ret_from_init = (eq - 1_000_000) / 1_000_000 * 100
                print(f"    {month}: ¥{eq:>14,.0f}  ({ret_from_init:+.1f}%)")
            print(f"  MinCapital: ¥{results.get('min_capital', 0):,.0f}")

        # CSV保存
        csv_path = f"vault/backtest_results/bt_{bot_type}_{args.start.replace('-', '')}_{args.end.replace('-', '')}.csv"
        engine.trades_to_csv(csv_path)
        if engine.trades:
            print(f"\n  📁 CSV保存: {csv_path}")

        telegram_texts.append(build_telegram_text(bot_type, results, args.start, args.end))

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️ 処理時間: {elapsed:.1f}秒")

    # Telegram送信
    try:
        from src.execution.alert import TelegramAlert
        alert = TelegramAlert()
        text = '\n\n'.join(telegram_texts) + f"\n\n⏱️ {elapsed:.1f}秒"
        await alert.send_message(text)
        print("📱 Telegram送信完了")
    except Exception as e:
        print(f"⚠️ Telegram送信失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
