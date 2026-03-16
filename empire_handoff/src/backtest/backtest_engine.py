"""バックテストエンジン - Bot-Alpha/Surgeのヒストリカル検証"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from src.data.database import HistoricalDB


class BacktestEngine:
    """ヒストリカルデータでBot-Alpha/Surgeを検証"""

    # MEXC先物コスト（片道）
    TAKER_FEE_PCT = 0.06   # taker手数料 0.06%
    SLIPPAGE_PCT = 0.05     # スリッページ 0.05%
    COST_PER_SIDE_PCT = TAKER_FEE_PCT + SLIPPAGE_PCT  # 0.11%/片道
    ROUND_TRIP_COST_PCT = COST_PER_SIDE_PCT * 2        # 0.22%/往復

    def __init__(self, bot_type: str, config: dict, db: HistoricalDB):
        """
        bot_type: "alpha" or "surge"
        config: settings.yamlのbot_alpha or bot_surge セクション
        """
        self.bot_type = bot_type
        self.config = config
        self.db = db
        self.initial_capital = 1_000_000
        self.trades: List[dict] = []
        self.equity_curve: List[dict] = []

    def run(self, start_date: str, end_date: str) -> dict:
        """
        バックテスト実行（同期）
        1. Fear&Greedヒストリカル取得
        2. BTC日足取得
        3. 各日でシグナル判定
        4. エントリー→TP/SLシミュレーション
        5. 成績計算
        """
        conn = self.db._get_conn()

        # Fear & Greed ヒストリカル
        fg_rows = conn.execute(
            "SELECT date, value FROM fear_greed_history WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        fg_map = {r[0]: r[1] for r in fg_rows}

        # BTC日足
        btc_df = self._get_daily_ohlcv(conn, 'BTC/USDT:USDT', start_date, end_date)
        if btc_df is None or len(btc_df) < 20:
            conn.close()
            return {"error": "BTC日足データ不足"}

        # 全銘柄リスト（クリプトのみ）
        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM sector WHERE is_crypto=1"
        ).fetchall()]

        capital = float(self.initial_capital)
        self.trades = []
        self.equity_curve = []
        open_trades = []
        self.skipped_count = 0  # 資金不足等でスキップしたシグナル数
        self.pyramid_count = 0  # ピラミッディング（同一銘柄追加）エントリー数
        self.max_simultaneous = 0  # 最大同時保有数

        # ピラミッディング設定
        pyramid_mode = self.config.get('pyramid', False)
        max_total = self.config.get('max_total_positions', 20)
        max_per_symbol = self.config.get('max_positions_per_symbol', 5) if pyramid_mode else 1
        min_position_value = 10000  # 最小ポジション1万円

        dates = sorted(fg_map.keys())

        for date_str in dates:
            fg = fg_map[date_str]

            # BTC日次データ
            btc_row = btc_df[btc_df.index.strftime('%Y-%m-%d') == date_str]
            if len(btc_row) == 0:
                continue
            btc_close = float(btc_row['close'].iloc[0])
            btc_prev = btc_df[btc_df.index < btc_row.index[0]]
            if len(btc_prev) == 0:
                continue
            btc_prev_close = float(btc_prev['close'].iloc[-1])
            btc_return = (btc_close - btc_prev_close) / btc_prev_close * 100

            # オープントレードのTP/SLチェック
            still_open = []
            for trade in open_trades:
                result = self._check_exit(conn, trade, date_str)
                if result:
                    trade.update(result)
                    capital += trade['pnl_amount']
                    self.trades.append(trade)
                else:
                    still_open.append(trade)
            open_trades = still_open
            self.max_simultaneous = max(self.max_simultaneous, len(open_trades))

            # 含み損益を計算してequity_curveに記録
            unrealized_pnl = self._calc_unrealized_pnl(conn, open_trades, date_str)
            equity = capital + unrealized_pnl

            # 同時ポジション上限
            if len(open_trades) >= max_total:
                self.equity_curve.append({'date': date_str, 'capital': equity, 'fg': fg})
                continue

            # シグナル判定
            if self.bot_type == 'alpha':
                signal = self._check_alpha_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'surge':
                signal = self._check_surge_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'momentum':
                signal = self._check_momentum_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'rebound':
                signal = self._check_rebound_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'stability':
                signal = self._check_stability_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'trend':
                signal = self._check_trend_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'cascade':
                signal = self._check_cascade_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'meanrevert':
                signal = self._check_meanrevert_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'breakout':
                signal = self._check_breakout_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'btcfollow':
                signal = self._check_btcfollow_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type == 'weakshort':
                signal = self._check_weakshort_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type.startswith('levburn'):
                signal = self._check_levburn_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            elif self.bot_type in ('feardip', 'sectorlead', 'shortsqueeze', 'sniper', 'scalp', 'event',
                                      'volexhaust', 'fearflat', 'domshift', 'gaptrap', 'sectorsync',
                                      'meanrevert_adaptive', 'meanrevert_tight', 'meanrevert_hybrid',
                                      'meanrevert_newlist', 'meanrevert_tuned',
                                      'ico_meanrevert', 'ico_rebound', 'ico_surge',
                                      # 派生BOT
                                      'sectorsync_nofear', 'sectorsync_nofear_3d',
                                      'sectorsync_nofear_1h', 'sectorsync_nofear_1m',
                                      'weakshort_strongfilter',
                                      'meanrevert_frarb', 'meanrevert_wide', 'meanrevert_strict',
                                      'meanrevert_strict_a', 'meanrevert_strict_b',
                                      'alpha_r7',
                                      'levburn_evolved',
                                      'alpha_relaxed', 'sniper_improved',
                                      'event_wick',
                                      'levburn_sec_lossskip'):
                signal = self._check_external_signal(conn, fg, btc_return, btc_df, date_str, symbols)
            else:
                signal = None

            # 銘柄年齢フィルター（分析用、_listing_dates configで制御）
            if signal and '_listing_dates' in self.config:
                ld_map = self.config['_listing_dates']
                sym = signal['symbol']
                if sym in ld_map:
                    from datetime import datetime as _dt
                    _age = (_dt.strptime(date_str, '%Y-%m-%d') - _dt.strptime(ld_map[sym], '%Y-%m-%d')).days
                    _age_min = self.config.get('_age_min', 0)
                    _age_max = self.config.get('_age_max', 99999)
                    if _age_min is not None and _age < _age_min:
                        signal = None
                    if signal and _age_max is not None and _age > _age_max:
                        signal = None

            # short_onlyフィルター: LONGシグナルを除外
            if signal and self.config.get('short_only', False):
                if signal.get('side') == 'long':
                    signal = None

            # FR方向フィルター: 実FRデータで方向を検証、不一致ならスキップ
            if signal and self.config.get('fr_direction_filter', False):
                real_fr = self._get_real_fr(conn, signal['symbol'], date_str)
                if real_fr is not None:
                    # 実FR > 0 → SHORTのみ許可、実FR < 0 → LONGのみ許可
                    if real_fr > 0 and signal.get('side') == 'long':
                        signal = None
                    elif real_fr < 0 and signal.get('side') == 'short':
                        signal = None
                else:
                    # 実FRなし → proxy FRの絶対値が閾値以上のときのみ許可
                    fr_val = signal.get('fr_for_check') or signal.get('fr_value', 0)
                    if abs(fr_val) < 0.5:
                        signal = None  # FR弱すぎ → 方向不明 → スキップ

            if signal:
                sym = signal['symbol']
                # 同一銘柄ポジション数チェック
                sym_open_count = sum(1 for t in open_trades if t['symbol'] == sym)
                if sym_open_count >= max_per_symbol:
                    self.skipped_count += 1
                else:
                    # 使用可能資金チェック
                    margin_in_use = sum(t['position_value'] for t in open_trades)
                    available = capital - margin_in_use
                    if available < min_position_value:
                        self.skipped_count += 1
                    else:
                        # look-ahead bias回避: 翌日始値でエントリー
                        next_result = self._get_next_open(conn, signal['symbol'], date_str)
                        if next_result is not None:
                            next_open, next_date = next_result
                            signal['entry_price'] = next_open
                            signal['signal_date'] = date_str
                            trade = self._simulate_entry(signal, available, next_date)
                            if trade:
                                if sym_open_count > 0:
                                    self.pyramid_count += 1
                                open_trades.append(trade)

            unrealized_pnl = self._calc_unrealized_pnl(conn, open_trades, date_str)
            self.equity_curve.append({'date': date_str, 'capital': capital + unrealized_pnl, 'fg': fg})

        # 残りオープントレードを最終日で強制決済
        for trade in open_trades:
            last_date = dates[-1] if dates else end_date
            result = self._force_exit(conn, trade, last_date)
            if result:
                trade.update(result)
                capital += trade['pnl_amount']
                self.trades.append(trade)

        conn.close()

        self.equity_curve.append({'date': end_date, 'capital': capital})
        return self.calculate_metrics()

    def _get_daily_ohlcv(self, conn, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """DBから日足取得"""
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000) + 86400000
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            conn, params=(symbol, start_ts, end_ts)
        )
        if len(df) == 0:
            return None
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def _check_alpha_signal(self, conn, fg: int, btc_return: float,
                            btc_df: pd.DataFrame, date_str: str,
                            symbols: list) -> Optional[dict]:
        """Bot-Alpha条件チェック"""
        fear_threshold = self.config.get('fear_threshold', 10)
        btc_return_threshold = self.config.get('btc_return_threshold', -1.0)
        correlation_max = self.config.get('correlation_max', 0.5)
        alpha_min = self.config.get('alpha_min', 3.0)

        if fg >= fear_threshold:
            return None
        if btc_return > btc_return_threshold:
            return None

        # 低相関・高アルファ銘柄スキャン
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 21 * 86400000  # 21日前

        btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(21)['close'].tolist()
        if len(btc_closes) < 21:
            return None

        best_target = None
        best_score = -1

        for symbol in symbols[:100]:  # 上位100銘柄
            sym_df = pd.read_sql_query(
                "SELECT timestamp, close FROM ohlcv "
                "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 20:
                continue

            sym_closes = sym_df['close'].tolist()[-21:]
            if len(sym_closes) < 21 or len(btc_closes) < 21:
                continue

            btc_ret = np.diff(btc_closes) / btc_closes[:-1]
            sym_ret = np.diff(sym_closes) / sym_closes[:-1]
            min_len = min(len(btc_ret), len(sym_ret))
            if min_len < 10:
                continue

            corr = np.corrcoef(btc_ret[-min_len:], sym_ret[-min_len:])[0, 1]
            if np.isnan(corr):
                corr = 1.0
            alpha = (sym_ret[-1] - btc_ret[-1]) * 100

            if corr < correlation_max and alpha >= alpha_min:
                score = (1 - corr) * 50 + min(alpha * 5, 50)
                if score > best_score:
                    best_score = score
                    best_target = {
                        'symbol': symbol,
                        'price': sym_closes[-1],
                        'correlation': float(corr),
                        'alpha': float(alpha),
                        'score': score,
                    }

        return best_target

    def _check_surge_signal(self, conn, fg: int, btc_return: float,
                            btc_df: pd.DataFrame, date_str: str,
                            symbols: list) -> Optional[dict]:
        """Bot-Surge条件チェック"""
        fear_min = self.config.get('fear_min', 25)
        fear_max = self.config.get('fear_max', 45)
        divergence_threshold = self.config.get('divergence_threshold', 3.0)

        if not (fear_min <= fg <= fear_max):
            return None
        if btc_return > 0:
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)

        btc_row = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(1)
        if len(btc_row) == 0:
            return None
        btc_close = float(btc_row['close'].iloc[0])
        btc_prev = btc_df[btc_df.index < btc_row.index[0]].tail(1)
        if len(btc_prev) == 0:
            return None
        btc_prev_close = float(btc_prev['close'].iloc[0])

        best_target = None
        best_divergence = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
                conn, params=(symbol, end_ts)
            )
            if len(sym_df) < 2:
                continue

            sym_close = float(sym_df.iloc[0]['close'])
            sym_prev = float(sym_df.iloc[1]['close'])
            sym_return = (sym_close - sym_prev) / sym_prev * 100
            btc_ret_pct = (btc_close - btc_prev_close) / btc_prev_close * 100
            divergence = sym_return - btc_ret_pct

            if abs(divergence) > divergence_threshold and abs(divergence) > abs(best_divergence):
                best_divergence = divergence
                best_target = {
                    'symbol': symbol,
                    'price': sym_close,
                    'btc_divergence': divergence,
                    'side': 'long' if divergence > 0 else 'short',
                }

        return best_target

    def _check_momentum_signal(self, conn, fg: int, btc_return: float,
                               btc_df: pd.DataFrame, date_str: str,
                               symbols: list) -> Optional[dict]:
        """Bot-Momentum: 出来高急増 + MA乖離（L03+L07+L15）
        条件:
          - Fear&Greed 20〜60（中立〜やや恐怖）
          - 出来高が20日平均の vol_ratio_min 倍以上
          - 終値のMA20乖離が ma20_dev_min〜ma20_dev_max %
          - 乖離方向でロング/ショート判定
        """
        fear_min = self.config.get('fear_min', 20)
        fear_max = self.config.get('fear_max', 60)
        vol_ratio_min = self.config.get('vol_ratio_min', 2.0)
        ma20_dev_min = self.config.get('ma20_dev_min', 3.0)
        ma20_dev_max = self.config.get('ma20_dev_max', 15.0)

        if not (fear_min <= fg <= fear_max):
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 25 * 86400000  # 25日分取得（MA20用）

        best_target = None
        best_score = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 21:
                continue

            closes = sym_df['close'].values
            volumes = sym_df['volume'].values

            # MA20 & 出来高20日平均
            ma20 = np.mean(closes[-20:])
            vol_avg20 = np.mean(volumes[-20:])
            current_close = float(closes[-1])
            current_vol = float(volumes[-1])

            if vol_avg20 <= 0 or ma20 <= 0:
                continue

            vol_ratio = current_vol / vol_avg20
            ma20_dev = (current_close - ma20) / ma20 * 100

            if vol_ratio < vol_ratio_min:
                continue
            if not (ma20_dev_min <= abs(ma20_dev) <= ma20_dev_max):
                continue

            # スコア: 出来高比率 × MA乖離度
            score = vol_ratio * abs(ma20_dev)
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current_close,
                    'vol_ratio': float(vol_ratio),
                    'ma20_dev': float(ma20_dev),
                    'side': 'long' if ma20_dev > 0 else 'short',
                }

        return best_target

    def _check_rebound_signal(self, conn, fg: int, btc_return: float,
                              btc_df: pd.DataFrame, date_str: str,
                              symbols: list) -> Optional[dict]:
        """Bot-Rebound: 暴落後リバウンド狙い（L02+L05+L17）
        条件:
          - Fear&Greed < fear_max（恐怖圏）
          - BTC 7日リターン < btc_7d_threshold（直近で下落）
          - 銘柄が7日安値から recovery_min〜recovery_max % 回復
          - BTC相関 < corr_max（独自の回復力）
        """
        fear_max = self.config.get('fear_max', 25)
        btc_7d_threshold = self.config.get('btc_7d_threshold', -5.0)
        recovery_min = self.config.get('recovery_min', 50)
        recovery_max = self.config.get('recovery_max', 120)
        corr_max = self.config.get('corr_max', 0.5)

        if fg > fear_max:
            return None

        # BTC 7日リターン
        btc_recent = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(8)
        if len(btc_recent) < 8:
            return None
        btc_7d_ret = (float(btc_recent['close'].iloc[-1]) - float(btc_recent['close'].iloc[0])) / float(btc_recent['close'].iloc[0]) * 100
        if btc_7d_ret > btc_7d_threshold:
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 21 * 86400000

        btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(21)['close'].tolist()

        best_target = None
        best_score = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 8:
                continue

            closes = sym_df['close'].values
            recent_7 = closes[-8:]
            low_7d = float(np.min(recent_7[:-1]))  # 直近7日の安値（今日除く）
            current = float(closes[-1])

            if low_7d <= 0:
                continue

            # 回復率: 安値からの戻し %
            drop = float(recent_7[0]) - low_7d
            if drop <= 0:
                continue
            recovery = (current - low_7d) / drop * 100

            if not (recovery_min <= recovery <= recovery_max):
                continue

            # BTC相関チェック
            if len(closes) >= 14 and len(btc_closes) >= 14:
                sym_ret = np.diff(closes[-14:]) / closes[-14:-1]
                btc_ret = np.diff(btc_closes[-14:]) / np.array(btc_closes[-14:-1], dtype=float)
                min_len = min(len(sym_ret), len(btc_ret))
                if min_len >= 10:
                    corr = np.corrcoef(sym_ret[-min_len:], btc_ret[-min_len:])[0, 1]
                    if np.isnan(corr):
                        corr = 1.0
                    if corr > corr_max:
                        continue
                else:
                    corr = 0.0
            else:
                corr = 0.0

            # スコア: 回復率 × (1-相関)
            score = recovery * (1 - corr)
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'recovery_pct': float(recovery),
                    'btc_corr': float(corr),
                    'side': 'long',  # リバウンドは常にロング
                }

        return best_target

    def _check_stability_signal(self, conn, fg: int, btc_return: float,
                                btc_df: pd.DataFrame, date_str: str,
                                symbols: list) -> Optional[dict]:
        """Bot-Stability: 低ボラ安定銘柄のMA回帰（L06+L07+L14）
        条件:
          - Fear&Greed 15〜55（広めの範囲）
          - ATR/close比が atr_ratio_max 以下（低ボラ）
          - ヒゲ/実体比が wick_body_max 以下（安定した足形）
          - MA20乖離が ma20_dev_min〜ma20_dev_max %（回帰狙い逆張り）
        """
        fear_min = self.config.get('fear_min', 15)
        fear_max = self.config.get('fear_max', 55)
        atr_ratio_max = self.config.get('atr_ratio_max', 1.0)
        wick_body_max = self.config.get('wick_body_max', 1.0)
        ma20_dev_min = self.config.get('ma20_dev_min', 2.0)
        ma20_dev_max = self.config.get('ma20_dev_max', 10.0)

        if not (fear_min <= fg <= fear_max):
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 25 * 86400000

        best_target = None
        best_score = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT open, high, low, close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 21:
                continue

            closes = sym_df['close'].values
            highs = sym_df['high'].values
            lows = sym_df['low'].values
            opens = sym_df['open'].values

            # ATR (14日)
            tr_values = []
            for i in range(-14, 0):
                h = float(highs[i])
                l = float(lows[i])
                prev_c = float(closes[i - 1])
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                tr_values.append(tr)
            atr14 = np.mean(tr_values)
            current_close = float(closes[-1])

            if current_close <= 0:
                continue
            atr_ratio = atr14 / current_close * 100

            if atr_ratio > atr_ratio_max:
                continue

            # ヒゲ/実体比（直近5日平均）
            wick_ratios = []
            for i in range(-5, 0):
                body = abs(float(closes[i]) - float(opens[i]))
                upper_wick = float(highs[i]) - max(float(closes[i]), float(opens[i]))
                lower_wick = min(float(closes[i]), float(opens[i])) - float(lows[i])
                total_wick = upper_wick + lower_wick
                if body > 0:
                    wick_ratios.append(total_wick / body)
                else:
                    wick_ratios.append(10.0)  # 同値足はペナルティ
            avg_wick_ratio = np.mean(wick_ratios)

            if avg_wick_ratio > wick_body_max:
                continue

            # MA20乖離
            ma20 = np.mean(closes[-20:])
            ma20_dev = (current_close - ma20) / ma20 * 100

            if not (ma20_dev_min <= abs(ma20_dev) <= ma20_dev_max):
                continue

            # スコア: 低ATR × 低ヒゲ × 乖離度（逆張りなので乖離が大きいほど魅力的）
            score = (1 / max(atr_ratio, 0.01)) * (1 / max(avg_wick_ratio, 0.01)) * abs(ma20_dev)
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current_close,
                    'atr_ratio': float(atr_ratio),
                    'wick_ratio': float(avg_wick_ratio),
                    'ma20_dev': float(ma20_dev),
                    'side': 'short' if ma20_dev > 0 else 'long',  # MA回帰＝逆張り
                }

        return best_target

    # ── 新規6Bot シグナルメソッド ──

    def _check_trend_signal(self, conn, fg: int, btc_return: float,
                            btc_df: pd.DataFrame, date_str: str,
                            symbols: list) -> Optional[dict]:
        """Bot-Trend: 楽観トレンドフォロー（Fear 45-75, BTC上昇, アルトモメンタム）"""
        fear_min = self.config.get('fear_min', 45)
        fear_max = self.config.get('fear_max', 75)
        vol_ratio_min = self.config.get('vol_ratio_min', 1.5)
        ma20_dev_min = self.config.get('ma20_dev_min', 3.0)
        ma20_dev_max = self.config.get('ma20_dev_max', 12.0)

        if not (fear_min <= fg <= fear_max):
            return None
        if btc_return <= 0:
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 25 * 86400000

        best_target = None
        best_score = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 21:
                continue

            closes = sym_df['close'].values
            volumes = sym_df['volume'].values
            current = float(closes[-1])
            ma20 = np.mean(closes[-20:])
            vol_avg20 = np.mean(volumes[-20:])

            if ma20 <= 0 or vol_avg20 <= 0:
                continue

            ma20_dev = (current - ma20) / ma20 * 100
            vol_ratio = float(volumes[-1]) / vol_avg20

            # 7日リターン
            if len(closes) >= 8:
                ret_7d = (current - float(closes[-8])) / float(closes[-8]) * 100
            else:
                continue

            if ma20_dev < ma20_dev_min or ma20_dev > ma20_dev_max:
                continue
            if vol_ratio < vol_ratio_min:
                continue
            if ret_7d <= 0:
                continue

            score = ret_7d * vol_ratio
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'ret_7d': float(ret_7d),
                    'vol_ratio': float(vol_ratio),
                    'ma20_dev': float(ma20_dev),
                    'side': 'long',
                }

        return best_target

    # セクターリーダー → フォロワーマッピング
    SECTOR_LEADERS = {
        'SOL/USDT:USDT': 'Solana',
        'ETH/USDT:USDT': 'Ethereum',
        'BNB/USDT:USDT': 'BNB',
    }

    def _check_cascade_signal(self, conn, fg: int, btc_return: float,
                              btc_df: pd.DataFrame, date_str: str,
                              symbols: list) -> Optional[dict]:
        """Bot-Cascade: セクターリーダー急騰 → フォロワー遅延買い（L04）"""
        fear_min = self.config.get('fear_min', 20)
        fear_max = self.config.get('fear_max', 65)
        leader_gain_min = self.config.get('leader_gain_min', 3.0)
        follower_lag_max = self.config.get('follower_lag_max', 50.0)

        if not (fear_min <= fg <= fear_max):
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)

        # 各リーダーの日次リターンチェック
        for leader_sym, chain in self.SECTOR_LEADERS.items():
            leader_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
                conn, params=(leader_sym, end_ts)
            )
            if len(leader_df) < 2:
                continue

            leader_close = float(leader_df.iloc[0]['close'])
            leader_prev = float(leader_df.iloc[1]['close'])
            leader_ret = (leader_close - leader_prev) / leader_prev * 100

            if leader_ret < leader_gain_min:
                continue

            # このチェーンのフォロワー銘柄を取得
            followers = [r[0] for r in conn.execute(
                "SELECT symbol FROM sector WHERE chain=? AND is_crypto=1 AND symbol != ?",
                (chain, leader_sym)
            ).fetchall()]

            best_follower = None
            best_lag = 0

            for fsym in followers[:50]:
                f_df = pd.read_sql_query(
                    "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                    "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
                    conn, params=(fsym, end_ts)
                )
                if len(f_df) < 2:
                    continue

                f_close = float(f_df.iloc[0]['close'])
                f_prev = float(f_df.iloc[1]['close'])
                f_ret = (f_close - f_prev) / f_prev * 100

                # フォロワーがリーダーより遅れている（リーダーの50%未満の上昇）
                lag_ratio = f_ret / leader_ret * 100 if leader_ret > 0 else 100
                if lag_ratio < follower_lag_max and f_ret >= 0:
                    lag_score = leader_ret - f_ret  # ラグが大きいほど魅力的
                    if lag_score > best_lag:
                        best_lag = lag_score
                        best_follower = {
                            'symbol': fsym,
                            'price': f_close,
                            'leader': leader_sym.split('/')[0],
                            'leader_ret': float(leader_ret),
                            'follower_ret': float(f_ret),
                            'side': 'long',
                        }

            if best_follower:
                return best_follower

        return None

    def _check_meanrevert_signal(self, conn, fg: int, btc_return: float,
                                 btc_df: pd.DataFrame, date_str: str,
                                 symbols: list) -> Optional[dict]:
        """Bot-MeanRevert: 過熱アルトの逆張りショート（Fear 50+, MA20乖離>15%）"""
        fear_min = self.config.get('fear_min', 50)
        fear_max = self.config.get('fear_max', 80)
        ma20_dev_min = self.config.get('ma20_dev_min', 15.0)

        if not (fear_min <= fg <= fear_max):
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 25 * 86400000

        best_target = None
        best_dev = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 21:
                continue

            closes = sym_df['close'].values
            current = float(closes[-1])
            ma20 = np.mean(closes[-20:])

            if ma20 <= 0:
                continue

            ma20_dev = (current - ma20) / ma20 * 100

            # 上方乖離が大きいものをショート
            if ma20_dev < ma20_dev_min:
                continue

            # 出来高確認（売りが始まっている兆候: 直近2日の出来高増加）
            volumes = sym_df['volume'].values
            vol_avg = np.mean(volumes[-20:])
            vol_recent = np.mean(volumes[-2:])
            if vol_avg > 0 and vol_recent / vol_avg > 1.2:
                vol_bonus = vol_recent / vol_avg
            else:
                vol_bonus = 1.0

            score = ma20_dev * vol_bonus
            if score > best_dev:
                best_dev = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'ma20_dev': float(ma20_dev),
                    'side': 'short',
                }

        return best_target

    def _check_breakout_signal(self, conn, fg: int, btc_return: float,
                               btc_df: pd.DataFrame, date_str: str,
                               symbols: list) -> Optional[dict]:
        """Bot-Breakout: レンジ収束 → 出来高爆発ブレイクアウト（L03+L06）"""
        fear_min = self.config.get('fear_min', 20)
        fear_max = self.config.get('fear_max', 55)
        vol_spike_min = self.config.get('vol_spike_min', 3.0)
        atr_contraction = self.config.get('atr_contraction', 0.7)

        if not (fear_min <= fg <= fear_max):
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 30 * 86400000

        best_target = None
        best_score = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 25:
                continue

            closes = sym_df['close'].values
            highs = sym_df['high'].values
            lows = sym_df['low'].values
            volumes = sym_df['volume'].values

            # ATR: 直近7日 vs その前7日
            def calc_atr_simple(h, l, n_start, n_end):
                trs = []
                for i in range(n_start, n_end):
                    trs.append(float(h[i]) - float(l[i]))
                return np.mean(trs) if trs else 0

            atr_recent = calc_atr_simple(highs, lows, -7, len(highs))
            atr_prior = calc_atr_simple(highs, lows, -14, -7)

            if atr_prior <= 0:
                continue

            atr_ratio = atr_recent / atr_prior

            # 出来高スパイク
            vol_avg20 = np.mean(volumes[-21:-1])
            current_vol = float(volumes[-1])
            if vol_avg20 <= 0:
                continue
            vol_ratio = current_vol / vol_avg20

            # ATR収束 + 出来高爆発
            if atr_ratio > atr_contraction:
                continue
            if vol_ratio < vol_spike_min:
                continue

            current = float(closes[-1])
            ma20 = np.mean(closes[-20:])
            side = 'long' if current > ma20 else 'short'

            score = vol_ratio * (1 / max(atr_ratio, 0.01))
            if score > best_score:
                best_score = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'atr_ratio': float(atr_ratio),
                    'vol_ratio': float(vol_ratio),
                    'side': side,
                }

        return best_target

    def _check_btcfollow_signal(self, conn, fg: int, btc_return: float,
                                btc_df: pd.DataFrame, date_str: str,
                                symbols: list) -> Optional[dict]:
        """Bot-BTCFollow: BTC暴落後の反発局面で高ベータアルトを買う（L02+L05）"""
        fear_max = self.config.get('fear_max', 30)
        btc_7d_threshold = self.config.get('btc_7d_threshold', -5.0)
        btc_3d_recovery = self.config.get('btc_3d_recovery', 2.0)
        beta_min = self.config.get('beta_min', 1.2)

        if fg > fear_max:
            return None

        # BTC 7日リターン（暴落確認）
        btc_recent = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(8)
        if len(btc_recent) < 8:
            return None
        btc_7d_ret = (float(btc_recent['close'].iloc[-1]) - float(btc_recent['close'].iloc[0])) / float(btc_recent['close'].iloc[0]) * 100

        if btc_7d_ret > btc_7d_threshold:
            return None

        # BTC 3日リターン（反発確認）
        btc_3d = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(4)
        if len(btc_3d) < 4:
            return None
        btc_3d_ret = (float(btc_3d['close'].iloc[-1]) - float(btc_3d['close'].iloc[0])) / float(btc_3d['close'].iloc[0]) * 100

        if btc_3d_ret < btc_3d_recovery:
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)
        start_ts = end_ts - 21 * 86400000
        btc_closes = btc_df[btc_df.index <= pd.Timestamp(date_str)].tail(21)['close'].tolist()

        best_target = None
        best_beta = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, end_ts)
            )
            if len(sym_df) < 14:
                continue

            closes = sym_df['close'].values
            sym_ret = np.diff(closes[-14:]) / closes[-14:-1]
            btc_ret = np.diff(btc_closes[-14:]) / np.array(btc_closes[-14:-1], dtype=float)
            min_len = min(len(sym_ret), len(btc_ret))
            if min_len < 10:
                continue

            sr = sym_ret[-min_len:]
            br = btc_ret[-min_len:]

            corr = np.corrcoef(sr, br)[0, 1]
            if np.isnan(corr):
                continue

            # ベータ = cov(sym, btc) / var(btc)
            beta = np.cov(sr, br)[0, 1] / np.var(br) if np.var(br) > 0 else 0

            if corr < 0.5 or beta < beta_min:
                continue

            current = float(closes[-1])
            score = beta * corr
            if score > best_beta:
                best_beta = score
                best_target = {
                    'symbol': symbol,
                    'price': current,
                    'beta': float(beta),
                    'correlation': float(corr),
                    'side': 'long',
                }

        return best_target

    def _check_weakshort_signal(self, conn, fg: int, btc_return: float,
                                btc_df: pd.DataFrame, date_str: str,
                                symbols: list) -> Optional[dict]:
        """Bot-WeakShort: 強気相場で弱いアルトをショート（Fear 50-75, BTC+1%以上）"""
        fear_min = self.config.get('fear_min', 50)
        fear_max = self.config.get('fear_max', 75)
        btc_gain_min = self.config.get('btc_gain_min', 1.0)
        divergence_min = self.config.get('divergence_min', 3.0)

        if not (fear_min <= fg <= fear_max):
            return None
        if btc_return < btc_gain_min:
            return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        end_ts = int(dt.timestamp() * 1000)

        best_target = None
        best_div = 0

        for symbol in symbols[:100]:
            sym_df = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 2",
                conn, params=(symbol, end_ts)
            )
            if len(sym_df) < 2:
                continue

            sym_close = float(sym_df.iloc[0]['close'])
            sym_prev = float(sym_df.iloc[1]['close'])
            sym_ret = (sym_close - sym_prev) / sym_prev * 100

            # BTCが上がっているのにアルトが下がっている = 弱い
            divergence = btc_return - sym_ret
            if divergence < divergence_min:
                continue

            score = divergence
            if score > best_div:
                best_div = score
                best_target = {
                    'symbol': symbol,
                    'price': sym_close,
                    'sym_return': float(sym_ret),
                    'btc_return': float(btc_return),
                    'divergence': float(divergence),
                    'side': 'short',
                }

        return best_target

    def _estimate_fr_proxy(self, df: pd.DataFrame, i: int) -> dict:
        """OHLCVから疑似FRスコアを推定"""
        if i < 3:
            return {"fr_proxy": 0.0, "vol_ratio": 1.0, "atr_ratio": 1.0,
                    "daily_change": 0.0, "consecutive_up": 0, "consecutive_down": 0}

        consecutive_up = 0
        consecutive_down = 0
        for j in range(1, 4):
            if i - j >= 0:
                if df.iloc[i - j]["close"] > df.iloc[i - j]["open"]:
                    consecutive_up += 1
                else:
                    consecutive_down += 1

        vol_start = max(0, i - 20)
        vol_window = df.iloc[vol_start:i]["volume"]
        vol_mean = vol_window.mean() if len(vol_window) > 0 else 1.0
        vol_ratio = df.iloc[i]["volume"] / vol_mean if vol_mean > 0 else 1.0

        atr_5_slice = df.iloc[max(0, i - 5):i + 1]
        atr_5 = float(atr_5_slice["high"].max() - atr_5_slice["low"].min()) if len(atr_5_slice) > 0 else 0
        atr_20_slice = df.iloc[max(0, i - 20):i + 1]
        atr_20 = float(atr_20_slice["high"].max() - atr_20_slice["low"].min()) if len(atr_20_slice) > 0 else atr_5
        atr_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0

        open_p = float(df.iloc[i]["open"])
        close_p = float(df.iloc[i]["close"])
        daily_change = (close_p - open_p) / open_p * 100 if open_p > 0 else 0

        fr_proxy = 0.0
        if consecutive_up >= 3:
            fr_proxy += 0.3
        if consecutive_down >= 3:
            fr_proxy -= 0.3
        if vol_ratio > 3.0:
            fr_proxy *= 1.5
        if abs(daily_change) > 10:
            fr_proxy += 0.2 * (1 if daily_change > 0 else -1)

        return {
            "fr_proxy": fr_proxy,
            "vol_ratio": vol_ratio,
            "atr_ratio": atr_ratio,
            "daily_change": daily_change,
            "consecutive_up": consecutive_up,
            "consecutive_down": consecutive_down,
        }

    def _check_levburn_signal(self, conn, fg: int, btc_return: float,
                               btc_df: pd.DataFrame, date_str: str,
                               symbols: list) -> Optional[dict]:
        """Bot-LevBurn: 実FR優先 → 疑似FRフォールバック"""
        fr_threshold = self.config.get('fr_threshold', 0.3)
        vol_threshold = self.config.get('vol_threshold', 3.0)
        extra = self.config.get('extra_conditions', None)
        use_fallback = self.config.get('fallback_to_proxy', True)

        # Fear連携フィルター
        if extra == 'fear_filter':
            if 30 <= fg <= 70:
                return None

        dt = datetime.strptime(date_str, '%Y-%m-%d')
        ts = int(dt.timestamp() * 1000)
        start_ts = ts - 25 * 86400000

        best_candidate = None
        best_score = -1

        for symbol in symbols[:200]:
            df = pd.read_sql_query(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=? AND timeframe='1d' AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                conn, params=(symbol, start_ts, ts)
            )
            if len(df) < 20:
                continue

            i = len(df) - 1

            # 実FR取得を試行
            fr = None
            data_source = "proxy"
            real_fr = self._get_real_fr(conn, symbol, date_str)
            if real_fr is not None:
                fr = real_fr
                data_source = "real"
            elif use_fallback:
                proxy = self._estimate_fr_proxy(df, i)
                fr = proxy["fr_proxy"]
            else:
                continue  # フォールバック無効 & 実FRなし → スキップ

            vol_r = self._estimate_fr_proxy(df, i)["vol_ratio"]
            atr_r = self._estimate_fr_proxy(df, i)["atr_ratio"]

            # FR閾値チェック（実FRは小数値、proxyはスケール済み）
            fr_for_check = fr
            if data_source == "real":
                # 実FRは0.001=0.1%、閾値比較用にproxyスケールに変換
                fr_for_check = fr * 100  # 0.001 → 0.1
            if abs(fr_for_check) < fr_threshold:
                continue

            if vol_r < vol_threshold:
                continue

            # RSI条件（tight variant）
            if extra == 'rsi_extreme':
                closes = df['close'].values[-14:]
                if len(closes) >= 14:
                    diffs = np.diff(closes)
                    gains = np.where(diffs > 0, diffs, 0)
                    losses = np.where(diffs < 0, -diffs, 0)
                    avg_gain = np.mean(gains[-13:]) if len(gains) >= 13 else 0
                    avg_loss = np.mean(losses[-13:]) if len(losses) >= 13 else 0
                    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
                    if fr_for_check > 0 and rsi < 75:
                        continue
                    if fr_for_check < 0 and rsi > 25:
                        continue

            if extra == 'extreme_only':
                if abs(fr_for_check) < 0.5:
                    continue

            if extra == 'fear_filter':
                if fg < 30 and fr_for_check > 0:
                    continue
                if fg > 70 and fr_for_check < 0:
                    continue

            # スコア算出
            score = abs(fr_for_check) * 30 + min(vol_r / 5, 1.0) * 20 + min(atr_r, 2.0) * 10
            if fg < 25 and fr_for_check < 0:
                score += 10
            elif fg > 75 and fr_for_check > 0:
                score += 10

            if score > best_score:
                best_score = score
                side = 'short' if fr_for_check > 0 else 'long'
                best_candidate = {
                    'symbol': symbol,
                    'side': side,
                    'price': float(df.iloc[i]['close']),
                    'fr_value': fr,
                    'fr_for_check': fr_for_check,
                    'data_source': data_source,
                    'vol_ratio': vol_r,
                    'score': score,
                }

        return best_candidate

    def _get_real_fr(self, conn, symbol: str, date_str: str) -> Optional[float]:
        """DBから特定日の実FRを取得"""
        row = conn.execute(
            """SELECT funding_rate FROM funding_rate_history
            WHERE symbol = ? AND timestamp LIKE ?
            ORDER BY timestamp DESC LIMIT 1""",
            (symbol, f"{date_str}%")
        ).fetchone()
        return row[0] if row else None

    def _get_next_open(self, conn, symbol: str, date_str: str) -> Optional[tuple]:
        """翌営業日の始値と日付を取得（look-ahead bias回避）"""
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        next_ts = int((dt + timedelta(days=1)).timestamp() * 1000)
        # 翌日から5日以内の最初のcandle
        max_ts = next_ts + 5 * 86400000
        row = pd.read_sql_query(
            "SELECT timestamp, open FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp < ? ORDER BY timestamp LIMIT 1",
            conn, params=(symbol, next_ts, max_ts)
        )
        if len(row) == 0:
            return None
        entry_dt = pd.to_datetime(row.iloc[0]['timestamp'], unit='ms')
        return float(row.iloc[0]['open']), entry_dt.strftime('%Y-%m-%d')

    def _check_external_signal(self, conn, fg: int, btc_return: float,
                               btc_df: pd.DataFrame, date_str: str,
                               symbols: list) -> Optional[dict]:
        """外部シグナルモジュールへのディスパッチ"""
        import importlib
        module = importlib.import_module(f'src.signals.bot_{self.bot_type}')
        return module.check_signal(conn, fg, btc_return, btc_df, date_str, symbols, self.config)

    def _calc_unrealized_pnl(self, conn, open_trades: list, date_str: str) -> float:
        """オープンポジションの含み損益を時価評価"""
        if not open_trades:
            return 0.0
        total_unrealized = 0.0
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        ts = int(dt.timestamp() * 1000)
        for trade in open_trades:
            row = pd.read_sql_query(
                "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
                "AND timestamp >= ? AND timestamp < ? LIMIT 1",
                conn, params=(trade['symbol'], ts, ts + 86400000)
            )
            if len(row) == 0:
                continue
            close = float(row.iloc[0]['close'])
            entry = trade['entry_price']
            is_long = trade['side'] == 'long'
            if is_long:
                raw_pnl_pct = (close - entry) / entry * 100
            else:
                raw_pnl_pct = (entry - close) / entry * 100
            net_pnl_pct = raw_pnl_pct - self.ROUND_TRIP_COST_PCT
            pnl_leveraged = net_pnl_pct * trade['leverage']
            total_unrealized += trade['position_value'] * (pnl_leveraged / 100)
        return total_unrealized

    def _simulate_entry(self, signal: dict, capital: float, date_str: str) -> Optional[dict]:
        """エントリーシミュレーション（翌日始値、コストは決済時に一括控除）"""
        leverage = signal.get('adaptive_leverage', self.config.get('leverage', 3))
        position_pct = self.config.get('position_size_pct', 30)
        tp_pct = self.config.get('take_profit_pct', 8.0)
        sl_pct = self.config.get('stop_loss_pct', 3.0)

        # ポジションサイズ上限
        # max_position_jpy: 絶対上限（円）。設定があればこちらを優先。
        # max_position_pct: 初期資金の%上限（デフォルト50%）
        max_jpy = self.config.get('max_position_jpy', None)
        if max_jpy is not None:
            max_position_value = float(max_jpy)
        else:
            max_position_value = self.initial_capital * self.config.get('max_position_pct', 50) / 100
        position_value = min(capital * (position_pct / 100), max_position_value)
        side = signal.get('side', 'long')
        entry_price = signal.get('entry_price', signal.get('price'))

        max_hold = self.config.get('max_holding_days', 14)

        return {
            'symbol': signal['symbol'],
            'entry_date': date_str,
            'entry_price': entry_price,
            'side': side,
            'leverage': leverage,
            'position_value': position_value,
            'tp_pct': tp_pct,
            'sl_pct': sl_pct,
            'max_holding_days': max_hold,
        }

    def _check_exit(self, conn, trade: dict, current_date: str) -> Optional[dict]:
        """TP/SLチェック（日足ベース）
        entry_dateは翌日始値エントリーの実日付。
        同日（holding_days=0）でも始値→高値/安値でTP/SL判定可能。
        """
        entry_date = datetime.strptime(trade['entry_date'], '%Y-%m-%d')
        current = datetime.strptime(current_date, '%Y-%m-%d')
        holding_days = (current - entry_date).days

        if holding_days < 0:
            return None

        dt = datetime.strptime(current_date, '%Y-%m-%d')
        ts = int(dt.timestamp() * 1000)
        row = pd.read_sql_query(
            "SELECT high, low, close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp >= ? AND timestamp < ? LIMIT 1",
            conn, params=(trade['symbol'], ts, ts + 86400000)
        )
        if len(row) == 0:
            # max_holding_days超過チェック
            if holding_days >= trade['max_holding_days']:
                return self._force_exit(conn, trade, current_date)
            return None

        high = float(row.iloc[0]['high'])
        low = float(row.iloc[0]['low'])
        close = float(row.iloc[0]['close'])
        entry = trade['entry_price']
        is_long = trade['side'] == 'long'

        tp_price = entry * (1 + trade['tp_pct'] / 100) if is_long else entry * (1 - trade['tp_pct'] / 100)
        sl_price = entry * (1 - trade['sl_pct'] / 100) if is_long else entry * (1 + trade['sl_pct'] / 100)

        # TP/SL判定
        if is_long:
            if high >= tp_price:
                return self._make_exit(trade, tp_price, current_date, holding_days, 'TP')
            if low <= sl_price:
                return self._make_exit(trade, sl_price, current_date, holding_days, 'SL')
        else:
            if low <= tp_price:
                return self._make_exit(trade, tp_price, current_date, holding_days, 'TP')
            if high >= sl_price:
                return self._make_exit(trade, sl_price, current_date, holding_days, 'SL')

        # max_holding_days
        if holding_days >= trade['max_holding_days']:
            return self._make_exit(trade, close, current_date, holding_days, 'TIMEOUT')

        return None

    def _make_exit(self, trade: dict, exit_price: float, date: str,
                   holding_days: int, reason: str) -> dict:
        """エグジット結果生成（往復コスト一括控除）

        コスト計算方式:
          raw_pnl = (exit - entry) / entry  （生PnL）
          net_pnl = raw_pnl - ROUND_TRIP_COST_PCT  （往復0.22%を一括控除）
        これにより entry/exit 価格個別調整による相殺バグを回避。
        """
        entry = trade['entry_price']
        is_long = trade['side'] == 'long'

        # 生PnL（コストなし）
        if is_long:
            raw_pnl_pct = (exit_price - entry) / entry * 100
        else:
            raw_pnl_pct = (entry - exit_price) / entry * 100

        # 往復コスト一括控除（常に損失方向）
        net_pnl_pct = raw_pnl_pct - self.ROUND_TRIP_COST_PCT

        pnl_leveraged = net_pnl_pct * trade['leverage']
        pnl_amount = trade['position_value'] * (pnl_leveraged / 100)

        return {
            'exit_date': date,
            'exit_price': exit_price,
            'exit_reason': reason,
            'holding_days': holding_days,
            'raw_pnl_pct': round(raw_pnl_pct, 2),
            'pnl_pct': round(net_pnl_pct, 2),
            'pnl_leveraged_pct': round(pnl_leveraged, 2),
            'pnl_amount': round(pnl_amount, 2),
        }

    def _force_exit(self, conn, trade: dict, date_str: str) -> Optional[dict]:
        """強制決済（最終日 or max_holding超過）"""
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        ts = int(dt.timestamp() * 1000)
        row = pd.read_sql_query(
            "SELECT close FROM ohlcv WHERE symbol=? AND timeframe='1d' "
            "AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            conn, params=(trade['symbol'], ts + 86400000)
        )
        if len(row) == 0:
            return None

        close = float(row.iloc[0]['close'])
        entry_date = datetime.strptime(trade['entry_date'], '%Y-%m-%d')
        holding_days = (dt - entry_date).days
        return self._make_exit(trade, close, date_str, holding_days, 'TIMEOUT')

    def calculate_metrics(self) -> dict:
        """成績指標計算

        MDD: equity_curveベース（含み損込み）。ピーク残高からの最大下落率。
        Sharpe: 日次リターン系列から年率化。トレードがない日はリターン0。
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'total_return_pct': 0,
                'max_drawdown_pct': 0,
                'avg_pnl_pct': 0,
                'avg_holding_days': 0,
                'best_trade': None,
                'worst_trade': None,
                'sharpe_ratio': 0,
                'monthly_returns': [],
                'min_capital': self.initial_capital,
                'max_simultaneous': getattr(self, 'max_simultaneous', 0),
                'pyramid_count': getattr(self, 'pyramid_count', 0),
                'skipped_count': getattr(self, 'skipped_count', 0),
                'trades': self.trades,
                'equity_curve': self.equity_curve,
            }

        wins = [t for t in self.trades if t.get('pnl_leveraged_pct', 0) > 0]
        losses = [t for t in self.trades if t.get('pnl_leveraged_pct', 0) <= 0]
        total = len(self.trades)
        win_rate = len(wins) / total * 100 if total > 0 else 0

        gross_profit = sum(t['pnl_amount'] for t in wins) if wins else 0
        gross_loss = abs(sum(t['pnl_amount'] for t in losses)) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        final_capital = self.initial_capital + sum(t.get('pnl_amount', 0) for t in self.trades)
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # MDD: equity_curveベース（含み損込み残高のピークからの最大下落率）
        peak = self.initial_capital
        max_dd = 0.0
        min_capital = self.initial_capital
        for ec in self.equity_curve:
            equity = ec.get('capital', self.initial_capital)
            min_capital = min(min_capital, equity)
            peak = max(peak, equity)
            if peak > 0:
                dd = (equity - peak) / peak * 100
                max_dd = min(max_dd, dd)

        avg_pnl = np.mean([t.get('pnl_leveraged_pct', 0) for t in self.trades])
        avg_days = np.mean([t.get('holding_days', 0) for t in self.trades])

        # Sharpe: 日次リターン系列から年率化
        # equity_curveから日次リターンを構築（トレードのない日は0%リターン）
        if len(self.equity_curve) >= 2:
            daily_returns = []
            for i in range(1, len(self.equity_curve)):
                prev_eq = self.equity_curve[i - 1].get('capital', self.initial_capital)
                curr_eq = self.equity_curve[i].get('capital', self.initial_capital)
                if prev_eq > 0:
                    daily_returns.append((curr_eq - prev_eq) / prev_eq)
                else:
                    daily_returns.append(0.0)
            if len(daily_returns) > 1 and np.std(daily_returns) > 0:
                sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(365)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        best = max(self.trades, key=lambda t: t.get('pnl_leveraged_pct', 0))
        worst = min(self.trades, key=lambda t: t.get('pnl_leveraged_pct', 0))

        # Monthly returns
        monthly = {}
        for t in self.trades:
            month = t.get('exit_date', t['entry_date'])[:7]
            monthly[month] = monthly.get(month, 0) + t.get('pnl_amount', 0)
        monthly_returns = [{'month': k, 'pnl': round(v, 2)} for k, v in sorted(monthly.items())]

        return {
            'total_trades': total,
            'win_rate': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2),
            'total_return_pct': round(total_return, 1),
            'max_drawdown_pct': round(max_dd, 1),
            'avg_pnl_pct': round(float(avg_pnl), 2),
            'avg_holding_days': round(float(avg_days), 1),
            'best_trade': {
                'symbol': best['symbol'],
                'pnl_pct': best.get('pnl_leveraged_pct', 0),
                'date': best['entry_date'],
            },
            'worst_trade': {
                'symbol': worst['symbol'],
                'pnl_pct': worst.get('pnl_leveraged_pct', 0),
                'date': worst['entry_date'],
            },
            'sharpe_ratio': round(float(sharpe), 2),
            'monthly_returns': monthly_returns,
            'final_capital': round(final_capital, 0),
            'min_capital': round(min_capital, 0),
            'max_simultaneous': getattr(self, 'max_simultaneous', 0),
            'pyramid_count': getattr(self, 'pyramid_count', 0),
            'skipped_count': getattr(self, 'skipped_count', 0),
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

    def trades_to_csv(self, filepath: str):
        """トレード一覧をCSV保存"""
        if not self.trades:
            return
        df = pd.DataFrame(self.trades)
        cols = ['symbol', 'entry_date', 'entry_price', 'side', 'leverage',
                'exit_date', 'exit_price', 'exit_reason', 'holding_days',
                'pnl_pct', 'pnl_leveraged_pct', 'pnl_amount']
        available = [c for c in cols if c in df.columns]
        df[available].to_csv(filepath, index=False)
