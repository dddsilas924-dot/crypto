#!/usr/bin/env python
"""
Resume Pipeline: Block 2-5 (Block 1 already complete)

Block 2 最適化: FR閾値ごとにシグナル収集を繰り返す代わりに、
最小FR(0.03)で1回だけ収集し、各シグナルのfr_for_check値で後フィルタ。
5 variants × 1 pass = 5回のみ（元は30回）→ 6倍高速化。
"""
import sys
import os
import csv
import json
import time
import traceback
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from copy import deepcopy

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.data.database import HistoricalDB
from src.backtest.backtest_engine import BacktestEngine

# Import shared utilities from overnight script
from scripts.overnight_grid_search import (
    START_DATE, END_DATE, INITIAL_CAPITAL, ROUND_TRIP_COST_PCT,
    GRID_BOTS, LEVBURN_VARIANTS, LB_FR_THRESHOLDS, LB_TP_VALUES,
    LB_SL_VALUES, LB_LEVERAGES,
    log, load_config, preload_ohlcv_for_symbols, simulate_trades_fast,
    _generate_block2_html, _html_header, _html_footer, _pf_color_bg,
    _render_svg_chart,
    run_block3, run_block4, run_block5, send_telegram_summary,
)


# ============================================================
# Optimized LevBurn Signal Collector
# ============================================================
class LevBurnSignalCollector(BacktestEngine):
    """LevBurnのシグナルをFR値付きで収集。最小FR閾値で1回だけ実行。"""

    def collect_signals_with_fr(self, start_date: str, end_date: str,
                                 min_fr_threshold: float = 0.03) -> list:
        """シグナルをfr_for_check値付きで収集"""
        # Override config to use minimum FR threshold
        original_fr = self.config.get('fr_threshold', 0.3)
        self.config['fr_threshold'] = min_fr_threshold

        conn = self.db._get_conn()

        fg_rows = conn.execute(
            "SELECT date, value FROM fear_greed_history WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        fg_map = {r[0]: r[1] for r in fg_rows}

        btc_df = self._get_daily_ohlcv(conn, 'BTC/USDT:USDT', start_date, end_date)
        if btc_df is None or len(btc_df) < 20:
            conn.close()
            self.config['fr_threshold'] = original_fr
            return []

        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM sector WHERE is_crypto=1"
        ).fetchall()]

        signals = []
        dates = sorted(fg_map.keys())

        for date_str in dates:
            fg = fg_map[date_str]

            btc_row = btc_df[btc_df.index.strftime('%Y-%m-%d') == date_str]
            if len(btc_row) == 0:
                continue
            btc_close = float(btc_row['close'].iloc[0])
            btc_prev = btc_df[btc_df.index < btc_row.index[0]]
            if len(btc_prev) == 0:
                continue
            btc_prev_close = float(btc_prev['close'].iloc[-1])
            btc_return = (btc_close - btc_prev_close) / btc_prev_close * 100

            try:
                signal = self._check_levburn_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            except Exception:
                signal = None

            if signal:
                next_result = self._get_next_open(conn, signal['symbol'], date_str)
                if next_result is not None:
                    next_open, next_date = next_result
                    signals.append({
                        'signal_date': date_str,
                        'entry_date': next_date,
                        'symbol': signal['symbol'],
                        'side': signal.get('side', 'long'),
                        'entry_price': next_open,
                        'fr_for_check': abs(signal.get('fr_for_check', 0)),
                    })

        conn.close()
        self.config['fr_threshold'] = original_fr
        return signals


