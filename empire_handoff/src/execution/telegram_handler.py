"""Telegram対話ハンドラー — ボットに話しかけて情報取得"""
import os
import html
import asyncio
import logging
import traceback
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv
from src.core.bot_display_names import get_display_name

load_dotenv()
logger = logging.getLogger("empire")


class TelegramBotHandler:
    """Telegramボットの対話機能"""

    def __init__(self, db=None, engine=None):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.db = db
        self.engine = engine
        self._app = None

    async def start(self):
        """ボットのポーリング開始（既存セッションをクリアしてから起動）"""
        if not self.token:
            logger.warning("[TelegramHandler] TELEGRAM_BOT_TOKEN未設定")
            return

        # 既存のpollingセッションをクリア（Conflict回避）
        try:
            bot = Bot(token=self.token)
            await bot.delete_webhook(drop_pending_updates=True)
            # 短いタイムアウトでgetUpdatesを呼んで既存セッションを切断
            try:
                await bot.get_updates(offset=-1, timeout=1)
            except Exception:
                pass
            await bot.shutdown()
            logger.info("[TelegramHandler] 既存セッションをクリア")
        except Exception as e:
            logger.warning(f"[TelegramHandler] セッションクリア失敗（初回起動時は正常）: {e}")

        self._app = Application.builder().token(self.token).build()

        # エラーハンドラー登録（無応答防止）
        self._app.add_error_handler(self._error_handler)

        # コマンド登録
        self._app.add_handler(CommandHandler("start", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("positions", self._cmd_positions))
        self._app.add_handler(CommandHandler("pos", self._cmd_positions))
        self._app.add_handler(CommandHandler("pnl", self._cmd_pnl))
        self._app.add_handler(CommandHandler("bots", self._cmd_bots))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("report", self._cmd_report))
        self._app.add_handler(CommandHandler("hot", self._cmd_hot))
        self._app.add_handler(CommandHandler("detail", self._cmd_detail))
        self._app.add_handler(CommandHandler("last", self._cmd_last))
        self._app.add_handler(CommandHandler("scores", self._cmd_scores))

        # 自然文メッセージ（グループでも受信するためfilterなし）
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message"],  # メッセージのみ
        )
        logger.info("[TelegramHandler] ボット対話開始")

    async def stop(self):
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def _error_handler(self, update, context: ContextTypes.DEFAULT_TYPE):
        """エラーハンドラー — 例外を握りつぶさずログ＋ユーザー通知"""
        logger.error(f"[TelegramHandler] Error: {context.error}")
        logger.error(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
        if update and update.message:
            try:
                await update.message.reply_text(
                    f"⚠️ エラーが発生しました: {str(context.error)[:200]}")
            except Exception:
                pass

    # ── コマンドハンドラー ──

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "📋 使えるコマンド:\n\n"
            "📊 基本情報\n"
            "/positions — 保有ポジション一覧\n"
            "/pnl — PNLサマリー\n"
            "/bots — Bot稼働状況\n"
            "/status — システム状態\n\n"
            "🔥 シグナル詳細\n"
            "/hot — 直近の激アツ通知+スコア内訳\n"
            "/last — 直近のBot発火シグナル詳細\n"
            "/scores — 現在のTier通過銘柄+スコア\n"
            "/detail BTC — 特定銘柄のスコア内訳\n\n"
            "📋 レポート\n"
            "/report — Bot活動レポート(24h)\n"
            "/help — このヘルプ\n\n"
            "💬 自然文でも聞けます:\n"
            "「激アツは？」「スコアは？」「直近のシグナル」等"
        )
        await update.message.reply_text(text)

    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_positions_text)

    async def _cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_pnl_text)

    async def _cmd_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_bots_text)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_status_text)

    async def _cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_activity_report_text)

    async def _cmd_hot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_hot_details_text)

    async def _cmd_last(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_last_signals_text)

    async def _cmd_scores(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._safe_reply(update, self._get_current_scores_text)

    async def _cmd_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """特定銘柄のスコア詳細: /detail BTC"""
        args = context.args
        if not args:
            await update.message.reply_text("使い方: /detail BTC\n銘柄名を指定してください")
            return
        symbol_query = args[0].upper()
        await self._safe_reply(update, lambda: self._get_symbol_detail_text(symbol_query))

    async def _safe_reply(self, update: Update, text_fn):
        """テキスト生成→HTML送信。失敗したらプレーンテキストで再送"""
        try:
            text = text_fn()
        except Exception as e:
            logger.error(f"[TelegramHandler] text_fn error: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ データ取得エラー: {e}")
            return
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"[TelegramHandler] HTML send error: {e}")
            # HTMLパース失敗 → プレーンテキストで再送
            import re
            plain = re.sub(r'<[^>]+>', '', text)
            await update.message.reply_text(plain[:4000])

    # ── 自然文解析 ──

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        msg = update.message.text.lower()
        # ポジション関連
        if any(w in msg for w in ['持ってる', 'ポジション', '保有', 'position', 'holdings']):
            text = self._get_positions_text()
        elif any(w in msg for w in ['損益', 'pnl', '利益', '損失', '儲かって']):
            text = self._get_pnl_text()
        elif any(w in msg for w in ['bot', 'ボット', '稼働', '動いてる']):
            text = self._get_bots_text()
        elif any(w in msg for w in ['状態', 'ステータス', 'status', '元気']):
            text = self._get_status_text()
        elif any(w in msg for w in ['激アツ', 'hot', 'アツい', '通知詳細', '根拠']):
            text = self._get_hot_details_text()
        elif any(w in msg for w in ['スコア', 'score', 'tier', '内訳', '採点']):
            text = self._get_current_scores_text()
        elif any(w in msg for w in ['直近', 'シグナル', 'signal', '発火', '最近の']):
            text = self._get_last_signals_text()
        elif any(w in msg for w in ['レポート', 'report', '活動', '成績']):
            text = self._get_activity_report_text()
        else:
            # 認識できないメッセージにはグループでは反応しない（ノイズ防止）
            if str(update.message.chat_id).startswith('-'):
                return  # グループでは無視
            text = (
                "🤔 すみません、よくわかりませんでした。\n\n"
                "/help でコマンド一覧を確認できます。\n"
                "「今何持ってる？」「損益は？」など聞いてみてください。"
            )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # ── データ取得 ──

    def _get_positions_text(self) -> str:
        if not self.db:
            return "⚠️ DB未接続"
        conn = self.db._get_conn()
        try:
            rows = conn.execute(
                "SELECT bot_type, symbol, side, entry_price, current_price, "
                "unrealized_pnl_pct, leverage, signal_time "
                "FROM paper_signals WHERE status='open' ORDER BY signal_time DESC"
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if not rows:
            return "📭 保有ポジションなし"

        lines = [f'📊 <b>保有ポジション ({len(rows)}件)</b>', '']
        total_pnl = 0
        for bot, sym, side, entry, cur, pnl, lev, time_str in rows:
            sym_short = sym.replace('/USDT:USDT', '').replace('_USDT', '')
            pnl = pnl or 0
            total_pnl += pnl
            emoji = '🟢' if pnl >= 0 else '🔴'
            arrow = '📈' if side == 'long' else '📉'
            cur_str = f'${cur:,.6f}' if cur else '-'
            lines.append(
                f'{emoji} <b>{sym_short}</b> {arrow}{side.upper()} {int(lev)}x\n'
                f'   Entry: ${entry:,.6f} → {cur_str}\n'
                f'   PnL: {pnl:+.2f}%  Bot: {get_display_name(bot)}'
            )

        total_cls = '📈' if total_pnl >= 0 else '📉'
        lines.append(f'\n{total_cls} <b>合計含み損益: {total_pnl:+.2f}%</b>')
        return '\n'.join(lines)

    def _get_pnl_text(self) -> str:
        if not self.db:
            return "⚠️ DB未接続"
        conn = self.db._get_conn()
        try:
            # 直近の決済
            rows = conn.execute(
                "SELECT bot_type, symbol, realized_pnl_pct, exit_reason, exit_time "
                "FROM paper_signals WHERE status='closed' "
                "ORDER BY exit_time DESC LIMIT 10"
            ).fetchall()
            # 合計
            totals = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN realized_pnl_pct>0 THEN 1 ELSE 0 END), "
                "SUM(realized_pnl_pct) FROM paper_signals WHERE status='closed'"
            ).fetchone()
        except Exception:
            rows, totals = [], (0, 0, 0)
        finally:
            conn.close()

        total_trades = totals[0] or 0
        wins = totals[1] or 0
        total_pnl = totals[2] or 0
        wr = f'{wins/total_trades*100:.0f}%' if total_trades > 0 else '-'

        lines = [
            f'💰 <b>PNLサマリー</b>',
            f'取引数: {total_trades} | 勝率: {wr} | 合計PNL: {total_pnl:+.2f}%',
            '',
            '<b>直近10件:</b>'
        ]
        for bot, sym, pnl, reason, time_str in rows:
            sym_short = sym.replace('/USDT:USDT', '').replace('_USDT', '')
            pnl = pnl or 0
            emoji = '✅' if pnl > 0 else '❌'
            lines.append(f'{emoji} {sym_short} ({get_display_name(bot)}): {pnl:+.2f}% [{reason or ""}]')

        return '\n'.join(lines)

    def _get_bots_text(self) -> str:
        if not self.engine:
            return "⚠️ Engine未接続"

        lines = []
        fg = '?'
        try:
            fg = self.engine.state.fear_greed
        except Exception:
            pass
        lines.append(f'🤖 Bot稼働状況 (Fear: {fg})')
        lines.append('')

        # BotManagerから全Bot状態を取得
        bm = getattr(self.engine, 'bot_manager', None)
        if bm and hasattr(bm, 'workers') and bm.workers:
            for name in sorted(bm.workers.keys()):
                try:
                    worker = bm.workers[name]
                    mode = worker.mode.value
                    if mode == 'disabled':
                        icon = '⚫'
                        status_str = '停止'
                    elif mode == 'live':
                        icon = '🔴'
                        status_str = 'LIVE'
                    else:
                        icon = '🔵'
                        status_str = 'ペーパー'
                    extra = f' [{worker.status}]' if worker.status not in ('waiting', 'disabled') else ''
                    lines.append(f'{icon} {get_display_name(name)} ({status_str}){extra}')
                except Exception as e:
                    lines.append(f'⚠️ {get_display_name(name)}: エラー({e})')
        else:
            # フォールバック
            try:
                alpha_active = getattr(self.engine.bot_alpha, 'activated', False) if hasattr(self.engine, 'bot_alpha') else False
                surge_active = getattr(self.engine.bot_surge, 'activated', False) if hasattr(self.engine, 'bot_surge') else False
                lines.append(f'{"🟢" if alpha_active else "⚪"} Alpha ({"稼働" if alpha_active else "待機"})')
                lines.append(f'{"🟢" if surge_active else "⚪"} Surge ({"稼働" if surge_active else "待機"})')
            except Exception:
                lines.append('⚠️ Bot情報取得不可')

        # LevBurn
        try:
            if hasattr(self.engine, 'levburn_engine') and self.engine.levburn_engine:
                lines.append('🟢 LevBurn (FR監視)')
            if hasattr(self.engine, 'ws_feed') and self.engine.ws_feed:
                ws_ok = getattr(self.engine.ws_feed, 'connected', False)
                lines.append(f'{"🟢" if ws_ok else "🔴"} LevBurn-Sec (WS)')
        except Exception:
            pass

        return '\n'.join(lines)

    def _get_status_text(self) -> str:
        now = datetime.now()
        lines = [f'⚙️ <b>システム状態</b>', f'時刻: {now.strftime("%Y-%m-%d %H:%M:%S")}', '']

        if self.engine:
            try:
                state = self.engine.state
                lines.append(f'Fear&Greed: {state.fear_greed}')
                lines.append(f'Regime: {state.regime}')
                lines.append(f'Cycle: {state.cycle_count}')
                if hasattr(state, 'btc_price') and state.btc_price:
                    lines.append(f'BTC: ${state.btc_price:,.0f}')
            except Exception as e:
                lines.append(f'⚠️ 状態取得エラー: {e}')

        return '\n'.join(lines)

    def _get_activity_report_text(self) -> str:
        if not self.db:
            return "⚠️ DB未接続"
        try:
            from src.core.bot_activity_logger import BotActivityLogger
            al = BotActivityLogger(self.db)
            text = al.generate_telegram_summary(hours=24)
            return text or '📭 直近24時間のBot活動なし'
        except Exception as e:
            return f'⚠️ レポート生成エラー: {e}'

    # ── 激アツ通知・スコア詳細 ──

    def _get_hot_details_text(self) -> str:
        """直近の激アツ通知の詳細（alert_logから取得）"""
        if not self.db:
            return "⚠️ DB未接続"
        conn = self.db._get_conn()
        try:
            rows = conn.execute(
                "SELECT symbol, alert_time, alert_price, tier1_score, tier2_score, "
                "regime, fear_greed, pnl_1h_pct, pnl_24h_pct "
                "FROM alert_log ORDER BY alert_time DESC LIMIT 5"
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if not rows:
            return "📭 直近の激アツ通知なし"

        lines = ['🔥 直近の激アツ通知 (5件)', '']
        for sym, time_str, price, t1, t2, regime, fg, pnl_1h, pnl_24h in rows:
            sym_short = sym.replace('/USDT:USDT', '').replace('_USDT', '')
            t1 = t1 or 0
            t2 = t2 or 0
            total = t1 + t2
            # 通知レベル判定
            if total >= 60:
                level = '🔥🔥🔥'
            elif total >= 40:
                level = '🔥'
            else:
                level = '👀'
            ts = (time_str or '')[:16].replace('T', ' ')
            pnl_1h_str = f'{pnl_1h:+.1f}%' if pnl_1h else '-'
            pnl_24h_str = f'{pnl_24h:+.1f}%' if pnl_24h else '-'
            lines.append(
                f'{level} {sym_short} ${price:,.4f}\n'
                f'  Tier1: {t1:.0f}pt  Tier2: {t2:.0f}pt  合計: {total:.0f}pt\n'
                f'  Regime: {regime or "?"}  F&G: {fg or "?"}\n'
                f'  結果: 1h {pnl_1h_str} / 24h {pnl_24h_str}\n'
                f'  {ts}'
            )
        return '\n'.join(lines)

    def _get_last_signals_text(self) -> str:
        """直近のBot発火シグナル詳細（bot_activity_log）"""
        if not self.db:
            return "⚠️ DB未接続"
        conn = self.db._get_conn()
        try:
            rows = conn.execute(
                "SELECT timestamp, bot_name, event_type, symbol, side, leverage, "
                "entry_price, exit_price, tp_price, sl_price, pnl_pct, exit_reason, details "
                "FROM bot_activity_log "
                "WHERE event_type IN ('signal','exit') "
                "ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if not rows:
            return "📭 直近のシグナルなし"

        lines = ['📡 直近のBot発火/決済 (10件)', '']
        for ts, bot, evt, sym, side, lev, entry, exit_p, tp, sl, pnl, reason, details in rows:
            sym_short = (sym or '').replace('/USDT:USDT', '').replace('_USDT', '')
            t = (ts or '')[:16].replace('T', ' ')

            if evt == 'signal':
                arrow = '📈' if side == 'long' else '📉'
                lev_str = f'{int(lev)}x' if lev else ''
                tp_str = f'${tp:,.6f}' if tp else '-'
                sl_str = f'${sl:,.6f}' if sl else '-'
                lines.append(
                    f'{arrow} [{get_display_name(bot)}] {sym_short} {(side or "").upper()} {lev_str}\n'
                    f'  Entry: ${entry:,.6f}\n'
                    f'  TP: {tp_str} / SL: {sl_str}\n'
                    f'  {details or ""}\n'
                    f'  {t}'
                )
            else:  # exit
                pnl = pnl or 0
                icon = '✅' if pnl > 0 else '❌'
                lines.append(
                    f'{icon} [{get_display_name(bot)}] {sym_short} 決済 {reason or ""}\n'
                    f'  PnL: {pnl:+.2f}%\n'
                    f'  Entry: ${entry:,.6f} -> Exit: ${exit_p:,.6f}\n'
                    f'  {t}'
                )
        return '\n'.join(lines)

    def _get_current_scores_text(self) -> str:
        """現在のTier1/2通過銘柄とスコア"""
        if not self.engine:
            return "⚠️ Engine未接続"

        lines = []
        try:
            state = self.engine.state
            t1_list = state.get_tier1_passed()
            t2_list = state.get_tier2_passed()

            lines.append(f'📊 Tier通過銘柄 (Cycle {state.cycle_count})')
            lines.append(f'Fear&Greed: {state.fear_greed} | Regime: {state.regime}')
            lines.append('')

            if t2_list:
                t2_sorted = sorted(t2_list, key=lambda s: s.tier1_score + s.tier2_score, reverse=True)
                lines.append(f'🏆 Tier2通過 ({len(t2_sorted)}件) — 上位10:')
                for s in t2_sorted[:10]:
                    sym_short = s.symbol.replace('/USDT:USDT', '').replace('_USDT', '')
                    total = s.tier1_score + s.tier2_score
                    fr = f'FR:{s.funding_rate:+.4f}' if s.funding_rate else ''
                    sec = f'[{s.sector}]' if s.sector else ''
                    # Tier1スコア内訳
                    t1d = getattr(s, 'tier1_details', {}) or {}
                    breakdown = []
                    label_map = {'L02': '聖域', 'L03': '出来高', 'L09': '変動',
                                 'L17': '低相関', 'L_alpha': 'α乖離'}
                    for k, label in label_map.items():
                        d = t1d.get(k, {})
                        sc = d.get('score', 0)
                        if sc != 0:
                            breakdown.append(f'{label}{sc:+.0f}')
                    # Tier2内訳
                    t2d = getattr(s, 'tier2_details', {}) or {}
                    t2_label = {'L08': 'FR', 'L10': '板厚', 'L13': '清算'}
                    for k, label in t2_label.items():
                        d = t2d.get(k, {})
                        sc = d.get('score', 0)
                        if sc != 0:
                            breakdown.append(f'{label}{sc:+.0f}')
                    bd_str = ', '.join(breakdown) if breakdown else ''
                    lines.append(
                        f'  {sym_short}: {total:.0f}pt (T1:{s.tier1_score:.0f} T2:{s.tier2_score:.0f})\n'
                        f'    {bd_str} {fr} {sec}'
                    )
            else:
                lines.append('📭 Tier2通過銘柄なし')

            if t1_list and not t2_list:
                lines.append(f'\nTier1通過: {len(t1_list)}件（Tier2未通過）')

        except Exception as e:
            lines.append(f'⚠️ スコア取得エラー: {e}')

        return '\n'.join(lines)

    def _get_symbol_detail_text(self, query: str) -> str:
        """特定銘柄のスコア詳細"""
        if not self.engine:
            return "⚠️ Engine未接続"

        try:
            state = self.engine.state
            # 部分一致で検索
            all_passed = state.get_tier1_passed() + state.get_tier2_passed()
            # 重複排除
            seen = set()
            candidates = []
            for s in all_passed:
                if s.symbol not in seen:
                    seen.add(s.symbol)
                    candidates.append(s)

            match = None
            for s in candidates:
                sym_clean = s.symbol.replace('/USDT:USDT', '').replace('_USDT', '').upper()
                if query in sym_clean or sym_clean in query:
                    match = s
                    break

            if not match:
                return f"📭 '{query}' はTier1/2通過リストに見つかりません"

            sym_short = match.symbol.replace('/USDT:USDT', '').replace('_USDT', '')
            lines = [
                f'🔍 {sym_short} スコア詳細',
                f'価格: ${match.last_price:,.6f}' if match.last_price else '',
                f'Tier1: {match.tier1_score:.1f}pt  Tier2: {match.tier2_score:.1f}pt  合計: {match.tier1_score + match.tier2_score:.1f}pt',
                '',
            ]

            # Tier1 内訳
            t1d = getattr(match, 'tier1_details', {}) or {}
            lines.append('--- Tier1 内訳 ---')
            t1_labels = {
                'L02': ('聖域(Alpha Sanctuary)', '200日安値との距離'),
                'L03': ('出来高スパイク', '直近volume/20MA比'),
                'L09': ('急変動', '5分足の変動率'),
                'L17': ('低BTC相関', 'BTCとの相関係数'),
                'L_alpha': ('Alpha乖離', 'BTC比の超過リターン'),
            }
            for k, (label, desc) in t1_labels.items():
                d = t1d.get(k, {})
                sc = d.get('score', 0)
                passed = '✅' if d.get('passed') else '❌'
                reason = d.get('reason', '')
                lines.append(f'{passed} {label}: {sc:+.0f}pt')
                if reason:
                    lines.append(f'    {reason}')

            # Tier2 内訳
            t2d = getattr(match, 'tier2_details', {}) or {}
            lines.append('')
            lines.append('--- Tier2 内訳 ---')
            t2_labels = {
                'L08': ('Funding Rate&OI', 'ショートスクイーズ/過熱判定'),
                'L10': ('板厚(流動性)', 'オーダーブック深度'),
                'L13': ('清算リスク(LCEF)', 'OI+極端FR'),
            }
            for k, (label, desc) in t2_labels.items():
                d = t2d.get(k, {})
                sc = d.get('score', 0)
                passed = '✅' if d.get('passed') else '❌'
                reason = d.get('reason', '')
                veto = ' ⛔VETO' if d.get('veto') else ''
                lines.append(f'{passed} {label}: {sc:+.0f}pt{veto}')
                if reason:
                    lines.append(f'    {reason}')

            # 追加データ
            lines.append('')
            lines.append('--- 補足データ ---')
            if match.funding_rate:
                lines.append(f'Funding Rate: {match.funding_rate:+.6f}')
            if match.btc_correlation is not None:
                lines.append(f'BTC相関: {match.btc_correlation:.3f}')
            if match.btc_alpha:
                lines.append(f'BTC Alpha: {match.btc_alpha:+.2f}%')
            if match.rsi_14:
                lines.append(f'RSI(14): {match.rsi_14:.1f}')
            if match.sector:
                lines.append(f'セクター: {match.sector}')

            return '\n'.join(lines)

        except Exception as e:
            return f'⚠️ 詳細取得エラー: {e}'
