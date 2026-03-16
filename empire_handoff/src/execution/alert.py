"""Telegramアラート送信 - v3.2: 5セクション新フォーマット"""
import os
import html
import asyncio
from datetime import datetime, timedelta
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from dotenv import load_dotenv
from src.core.state import SymbolState
from src.core.commentary import Commentary
from src.core.bot_display_names import get_display_name

load_dotenv()


class TelegramAlert:
    def __init__(self, db=None):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.bot = Bot(token=self.token)
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.community_chat_id = os.getenv('TELEGRAM_COMMUNITY_CHAT_ID')
        self.db = db

    async def send_message(self, text: str, reply_markup=None) -> bool:
        try:
            # Telegram上限4096文字
            if len(text) > 4000:
                text = text[:4000] + "\n...(truncated)"
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return True
        except Exception as e:
            print(f"[Telegram Error] {e}")
            return False

    # ========================================
    # リアルタイムアラート（即時送信 3種のみ）
    # ========================================

    async def send_bot_alpha_alert(self, signal: dict) -> bool:
        """Bot-Alpha 極限一撃モード アラート"""
        entry = signal['entry']
        activation = signal['activation']
        targets = signal.get('all_targets', [])

        targets_text = '\n'.join([
            f"  {html.escape(t['symbol'])}: corr={t['correlation']:.2f}, α={t['alpha']:+.1f}%, score={t['score']:.0f}"
            for t in targets[:5]
        ])

        text = (
            f"🔴🔴🔴 <b>Bot-Alpha: 極限一撃モード発火!</b>\n\n"
            f"😱 Fear&amp;Greed: {signal['fear_greed']}\n"
            f"📉 BTC日次: {activation['btc_return']:+.1f}%\n"
            f"📊 BTC.D変化: {activation['btc_d_change']:+.1f}%\n\n"
            f"🎯 <b>エントリー: {html.escape(entry['symbol'])}</b>\n"
            f"├ 方向: {entry['side'].upper()}\n"
            f"├ レバレッジ: {entry['leverage']}x\n"
            f"├ ポジション: 資金の{entry['position_size_pct']}%\n"
            f"├ TP: +{entry['take_profit_pct']}%\n"
            f"├ SL: -{entry['stop_loss_pct']}%\n"
            f"└ 価格: ${entry['entry_price']:,.4f}\n\n"
            f"📋 候補銘柄 Top5:\n{targets_text}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if self.db:
            self.db.log_alert(entry['symbol'], entry['entry_price'], 0, 0, 'bot_alpha', signal['fear_greed'])

        return await self.send_message(text)

    async def send_bot_surge_alert(self, signal: dict) -> bool:
        """Bot-Surge 日常循環モード アラート"""
        entry = signal.get('entry', {})
        cascades = signal.get('sector_cascades', [])
        divergent = signal.get('divergent_symbols', [])

        cascade_text = '\n'.join([
            f"  {html.escape(c['leader'])}→{html.escape(c['follower'])} (lag {c['lag_days']}d, 経過{c['elapsed_days']}d)"
            for c in cascades[:5]
        ]) or '  なし'

        div_text = '\n'.join([
            f"  {html.escape(d['symbol'])}: BTC乖離{d['btc_divergence']:+.1f}%"
            for d in divergent[:5]
        ]) or '  なし'

        text = (
            f"🟡 <b>Bot-Surge: 日常循環モード</b>\n\n"
            f"😰 Fear&amp;Greed: {signal['fear_greed']}\n\n"
        )

        if entry:
            text += (
                f"🎯 <b>エントリー: {html.escape(entry['symbol'])}</b>\n"
                f"├ 方向: {entry['side'].upper()}\n"
                f"├ レバレッジ: {entry['leverage']}x\n"
                f"├ ポジション: 資金の{entry['position_size_pct']}%\n"
                f"├ TP: +{entry['take_profit_pct']}%\n"
                f"├ SL: -{entry['stop_loss_pct']}%\n"
                f"└ 理由: {html.escape(entry.get('reason', ''))}\n\n"
            )

        text += (
            f"🔄 セクター波及:\n{cascade_text}\n\n"
            f"📊 BTC乖離銘柄:\n{div_text}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if self.db and entry:
            self.db.log_alert(entry['symbol'], 0, 0, 0, 'bot_surge', signal['fear_greed'])

        return await self.send_message(text)

    async def send_pattern_c_alert(self, positions_count: int) -> bool:
        """パターンC全面安警告"""
        text = (
            f"🚨🚨🚨 <b>パターンC（全面安）移行!</b>\n\n"
            f"オープンポジション {positions_count}件あり。\n"
            f"<b>全ポジション決済を強く推奨します。</b>"
        )
        return await self.send_message(text)

    # ========================================
    # 市場レポート（startup / daily / emergency）
    # ========================================

    def _build_market_premise(self, data: dict) -> str:
        """市場前提ヘッダー（全レポート共通）"""
        btc_price = data.get('btc_price', 0)
        btc_change = data.get('btc_change_24h', 0)
        fg = data.get('fear_greed', 50)
        btc_d = data.get('btc_dominance', 0)
        regime = data.get('regime', 'F')
        regime_action = data.get('regime_action', '')

        fg_label = self._fear_label(fg)

        return (
            f"■ 市場前提\n"
            f"  BTC ${btc_price:,.0f} ({btc_change:+.1f}%) | "
            f"F&amp;G {fg} ({fg_label}) | "
            f"BTC.D {btc_d:.1f}% | "
            f"Pattern {html.escape(regime)}"
        )

    def _fear_label(self, fg: int) -> str:
        if fg <= 10: return 'Extreme Fear'
        elif fg <= 25: return 'Fear'
        elif fg <= 45: return 'Fear域'
        elif fg <= 55: return 'Neutral'
        elif fg <= 75: return 'Greed'
        else: return 'Extreme Greed'

    # Bot status icons
    _STATUS_ICON = {
        'waiting': '⚪', 'near': '🟡', 'fired': '🔴',
        'active': '🟢', 'blocked': '⛔',
    }

    def _bot_status_line(self, name: str, status: str, distance: str = '') -> str:
        """Bot status 1行: icon + name + status + distance"""
        icon = self._STATUS_ICON.get(status, '⚪')
        label = {'waiting': '待機', 'near': '接近', 'fired': '発火',
                 'active': '稼働', 'blocked': 'ブロック'}.get(status, status)
        dist = f' ({html.escape(distance)})' if distance else ''
        return f'  {icon} {name}: {label}{dist}'

    def _build_bot_status_section(self, data: dict) -> str:
        """5段階Bot Status with distance-to-threshold"""
        fg = data.get('fear_greed', 50)
        btc_change = data.get('btc_change_24h', 0)
        lines = ['■ Bot Status']

        # Alpha: Fear<10 + BTC≤-1% + BTC.D≤-0.5%
        alpha_status = data.get('bot_alpha_status', 'waiting')
        alpha_last = data.get('bot_alpha_last')
        if alpha_status == 'fired':
            alpha_dist = '極限一撃モード発火中!'
        elif alpha_status == 'near':
            alpha_dist = f'Fear:{fg} → 閾値10まであと{fg - 10}'
        else:
            alpha_dist = f'Fear:{fg} → 閾値10まであと{fg - 10}' if fg <= 20 else f'Fear帯0-10外 (現在{fg})'
        line = self._bot_status_line('Alpha', alpha_status, alpha_dist)
        if alpha_last:
            line += f' 最終:{alpha_last.strftime("%m-%d %H:%M")}'
        lines.append(line)

        # Surge: Fear 25-45 + BTC≤0%
        surge_status = data.get('bot_surge_status', 'waiting')
        if surge_status == 'active':
            surge_dist = f'Fear:{fg}, BTC:{btc_change:+.1f}%'
        elif 25 <= fg <= 45:
            surge_dist = f'Fear:{fg} 範囲内, BTC:{btc_change:+.1f}%{"" if btc_change <= 0 else " (BTC>0で未発火)"}'
        elif fg < 25:
            surge_dist = f'Fear:{fg} → 下限25まであと{25 - fg}'
        else:
            surge_dist = f'Fear:{fg} → 上限45超過'
        lines.append(self._bot_status_line('Surge', surge_status, surge_dist))

        # MeanRevert: Fear 50-80 + MA20乖離>15%
        if 50 <= fg <= 80:
            mr_status = 'active'
            mr_dist = f'Fear:{fg} 範囲内'
        elif fg < 50:
            mr_status = 'waiting'
            mr_dist = f'Fear:{fg} → 下限50まであと{50 - fg}'
        else:
            mr_status = 'waiting'
            mr_dist = f'Fear:{fg} → 上限80超過'
        lines.append(self._bot_status_line('MeanRevert', mr_status, mr_dist))

        # WeakShort: Fear 50-75 + BTC≥+1%
        if 50 <= fg <= 75 and btc_change >= 1.0:
            ws_status = 'active'
            ws_dist = f'Fear:{fg}, BTC:{btc_change:+.1f}%'
        elif 50 <= fg <= 75:
            ws_status = 'near'
            ws_dist = f'Fear:{fg} 範囲内, BTC:{btc_change:+.1f}% (≥+1%で発火)'
        elif fg < 50:
            ws_status = 'waiting'
            ws_dist = f'Fear:{fg} → 下限50まであと{50 - fg}'
        else:
            ws_status = 'waiting'
            ws_dist = f'Fear:{fg} → 上限75超過'
        lines.append(self._bot_status_line('WeakShort', ws_status, ws_dist))

        # Sniper: Fear<30 + BTC≤-3%
        if fg < 30 and btc_change <= -3.0:
            sn_status = 'fired'
            sn_dist = f'Fear:{fg}, BTC:{btc_change:+.1f}%'
        elif fg < 30:
            sn_status = 'near'
            sn_dist = f'Fear:{fg} 範囲内, BTC:{btc_change:+.1f}% (≤-3%で発火)'
        else:
            sn_status = 'waiting'
            sn_dist = f'Fear:{fg} → 閾値30まであと{fg - 30}' if fg > 30 else f'Fear:{fg}'
        lines.append(self._bot_status_line('Sniper', sn_status, sn_dist))

        # Scalp: Always active
        lines.append(self._bot_status_line('Scalp', 'active', 'BB+RSI常時監視'))

        return '\n'.join(lines)

    def _score_breakdown(self, s) -> str:
        """スコア内訳を1行で生成"""
        parts = []
        t1d = getattr(s, 'tier1_details', {}) or {}
        t2d = getattr(s, 'tier2_details', {}) or {}

        # Tier1 加点
        for key, label in [('L02', '聖域'), ('L03', '出来高'), ('L09', '変動'),
                           ('L17', '低相関'), ('L_alpha', 'α乖離')]:
            sc = t1d.get(key, {}).get('score', 0)
            if sc > 0:
                parts.append(f'{label}+{sc:.0f}')
            elif sc < 0 and sc != -100:
                parts.append(f'{label}{sc:.0f}')

        # Tier2 加減点
        l08_sc = t2d.get('L08', {}).get('score', 0)
        if l08_sc > 0:
            parts.append(f'FR+{l08_sc:.0f}')
        elif l08_sc < 0:
            parts.append(f'FR{l08_sc:.0f}')
        l10_sc = t2d.get('L10', {}).get('score', 0)
        if l10_sc > 0:
            parts.append(f'板厚+{l10_sc:.0f}')
        l13_sc = t2d.get('L13', {}).get('score', 0)
        if l13_sc != 0:
            parts.append(f'清算{l13_sc:+.0f}')

        return ', '.join(parts) if parts else ''

    def _matching_bots(self, s, fg: int) -> str:
        """銘柄に該当するBot候補を表示"""
        bots = []
        corr = getattr(s, 'btc_correlation', 1.0)
        alpha = getattr(s, 'btc_alpha', 0)
        if fg < 10 and corr < 0.5 and alpha >= 3.0:
            bots.append('◎Alpha')
        if 25 <= fg <= 45:
            bots.append('◎Surge')
        if 50 <= fg <= 80:
            bots.append('○MeanRevert')
        if 50 <= fg <= 75:
            bots.append('○WeakShort')
        if fg < 30 and corr < 0.3:
            bots.append('○Sniper')
        return ' '.join(bots) if bots else ''

    def _build_tier2_section(self, data: dict) -> str:
        """Tier2通過上位（T1/T2スコア分離 + 内訳 + Bot候補）"""
        t2_list = data.get('tier2_passed', [])
        t2_top = data.get('tier2_top', [])
        new_listings = data.get('new_listings', set())
        fg = data.get('fear_greed', 50)

        tier2_lines = []
        for i, s in enumerate(t2_top[:20], 1):
            sym_short = s.symbol.replace('/USDT:USDT', '')
            sector = html.escape(s.sector or 'N/A')
            total = s.tier1_score + s.tier2_score
            new_tag = ' [NEW]' if s.symbol in new_listings else ''

            # Main line
            line = (f"  {i}. {html.escape(sym_short)}{new_tag} [{sector}] "
                    f"{total:.0f}pt (T1:{s.tier1_score:.0f}+T2:{s.tier2_score:.0f})")

            # Score breakdown (top 10 only to save space)
            if i <= 10:
                breakdown = self._score_breakdown(s)
                if breakdown:
                    line += f'\n     {html.escape(breakdown)}'
                bots = self._matching_bots(s, fg)
                if bots:
                    line += f' | {bots}'

            tier2_lines.append(line)

        tier2_text = '\n'.join(tier2_lines) if tier2_lines else '  なし'
        return (
            f"■ Tier2通過 上位{min(20, len(t2_top))} (全{len(t2_list)}銘柄)\n"
            f"{tier2_text}"
        )

    async def send_market_report(self, report_type: str, data: dict) -> bool:
        """
        市場レポート送信 - 5セクション新フォーマット
        1. 結論  2. 市場前提  3. 候補・除外  4. Bot Status  5. どらの解説
        report_type: "startup" | "daily" | "emergency"
        """
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

        # ヘッダー
        headers = {
            'startup': f"🚀 <b>起動レポート {now_str}</b>",
            'daily': f"📊 <b>デイリーレポート {now_str}</b>",
            'emergency': f"⚡ <b>緊急レポート {now_str}</b>",
        }
        header = headers.get(report_type, f"📋 <b>レポート {now_str}</b>")

        fg = data.get('fear_greed', 50)
        regime = data.get('regime', 'F')
        btc_change = data.get('btc_change_24h', 0)

        # § 1. 結論
        conclusion = Commentary._build_conclusion(regime, fg, len(data.get('tier1_passed', [])))
        section1 = f"■ 結論\n  {html.escape(conclusion)}"

        # § 2. 市場前提
        section2 = self._build_market_premise(data)

        # § 3. Tier1/Tier2 候補・除外
        t1_list = data.get('tier1_passed', [])
        sector_breakdown = data.get('tier1_sector_breakdown', {})
        sector_str = ', '.join([f"{k}:{v}" for k, v in sorted(sector_breakdown.items(), key=lambda x: -x[1])[:8]])
        tier1_info = f"■ Tier1通過 ({len(t1_list)}銘柄)\n  セクター: {sector_str or 'N/A'}"
        tier2_info = self._build_tier2_section(data)
        section3 = f"{tier1_info}\n\n{tier2_info}"

        # § 4. Bot Status
        section4 = self._build_bot_status_section(data)

        # § 5. どらの解説
        commentary_text = Commentary.build_report_commentary(data)
        section5 = f"■ どらの解説\n{html.escape(commentary_text)}"

        # ポジション
        positions = data.get('positions', [])
        if positions:
            pos_lines = []
            for p in positions:
                sym_short = p.get('symbol', '').replace('/USDT:USDT', '')
                pnl = p.get('unrealized_pnl_pct', 0) or 0
                pos_lines.append(f"  {html.escape(sym_short)}: {pnl:+.1f}%")
            pos_text = '\n'.join(pos_lines)
        else:
            pos_text = '  なし'
        position_section = f"■ ポジション ({len(positions)}件)\n{pos_text}"

        # 組み立て
        text = '\n\n'.join([header, section1, section2, section3, section4, position_section, section5])

        # emergency: トリガー詳細＋アクション指示
        if report_type == 'emergency':
            triggers = data.get('triggers', [])
            trigger_lines = []
            for t in triggers:
                action = Commentary.trigger_comment(t)
                trigger_lines.append(f"  ・{html.escape(t)}\n    → {html.escape(action)}")
            trigger_text = '\n'.join(trigger_lines)
            text += f"\n\n■ トリガー詳細\n{trigger_text}"

        # フィードバック（daily/startup）
        if report_type in ('daily', 'startup'):
            fb = data.get('feedback_stats', {})
            if fb:
                text += (
                    f"\n\n■ アラート精度\n"
                    f"  1h後PnL: {fb.get('avg_1h', 0):+.2f}%\n"
                    f"  24h後PnL: {fb.get('avg_24h', 0):+.2f}%\n"
                    f"  勝率(24h): {fb.get('win_rate_24h', 0):.0f}%"
                )

        # スコアガイドフッター
        text += f"\n\n{html.escape(Commentary.score_guide_footer())}"

        return await self.send_message(text)

    async def send_community_report(self, data: dict) -> bool:
        """コミュニティ向け簡易レポート（Bot詳細・ポジション除外）"""
        if not self.community_chat_id:
            return False

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        fg = data.get('fear_greed', 50)
        regime = data.get('regime', 'F')

        header = f"📊 <b>Empire Monitor コミュニティレポート {now_str}</b>"

        # 市場前提
        premise = self._build_market_premise(data)

        # 結論
        conclusion = Commentary._build_conclusion(regime, fg, len(data.get('tier1_passed', [])))

        # Tier2上位10（スコア内訳なし、簡易版）
        t2_top = data.get('tier2_top', [])
        t2_lines = []
        for i, s in enumerate(t2_top[:10], 1):
            sym_short = s.symbol.replace('/USDT:USDT', '')
            score = s.tier1_score + s.tier2_score
            t2_lines.append(f"  {i}. {html.escape(sym_short)} Score:{score:.0f}")
        t2_text = '\n'.join(t2_lines) if t2_lines else '  なし'
        tier2_section = f"■ 注目銘柄 Top10\n{t2_text}"

        # 解説（Fear部分のみ）
        fear_note = Commentary._fear_comment(fg)

        text = '\n\n'.join([
            header,
            f"■ 結論\n  {html.escape(conclusion)}",
            premise,
            tier2_section,
            html.escape(fear_note),
            html.escape(Commentary.score_guide_footer()),
        ])

        try:
            if len(text) > 4000:
                text = text[:4000] + "\n...(truncated)"
            await self.bot.send_message(
                chat_id=self.community_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
            return True
        except Exception as e:
            print(f"[Telegram Community Error] {e}")
            return False

    # ========================================
    # ポジション関連（即時送信）
    # ========================================

    async def send_position_alert(self, symbol: str, pnl_pct: float, alert_type: str) -> bool:
        if alert_type == 'dd_warning':
            text = f"⚠️ <b>DD警告: {html.escape(symbol)}</b>\n含み損: {pnl_pct:.1f}%\nSL確認してください"
        elif alert_type == 'tp_near':
            text = f"🎯 <b>利確接近: {html.escape(symbol)}</b>\n含み益: {pnl_pct:+.1f}%"
        elif alert_type == 'sl_hit':
            text = f"🔴 <b>SL到達: {html.escape(symbol)}</b>\n損失: {pnl_pct:.1f}%"
        else:
            text = f"📢 <b>ポジション通知: {html.escape(symbol)}</b>\nPnL: {pnl_pct:+.1f}%"
        return await self.send_message(text)

    # ========================================
    # ペーパートレード通知
    # ========================================

    async def send_paper_signal(self, bot_type: str, entry: dict, trade_serial: str = '') -> bool:
        """ペーパートレードシグナル通知"""
        symbol = html.escape(entry.get('symbol', 'N/A'))
        side = entry.get('side', 'long').upper()
        leverage = entry.get('leverage', 3)
        tp = entry.get('take_profit_pct', 8.0)
        sl = entry.get('stop_loss_pct', 3.0)
        price = entry.get('entry_price', entry.get('price', 0))
        serial_tag = f"<code>{trade_serial}</code> " if trade_serial else ""

        text = (
            f"🧪 <b>[PAPER] {serial_tag}{get_display_name(bot_type)} シグナル</b>\n"
            f"  銘柄: {symbol}\n"
            f"  方向: {side} {leverage}x\n"
            f"  価格: ${price:,.6f}\n"
            f"  TP: +{tp}% / SL: -{sl}%\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(text)

    async def send_paper_exit(self, signal: dict, trade_serial: str = '') -> bool:
        """ペーパートレード決済通知"""
        symbol = html.escape(signal.get('symbol', 'N/A'))
        bot = signal.get('bot_type', '')
        reason = signal.get('exit_reason', '')
        pnl = signal.get('realized_pnl_pct', 0)
        emoji = "✅" if pnl > 0 else "❌"
        serial_tag = f"<code>{trade_serial}</code> " if trade_serial else ""

        text = (
            f"{emoji} <b>[PAPER] {serial_tag}{get_display_name(bot)} 決済</b>\n"
            f"  銘柄: {symbol}\n"
            f"  理由: {reason}\n"
            f"  PnL: {pnl:+.2f}%\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(text)

    async def send_levburn_alert(self, signal: dict, price: float = 0) -> bool:
        """レバ焼きシグナル通知"""
        symbol = html.escape(signal.get('symbol', 'N/A'))
        direction = signal.get('direction', 'LONG')
        score = signal.get('burn_score', 0)
        risk = signal.get('risk_level', 'MEDIUM')
        fr = signal.get('funding_rate', 0)
        oi = signal.get('oi_usd', 0)
        oi_chg = signal.get('oi_change_24h', 0)
        ratio = signal.get('futures_spot_ratio', 0)
        reasons = signal.get('reasons', [])
        tp = signal.get('tp_pct', 5.0)
        sl = signal.get('sl_pct', 2.5)
        lev = signal.get('leverage', 5)
        pos_pct = signal.get('position_pct', 3)
        max_hold = signal.get('max_hold_hours', 48)

        dir_emoji = '📈' if direction == 'LONG' else '📉'
        fr_state = 'ロング過熱' if fr > 0 else 'ショート過熱'
        spec_level = '高' if ratio >= 20 else ('中' if ratio >= 5 else '低')

        reasons_text = '\n'.join([f"  • {r}" for r in reasons])

        text = (
            f"🔥 <b>レバ焼きシグナル: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"{dir_emoji} 方向: {direction}\n"
            f"📊 焼きスコア: {score}/100 ({risk})\n"
            f"💰 現在価格: ${price:,.6f}\n\n"
            f"📈 FR/OI分析:\n"
            f"  • Funding Rate: {fr:+.4f} ({fr_state})\n"
            f"  • Open Interest: ${oi / 1e6:.1f}M ({oi_chg:+.1f}%)\n"
            f"  • 先物/現物比率: {ratio:.1f}x\n"
            f"  • 投機度: {spec_level}\n\n"
            f"🔍 検知根拠:\n{reasons_text}\n\n"
            f"🎯 トレードプラン:\n"
            f"  • TP: +{tp}% / SL: -{sl}%\n"
            f"  • レバレッジ: {lev}x\n"
            f"  • ポジションサイズ: 資金の{pos_pct}%\n"
            f"  • 最大保有: {max_hold}h\n\n"
            f"⚠️ レバ焼きはハイリスク。ポジサイズ厳守\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(text)

    async def send_levburn_sec_alert(self, signal) -> bool:
        """LevBurn-Sec 1秒足スキャルピングシグナル通知"""
        symbol = html.escape(signal.symbol.replace('/USDT:USDT', ''))
        dir_emoji = '📈' if signal.direction == 'LONG' else '📉'
        reasons_text = ', '.join(signal.reasons) if signal.reasons else 'N/A'

        text = (
            f"⚡ <b>LevBurn-Sec: {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"{dir_emoji} 方向: {signal.direction}\n"
            f"💰 価格: ${signal.entry_price:,.6f}\n"
            f"📊 スコア: {signal.combined_score}/100 "
            f"(FR:{signal.burn_score} + RT:{signal.trigger_score})\n\n"
            f"📈 FR: {signal.fr_value:+.4f}\n"
            f"⚡ 1s変動: {signal.price_change_1s:+.2f}%\n"
            f"⚡ 5s変動: {signal.price_change_5s:+.2f}%\n"
            f"🔍 トリガー: {html.escape(reasons_text)}\n\n"
            f"🎯 TP: +{signal.tp_pct}% (${signal.tp_price:,.6f})\n"
            f"🛑 SL: -{signal.sl_pct}% (${signal.sl_price:,.6f})\n"
            f"📐 Lev: {signal.leverage}x | Size: {signal.position_pct}%\n"
            f"⏱️ 最大保有: {signal.max_hold_seconds}秒\n"
            f"🏷️ Variant: {signal.variant}\n\n"
            f"⚠️ 超短期スキャルピング。即時判断必須\n"
            f"⏰ {signal.timestamp}"
        )
        return await self.send_message(text)

    # ========================================
    # ライブ注文実行通知
    # ========================================

    async def send_live_entry(self, bot_name: str, signal: dict, fill_result: dict) -> bool:
        """ライブエントリー約定通知"""
        symbol = html.escape(signal.get('symbol', 'N/A'))
        side = signal.get('side', 'long').upper()
        leverage = signal.get('leverage', 3)
        fill_price = fill_result.get('entry_order', {}).get('average', 0)
        tp = signal.get('take_profit_pct', 0)
        sl = signal.get('stop_loss_pct', 0)
        tp_ok = '✅' if fill_result.get('tp_order') else '❌'
        sl_ok = '✅' if fill_result.get('sl_order') else '❌'

        text = (
            f"💰 <b>[LIVE] {get_display_name(bot_name)} エントリー約定</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"  銘柄: {symbol}\n"
            f"  方向: {side} {leverage}x\n"
            f"  約定価格: ${fill_price:,.6f}\n"
            f"  TP: +{tp}% {tp_ok} / SL: -{sl}% {sl_ok}\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(text)

    async def send_live_exit(self, bot_name: str, symbol: str, reason: str,
                              pnl: float, exit_price: float = 0) -> bool:
        """ライブ決済通知"""
        emoji = "✅" if pnl > 0 else "❌"
        sym = html.escape(symbol)
        text = (
            f"{emoji} <b>[LIVE] {get_display_name(bot_name)} 決済</b>\n"
            f"  銘柄: {sym}\n"
            f"  理由: {html.escape(reason)}\n"
            f"  決済価格: ${exit_price:,.6f}\n"
            f"  PnL: {pnl:+.2f}%\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(text)

    async def send_live_error(self, bot_name: str, symbol: str, error: str) -> bool:
        """ライブ実行エラー通知（緊急）"""
        sym = html.escape(symbol)
        text = (
            f"🚨 <b>[LIVE ERROR] {get_display_name(bot_name)}</b>\n"
            f"  銘柄: {sym}\n"
            f"  エラー: {html.escape(str(error)[:300])}\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"⚠️ 手動確認が必要です"
        )
        return await self.send_message(text)

    async def send_circuit_breaker(self, reason: str, daily_pnl: float) -> bool:
        """サーキットブレーカー発動通知"""
        text = (
            f"🛑 <b>サーキットブレーカー発動</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"  理由: {html.escape(reason)}\n"
            f"  日次PnL: {daily_pnl:+.2f}%\n"
            f"  ⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"全Bot新規エントリーを停止しました。"
        )
        return await self.send_message(text)

    # ========================================
    # ユーティリティ
    # ========================================

    async def send_error(self, error_msg: str) -> bool:
        text = f"⚠️ <b>Empire Monitor エラー</b>\n\n{html.escape(error_msg[:500])}"
        return await self.send_message(text)

    # ========================================
    # レガシー互換（エンジン内部から呼ばれる既存メソッド）
    # Tier2アラートはログのみ記録し、リアルタイム送信しない
    # ========================================

    async def send_tier2_alert(self, state: SymbolState, tier1_results: dict, tier2_results: dict, regime: str, regime_action: str, fear_greed: int) -> bool:
        """Tier2通過 - ログ記録のみ（リアルタイム送信廃止）"""
        if self.db:
            self.db.log_alert(state.symbol, state.last_price, state.tier1_score, state.tier2_score, regime, fear_greed)
        # リアルタイム送信しない（レポートにまとめる）
        return True

    async def send_regime_update(self, pattern: str, action: str, btc_change: float, dom_change: float, total_change: float, fear_greed: int) -> bool:
        """レジーム更新 - ログのみ（レポートにまとめる）"""
        # パターンCへの遷移は send_pattern_c_alert で別途処理
        return True

    async def send_startup(self, symbol_count: int, regime: str, fear_greed: int, db_stats: dict = None) -> bool:
        """レガシー起動通知 - report_schedulerの on_startup で置換"""
        return True

    async def send_daily_summary(self, date: str, total_alerts: int, t1: int, t2: int, regime: str, fg: int, top_symbols: list, feedback_stats: dict = None) -> bool:
        """レガシーデイリーサマリー - report_schedulerの check_daily で置換"""
        return True

    # ========================================
    # 激アツ通知
    # ========================================

    async def send_hot_signal_alert(self, signal) -> bool:
        """激アツシグナル通知"""
        s = signal
        direction = '📈 LONG' if s.direction == 'long' else '📉 SHORT'
        sym_short = html.escape(s.symbol.replace('/USDT:USDT', ''))

        # 時間足テーブル
        def _tf_row(tf_name, tf_key):
            a = s.tf_analysis.get(tf_key, {})
            rsi_val = f"{a.get('rsi', '-')}"
            bb_val = a.get('bb_pos', '-')
            ema_val = a.get('ema_cross', '-')
            vol_val = f"{a.get('vol_ratio', '-')}x" if isinstance(a.get('vol_ratio'), (int, float)) else '-'
            return f"│ {tf_name:3s} │ {rsi_val:6s} │ {bb_val:6s} │ {ema_val:6s} │ {vol_val:5s} │"

        tf_table = (
            "┌─────┬────────┬────────┬────────┬───────┐\n"
            "│ 足  │ RSI    │ BB     │ EMA    │ Vol   │\n"
            "├─────┼────────┼────────┼────────┼───────┤\n"
            f"{_tf_row('1h', '1h')}\n"
            f"{_tf_row('4h', '4h')}\n"
            f"{_tf_row('1d', '1d')}\n"
            "└─────┴────────┴────────┴────────┴───────┘"
        )

        # TP% / SL%
        def _pct(target, base):
            if base <= 0:
                return 0
            return (target - base) / base * 100

        entry_mid = (s.entry_low + s.entry_high) / 2
        tp1_pct = abs(_pct(s.tp1, entry_mid))
        tp2_pct = abs(_pct(s.tp2, entry_mid))
        tp3_pct = abs(_pct(s.tp3, entry_mid))
        sl_pct = abs(_pct(s.sl, entry_mid))

        reasoning_text = '\n'.join([f"• {html.escape(r)}" for r in s.reasoning])
        rr_warning = " ⚠️RR不足" if s.rr_warning else ""

        level_emoji = '🔥🔥🔥' if s.hot_score >= 80 else '🔥'
        header = f"{level_emoji} <b>{'激アツ' if s.hot_score >= 80 else 'アツい'}シグナル: {sym_short}</b>"

        text = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 現在価格: ${s.price:,.6f}\n"
            f"📍 エントリーゾーン: ${s.entry_low:,.6f} 〜 ${s.entry_high:,.6f}\n"
            f"📊 方向: {direction}\n"
            f"🎯 激アツ度: {s.hot_score}/100\n\n"
            f"📊 時間足分析:\n<pre>{tf_table}</pre>\n\n"
            f"📈 エントリー根拠:\n{reasoning_text}\n\n"
            f"🎯 利確プラン:\n"
            f"• TP1: ${s.tp1:,.6f} ({tp1_pct:.1f}%) → 40%決済\n"
            f"• TP2: ${s.tp2:,.6f} ({tp2_pct:.1f}%) → 30%決済\n"
            f"• TP3: ${s.tp3:,.6f} ({tp3_pct:.1f}%) → 残り30%決済\n"
            f"※TP1到達後、SLを建値に移動\n\n"
            f"🛑 損切り:\n"
            f"• SL: ${s.sl:,.6f} ({sl_pct:.1f}%)\n"
            f"• RR比: {s.rr_ratio:.2f}{rr_warning}\n\n"
            f"⏰ {s.timestamp}\n"
            f"🏷️ セクター: {html.escape(s.sector)} | Tier2スコア: {s.tier2_score:.0f}"
        )

        if self.db:
            self.db.log_alert(s.symbol, s.price, s.tier2_score, 0, 'hot_signal', 0)

        return await self.send_message(text)

    async def send_watchlist_report(self, data: dict) -> bool:
        """監視銘柄定期レポート"""
        signals = data.get('signals', [])
        btc_price = data.get('btc_price', 0)
        btc_chg = data.get('btc_change', 0)
        fear = data.get('fear_greed', 50)
        pattern = data.get('regime', 'F')
        interval = data.get('interval', '1h')

        header = f"📋 <b>監視銘柄レポート ({html.escape(interval)}更新)</b>"
        market = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 市場: BTC ${btc_price:,.0f} ({btc_chg:+.1f}%) | "
            f"Fear {fear} | Pattern {html.escape(pattern)}\n"
            f"監視中: {len(signals)}銘柄"
        )

        # 注目銘柄 Top5
        hot = [s for s in signals if s.hot_score >= 60]
        hot_lines = []
        for s in hot[:5]:
            sym = html.escape(s.symbol.replace('/USDT:USDT', ''))
            arrow = '📈' if s.direction == 'long' else '📉'
            hot_lines.append(
                f"  {arrow} {sym}: {s.hot_score}点 | ${s.price:,.4f} | {html.escape(s.sector)}"
            )
        hot_text = '\n'.join(hot_lines) if hot_lines else '  なし'

        # 様子見
        watch = [s for s in signals if 40 <= s.hot_score < 60]
        watch_lines = []
        for s in watch[:10]:
            sym = html.escape(s.symbol.replace('/USDT:USDT', ''))
            watch_lines.append(f"  {sym}: {s.hot_score}点")
        watch_text = '\n'.join(watch_lines) if watch_lines else '  なし'

        next_update = (datetime.now() + timedelta(hours=1)).strftime('%H:%M')

        text = (
            f"{header}\n{market}\n\n"
            f"🔥 注目銘柄:\n{hot_text}\n\n"
            f"👀 様子見:\n{watch_text}\n\n"
            f"次回更新: {next_update}"
        )

        return await self.send_message(text)