def run_block2_optimized(config, db):
    """Block 2: LevBurn最適化版（variant毎に1回のみシグナル収集）"""
    log("=" * 60)
    log("Block 2: LevBurn 5バリエーション精密チューニング (最適化版)")
    log("=" * 60)
    block_start = time.time()

    all_lb_results = []
    min_fr = min(LB_FR_THRESHOLDS)  # 0.03

    for vname, vcfg in LEVBURN_VARIANTS.items():
        variant_start = time.time()
        log(f"\n--- LevBurn-{vname.upper()} ---")

        # Collect signals ONCE with minimum FR threshold
        bot_cfg = vcfg.copy()
        bot_cfg['fr_threshold'] = min_fr
        bot_cfg['max_position_pct'] = 50

        collector = LevBurnSignalCollector(f'levburn_{vname}', bot_cfg, db)
        all_signals = collector.collect_signals_with_fr(START_DATE, END_DATE, min_fr)

        log(f"  シグナル収集完了: {len(all_signals)}件 (FR>={min_fr})")

        if not all_signals:
            log(f"  No signals for {vname}")
            for fr_thr in LB_FR_THRESHOLDS:
                for tp in LB_TP_VALUES:
                    for sl in LB_SL_VALUES:
                        for lev in LB_LEVERAGES:
                            all_lb_results.append({
                                'Variant': vname, 'FR_thr': fr_thr,
                                'TP': tp, 'SL': sl, 'Leverage': lev,
                                'PF': 0, 'Return': 0, 'MDD': 0,
                                'WR': 0, 'Sharpe': 0, 'Trades': 0,
                            })
            continue

        # Preload OHLCV once per variant
        signal_syms = list(set(s['symbol'] for s in all_signals) | {'BTC/USDT:USDT'})
        ohlcv_cache = preload_ohlcv_for_symbols(db, signal_syms, START_DATE, END_DATE)

        for fr_thr in LB_FR_THRESHOLDS:
            # Filter signals by FR threshold
            filtered_signals = [s for s in all_signals if s['fr_for_check'] >= fr_thr]

            if not filtered_signals:
                log(f"  FR={fr_thr}: no signals after filter")
                for tp in LB_TP_VALUES:
                    for sl in LB_SL_VALUES:
                        for lev in LB_LEVERAGES:
                            all_lb_results.append({
                                'Variant': vname, 'FR_thr': fr_thr,
                                'TP': tp, 'SL': sl, 'Leverage': lev,
                                'PF': 0, 'Return': 0, 'MDD': 0,
                                'WR': 0, 'Sharpe': 0, 'Trades': 0,
                            })
                continue

            combo_count = 0
            total_combos = len(LB_TP_VALUES) * len(LB_SL_VALUES) * len(LB_LEVERAGES)

            for tp in LB_TP_VALUES:
                for sl in LB_SL_VALUES:
                    for lev in LB_LEVERAGES:
                        max_hold = vcfg.get('max_holding_days', 2)
                        pos_pct = vcfg.get('position_size_pct', 3)

                        metrics = simulate_trades_fast(
                            filtered_signals, ohlcv_cache, tp, sl, lev,
                            max_hold_days=max_hold, position_size_pct=pos_pct,
                        )

                        all_lb_results.append({
                            'Variant': vname, 'FR_thr': fr_thr,
                            'TP': tp, 'SL': sl, 'Leverage': lev,
                            'PF': metrics['profit_factor'],
                            'Return': metrics['total_return_pct'],
                            'MDD': metrics['max_drawdown_pct'],
                            'WR': metrics['win_rate'],
                            'Sharpe': metrics['sharpe_ratio'],
                            'Trades': metrics['total_trades'],
                        })
                        combo_count += 1

            best_row = max(
                [r for r in all_lb_results if r['Variant'] == vname and r['FR_thr'] == fr_thr and r['Trades'] > 0],
                key=lambda x: x['PF'], default=None
            )
            if best_row:
                log(f"  FR={fr_thr}: {len(filtered_signals)} sigs, best PF={best_row['PF']:.2f} TP={best_row['TP']} SL={best_row['SL']} Lev={best_row['Leverage']}")

        variant_elapsed = time.time() - variant_start
        log(f"  {vname} 完了: {variant_elapsed / 60:.1f}分")

    # Save CSV
    csv_path = 'vault/backtest_results/levburn_grid_results.csv'
    if all_lb_results:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_lb_results[0].keys())
            writer.writeheader()
            writer.writerows(all_lb_results)
        log(f"CSV saved: {csv_path}")

    # Generate HTML
    _generate_block2_html(all_lb_results)

    elapsed = time.time() - block_start
    log(f"Block 2 完了: {elapsed / 60:.1f}分")
    return all_lb_results


def main():
    overall_start = time.time()
    log("=" * 60)
    log("  Resume Pipeline: Blocks 2-5")
    log(f"  開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("  Block 1: SKIP (既に完了)")
    log("=" * 60)

    config = load_config()
    db = HistoricalDB()

    block_results = {}
    errors = []

    # Load Block 1 results from saved files
    best_per_bot = {}
    trade_logs = {}
    try:
        results_df = pd.read_csv('vault/backtest_results/grid_search_results.csv')
        for bot in GRID_BOTS:
            bot_df = results_df[results_df['Bot'] == bot]
            if not bot_df.empty:
                best = bot_df.sort_values('PF', ascending=False).iloc[0]
                best_per_bot[bot] = best.to_dict()

            tl_path = f'vault/backtest_results/trade_logs/{bot}_best_trades.json'
            if os.path.exists(tl_path):
                with open(tl_path, 'r', encoding='utf-8') as f:
                    trade_logs[bot] = json.load(f)

        block_results['block1'] = {
            'best_per_bot': best_per_bot,
            'total_patterns': len(results_df),
        }
        log(f"Block 1 データ読込: {len(best_per_bot)} bots, {len(results_df)} patterns")
    except Exception as e:
        log(f"Block 1 データ読込エラー: {e}")
        block_results['block1'] = {}

    # === Block 2 (Optimized) ===
    try:
        lb_results = run_block2_optimized(config, db)
        block_results['block2'] = {'all_results': lb_results}
    except Exception as e:
        log(f"Block 2 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 2: {e}")
        block_results['block2'] = {}

    # === Block 3 ===
    try:
        b3_results = run_block3(trade_logs, best_per_bot)
        block_results['block3'] = b3_results
    except Exception as e:
        log(f"Block 3 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 3: {e}")
        block_results['block3'] = {}

    # === Block 4 ===
    try:
        b4_results = run_block4(trade_logs, db)
        block_results['block4'] = b4_results
    except Exception as e:
        log(f"Block 4 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 4: {e}")
        block_results['block4'] = {}

    # === Block 5 ===
    try:
        b5_results = run_block5()
        block_results['block5'] = b5_results
    except Exception as e:
        log(f"Block 5 エラー: {e}")
        traceback.print_exc()
        errors.append(f"Block 5: {e}")
        block_results['block5'] = {}

    # === Telegram ===
    try:
        import asyncio
        asyncio.run(send_telegram_summary(block_results))
    except Exception as e:
        log(f"Telegram通知エラー: {e}")

    overall_elapsed = time.time() - overall_start
    log("=" * 60)
    log(f"  全ブロック完了: {overall_elapsed / 60:.1f}分")
    if errors:
        log(f"  エラー: {len(errors)}件")
        for e in errors:
            log(f"    - {e}")
    log("=" * 60)


if __name__ == '__main__':
    main()
