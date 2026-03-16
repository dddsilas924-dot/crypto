"""Task 2: トレード手動検算スクリプト

MeanRevert 10件 + Surge 10件をランダム抽出し、DBの生データと照合:
1. entry_price == 翌日DB始値
2. TP/SL判定の正確性
3. コスト0.22%の適用
4. PnL計算の一致
"""
import sys
import random
import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

ROUND_TRIP_COST = 0.22  # %


def verify_trade(db, trade, bot_config):
    """1トレードを手動検算"""
    conn = db._get_conn()
    issues = []

    symbol = trade['symbol']
    entry_date = trade['entry_date']
    signal_date = trade.get('signal_date', '')
    entry_price = trade['entry_price']
    exit_price = trade.get('exit_price', 0)
    exit_date = trade.get('exit_date', '')
    exit_reason = trade.get('exit_reason', '')
    side = trade['side']
    leverage = trade['leverage']
    position_value = trade['position_value']

    # === Check 1: entry_price == 翌日DB始値 ===
    if signal_date:
        dt = datetime.strptime(signal_date, '%Y-%m-%d')
        next_ts = int((dt + timedelta(days=1)).timestamp() * 1000)
        max_ts = next_ts + 5 * 86400000
        row = pd.read_sql_query(
            "SELECT timestamp, open FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp < ? ORDER BY timestamp LIMIT 1",
            conn, params=(symbol, next_ts, max_ts)
        )
        if len(row) > 0:
            db_open = float(row.iloc[0]['open'])
            if abs(entry_price - db_open) > 0.0001 * db_open:  # 0.01%許容
                issues.append(f"entry_price不一致: engine={entry_price:.6f} DB={db_open:.6f}")
        else:
            issues.append(f"翌日OHLCVなし (signal={signal_date})")

    # === Check 2: TP/SL判定の正確性 ===
    tp_pct = trade.get('tp_pct', bot_config.get('take_profit_pct', 8.0))
    sl_pct = trade.get('sl_pct', bot_config.get('stop_loss_pct', 3.0))
    is_long = side == 'long'

    if is_long:
        tp_price = entry_price * (1 + tp_pct / 100)
        sl_price = entry_price * (1 - sl_pct / 100)
    else:
        tp_price = entry_price * (1 - tp_pct / 100)
        sl_price = entry_price * (1 + sl_pct / 100)

    if exit_reason == 'TP':
        # exit_priceがTP価格と一致するか
        if abs(exit_price - tp_price) > 0.0001 * tp_price:
            issues.append(f"TP価格不一致: exit={exit_price:.6f} expected={tp_price:.6f}")

        # その日の高値/安値がTPに到達しているか
        if exit_date:
            dt = datetime.strptime(exit_date, '%Y-%m-%d')
            ts = int(dt.timestamp() * 1000)
            row = pd.read_sql_query(
                "SELECT high, low FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp < ? LIMIT 1",
                conn, params=(symbol, ts, ts + 86400000)
            )
            if len(row) > 0:
                high = float(row.iloc[0]['high'])
                low = float(row.iloc[0]['low'])
                if is_long and high < tp_price:
                    issues.append(f"TP未到達: high={high:.6f} < tp={tp_price:.6f}")
                elif not is_long and low > tp_price:
                    issues.append(f"TP未到達: low={low:.6f} > tp={tp_price:.6f}")

    elif exit_reason == 'SL':
        if abs(exit_price - sl_price) > 0.0001 * sl_price:
            issues.append(f"SL価格不一致: exit={exit_price:.6f} expected={sl_price:.6f}")

        if exit_date:
            dt = datetime.strptime(exit_date, '%Y-%m-%d')
            ts = int(dt.timestamp() * 1000)
            row = pd.read_sql_query(
                "SELECT high, low FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp < ? LIMIT 1",
                conn, params=(symbol, ts, ts + 86400000)
            )
            if len(row) > 0:
                high = float(row.iloc[0]['high'])
                low = float(row.iloc[0]['low'])
                if is_long and low > sl_price:
                    issues.append(f"SL未到達: low={low:.6f} > sl={sl_price:.6f}")
                elif not is_long and high < sl_price:
                    issues.append(f"SL未到達: high={high:.6f} < sl={sl_price:.6f}")

    # === Check 3: コスト0.22%の適用 ===
    raw_pnl_pct = trade.get('raw_pnl_pct', 0)
    net_pnl_pct = trade.get('pnl_pct', 0)
    expected_net = round(raw_pnl_pct - ROUND_TRIP_COST, 2)
    if abs(net_pnl_pct - expected_net) > 0.01:
        issues.append(f"コスト控除不一致: net={net_pnl_pct} expected={expected_net} (raw={raw_pnl_pct} - {ROUND_TRIP_COST})")

    # === Check 4: PnL計算の一致 ===
    if is_long:
        manual_raw = (exit_price - entry_price) / entry_price * 100
    else:
        manual_raw = (entry_price - exit_price) / entry_price * 100

    manual_net = manual_raw - ROUND_TRIP_COST
    manual_leveraged = manual_net * leverage
    manual_amount = position_value * (manual_leveraged / 100)

    reported_amount = trade.get('pnl_amount', 0)
    if abs(manual_amount - reported_amount) > 1.0:  # 1円許容
        issues.append(f"PnL金額不一致: engine={reported_amount:.2f} manual={manual_amount:.2f}")

    reported_leveraged = trade.get('pnl_leveraged_pct', 0)
    if abs(manual_leveraged - reported_leveraged) > 0.05:
        issues.append(f"レバPnL%不一致: engine={reported_leveraged:.2f} manual={manual_leveraged:.2f}")

    conn.close()
    return issues


def main():
    with open('config/settings.yaml', 'r') as f:
        config = yaml.safe_load(f)

    db = HistoricalDB()
    start, end = '2024-01-01', '2026-03-01'
    random.seed(42)

    total_checks = 0
    total_issues = 0

    for bot_name, bot_label in [('meanrevert', 'MeanRevert'), ('surge', 'Surge')]:
        bot_config = config.get(f'bot_{bot_name}', {})
        engine = BacktestEngine(bot_name, bot_config, db)
        r = engine.run(start, end)
        trades = r.get('trades', [])

        print(f"\n{'=' * 80}")
        print(f"  {bot_label} トレード検算 (全{len(trades)}件からランダム10件)")
        print(f"{'=' * 80}")

        if len(trades) < 10:
            sample = trades
        else:
            sample = random.sample(trades, 10)

        for i, trade in enumerate(sample, 1):
            issues = verify_trade(db, trade, bot_config)
            total_checks += 1

            status = "✓ OK" if not issues else f"⚠ {len(issues)}件"
            sym_short = trade['symbol'].replace('/USDT:USDT', '')
            print(f"\n  [{i:2d}] {sym_short} {trade['side']:>5s} {trade.get('entry_date','')}"
                  f" → {trade.get('exit_date','')} ({trade.get('exit_reason','')}) "
                  f"PnL={trade.get('pnl_leveraged_pct',0):+.2f}%  {status}")

            if issues:
                total_issues += len(issues)
                for iss in issues:
                    print(f"       ⚠ {iss}")

    # サマリー
    print(f"\n{'=' * 80}")
    print(f"  検算サマリー")
    print(f"{'=' * 80}")
    print(f"  検算トレード数: {total_checks}")
    print(f"  不一致件数: {total_issues}")
    if total_issues == 0:
        print(f"  結果: 全トレード検算OK ✓✓ エンジン計算は正確")
    else:
        print(f"  結果: {total_issues}件の不一致あり ⚠ 要確認")


if __name__ == "__main__":
    main()
