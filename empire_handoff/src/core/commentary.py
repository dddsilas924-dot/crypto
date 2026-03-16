"""テンプレートベース日本語コメンタリー生成（AI不使用）"""
from typing import Dict, List, Optional


class Commentary:
    """条件分岐によるテンプレートベースのコメンタリー生成

    Iron Rule: AIはTier3コメンタリーのみ。
    このクラスはテンプレート文字列の組み立てのみを行い、
    価格判定・計算には一切関与しない。
    """

    # ============================
    # Regime コメンタリー
    # ============================

    REGIME_TEMPLATES = {
        'A': '📈 BTC独走相場。BTC上昇・ドミナンス上昇・時価総額上昇。アルトは出遅れやすく、BTC以外は静観推奨。',
        'B': '🎉 アルト祭り突入。BTC上昇中にドミナンス低下＝資金がアルトに流れている。Tier2上位を積極的に狙う。',
        'C': '🚨 全面安パターン。BTC下落・ドミナンス上昇＝アルトからBTCへ資金退避。全ポジション決済を推奨。',
        'D': '🔍 本質Alpha探し。BTC下落だがドミナンスも低下＝一部アルトが独自に動いている。低相関・高アルファ銘柄を狙う。',
        'E': '😴 じわ下げ相場。BTCレンジだがドミナンス上昇＝アルトが静かに売られている。静観推奨。',
        'F': '🔄 アルト循環相場。BTCレンジ・ドミナンス低下＝セクター間で資金ローテーション。短期狙いの回転売買向き。',
    }

    REGIME_ACTIONS = {
        'A': '静観。BTC現物保有者以外は手を出さない。',
        'B': '全力買い。Tier2上位銘柄をロング。',
        'C': '全切り。既存ポジション即時決済。新規エントリー禁止。',
        'D': '先行買い。低相関＋高αのみ厳選ロング。',
        'E': '静観。下落余地あるため新規不可。',
        'F': '短期狙い。セクター循環を利用した回転売買。',
    }

    @classmethod
    def regime_comment(cls, pattern: str, fear_greed: int, btc_change_24h: float) -> str:
        """パターン＋Fear＋BTC変動からコメンタリー生成"""
        base = cls.REGIME_TEMPLATES.get(pattern, '判定不能。データ確認中。')
        action = cls.REGIME_ACTIONS.get(pattern, '')

        # Fear帯による追加コメント
        fear_note = cls._fear_comment(fear_greed)

        # BTC方向の補足
        if btc_change_24h <= -3.0:
            btc_note = f'BTC急落中({btc_change_24h:+.1f}%)。追撃ショートは禁物、反発に備える。'
        elif btc_change_24h <= -1.0:
            btc_note = f'BTC軟調({btc_change_24h:+.1f}%)。慎重に。'
        elif btc_change_24h >= 3.0:
            btc_note = f'BTC急騰中({btc_change_24h:+.1f}%)。追撃ロングは高値掴みリスク。'
        elif btc_change_24h >= 1.0:
            btc_note = f'BTC堅調({btc_change_24h:+.1f}%)。'
        else:
            btc_note = ''

        parts = [base, f'→ {action}' if action else '']
        if fear_note:
            parts.append(fear_note)
        if btc_note:
            parts.append(btc_note)

        return '\n'.join(p for p in parts if p)

    @classmethod
    def _fear_comment(cls, fg: int) -> str:
        """Fear&Greed値からコメント生成"""
        if fg <= 10:
            return f'😱 極限恐怖(F&G={fg})。Bot-Alpha発火圏内。歴史的買い場の可能性。'
        elif fg <= 25:
            return f'😰 恐怖域(F&G={fg})。Bot-Sniper待機中。逆張りロングの好機だが慎重に。'
        elif fg <= 45:
            return f'😟 Fear域(F&G={fg})。Bot-Surge稼働条件。押し目買い候補を探す。'
        elif fg <= 55:
            return f'😐 中立(F&G={fg})。方向感なし。エントリーは明確なシグナル待ち。'
        elif fg <= 75:
            return f'😊 Greed域(F&G={fg})。Bot-WeakShort/MeanRevert稼働条件。過熱銘柄のショート機会。'
        else:
            return f'🤑 極限貪欲(F&G={fg})。天井圏の警戒。新規ロング禁止、利確優先。'

    # ============================
    # Bot ステータス コメンタリー
    # ============================

    BOT_STATUS_TEMPLATES = {
        'alpha': {
            'waiting': 'Bot-Alpha: 待機中。Fear<10の極限恐怖を待つ。',
            'near': 'Bot-Alpha: ⚠️ 発火圏接近中(Fear<15)。条件到達で即座に発火。',
            'fired': 'Bot-Alpha: 🔴 発火中！極限一撃モード。低相関・高αの厳選銘柄にLong 3x。',
            'blocked': 'Bot-Alpha: ブロック中。冷却期間または手動停止。',
        },
        'surge': {
            'waiting': 'Bot-Surge: 待機中。Fear 25-45 + BTC≤0%を待つ。',
            'active': 'Bot-Surge: 🟡 稼働中。BTC乖離銘柄＋セクター波及を監視。',
            'blocked': 'Bot-Surge: ブロック中。冷却期間または手動停止。',
        },
        'meanrevert': {
            'waiting': 'Bot-MeanRevert: 待機中。Fear 50-80 + MA20乖離>15%を待つ。',
            'active': 'Bot-MeanRevert: 稼働中。過熱銘柄の平均回帰ショート。',
        },
        'weakshort': {
            'waiting': 'Bot-WeakShort: 待機中。Fear 50-75 + BTC≥+1%を待つ。',
            'active': 'Bot-WeakShort: 稼働中。BTC上昇についていけない弱小銘柄をショート。',
        },
        'sniper': {
            'waiting': 'Bot-Sniper: 待機中。Fear<30 + BTC≤-3% + Vol≥5x + Corr<0.3の全条件を待つ。',
            'fired': 'Bot-Sniper: 🎯 発火！超低相関・超高ボリューム銘柄にLong 10x。',
        },
        'scalp': {
            'waiting': 'Bot-Scalp: 常時稼働。BB(20,2σ)+RSI(14)でL/S 10x。',
            'active': 'Bot-Scalp: 🔄 ポジション保有中。',
        },
    }

    @classmethod
    def bot_status_comment(cls, bot_name: str, status: str) -> str:
        """Bot名＋ステータスからコメンタリー生成"""
        templates = cls.BOT_STATUS_TEMPLATES.get(bot_name, {})
        return templates.get(status, f'{bot_name}: 状態不明({status})')

    # ============================
    # Tier1/Tier2 通過コメンタリー
    # ============================

    @classmethod
    def tier1_summary(cls, passed_count: int, total_scanned: int,
                      sector_breakdown: Dict[str, int]) -> str:
        """Tier1通過サマリー"""
        rate = (passed_count / total_scanned * 100) if total_scanned > 0 else 0

        if rate > 30:
            tone = '市場全体が活発。銘柄選別が重要。'
        elif rate > 15:
            tone = '通常レベルの通過率。'
        elif rate > 5:
            tone = '通過率低め。市場は低調。'
        else:
            tone = '通過率極端に低い。市場凍結状態。エントリー見送り推奨。'

        # 上位セクター
        top_sectors = sorted(sector_breakdown.items(), key=lambda x: -x[1])[:3]
        if top_sectors:
            sector_text = '、'.join([f'{k}({v}銘柄)' for k, v in top_sectors])
            sector_note = f'主要セクター: {sector_text}'
        else:
            sector_note = ''

        lines = [
            f'Tier1通過: {passed_count}/{total_scanned}銘柄 ({rate:.1f}%)',
            tone,
        ]
        if sector_note:
            lines.append(sector_note)

        return '\n'.join(lines)

    @classmethod
    def tier2_symbol_comment(cls, symbol: str, tier1_score: float, tier2_score: float,
                             tier1_details: Dict, tier2_details: Dict,
                             is_new_listing: bool = False) -> str:
        """個別銘柄のTier2通過コメント（スコア内訳付き）"""
        total = tier1_score + tier2_score
        sym_short = symbol.replace('/USDT:USDT', '')

        parts = [f'{sym_short}: 合計{total:.0f}pt (T1:{tier1_score:.0f} + T2:{tier2_score:.0f})']

        # Tier1 内訳
        t1_parts = []
        l02 = tier1_details.get('L02', {})
        if l02.get('score', 0) > 0:
            t1_parts.append(f"聖域{l02['score']:.0f}")
        l03 = tier1_details.get('L03', {})
        if l03.get('score', 0) > 0:
            t1_parts.append(f"出来高{l03['score']:.0f}")
        l09 = tier1_details.get('L09', {})
        if l09.get('score', 0) > 0:
            t1_parts.append(f"価格変動{l09['score']:.0f}")
        l17 = tier1_details.get('L17', {})
        if l17.get('score', 0) > 0:
            t1_parts.append(f"低相関{l17['score']:.0f}")
        l_alpha = tier1_details.get('L_alpha', {})
        if l_alpha.get('score', 0) > 0:
            t1_parts.append(f"α乖離{l_alpha['score']:.0f}")
        if t1_parts:
            parts.append(f"  T1内訳: {' / '.join(t1_parts)}")

        # Tier2 内訳
        t2_parts = []
        l08 = tier2_details.get('L08', {})
        if l08.get('score', 0) != 0:
            fr_label = 'ショートスクイーズ圧' if l08['score'] > 0 else '過熱'
            t2_parts.append(f"FR:{fr_label}({l08['score']:+.0f})")
        l10 = tier2_details.get('L10', {})
        if l10.get('score', 0) > 0:
            t2_parts.append(f"流動性{l10['score']:.0f}")
        l13 = tier2_details.get('L13', {})
        if l13.get('score', 0) != 0:
            t2_parts.append(f"清算リスク({l13['score']:+.0f})")
        if t2_parts:
            parts.append(f"  T2内訳: {' / '.join(t2_parts)}")

        if is_new_listing:
            parts.append('  🆕 新規上場銘柄')

        return '\n'.join(parts)

    # ============================
    # トリガー アクション コメンタリー
    # ============================

    # トリガー分析テンプレート: {意味, 執行方針, 監視強化Bot, 回避Bot}
    TRIGGER_ANALYSIS = {
        'btc_1h': {
            'meaning': 'フラッシュクラッシュ/急騰',
            'action': '新規エントリー見送り。既存ポジションSL確認。',
            'watch': 'Alpha, Sniper',
            'avoid': 'Scalp',
        },
        'btc_4h': {
            'meaning': 'トレンド転換の可能性',
            'action': '全ポジションSL見直し。ポジション縮小検討。',
            'watch': 'Alpha, Sniper',
            'avoid': 'Surge, Scalp',
        },
        'fear_change': {
            'meaning': '市場心理の急転',
            'action': 'Bot発火条件の変化を確認。',
            'watch': 'Alpha (Fear急落時), MeanRevert (Fear急騰時)',
            'avoid': 'なし',
        },
        'btc_d_change': {
            'meaning': '資金フロー急変（BTC⇔アルト）',
            'action': 'アルトポジション方向を再確認。',
            'watch': 'WeakShort (D上昇時)',
            'avoid': 'Surge (D上昇時)',
        },
        'oi_change': {
            'meaning': 'レバレッジ清算連鎖リスク',
            'action': 'ポジションサイズ縮小。高レバBot一時停止検討。',
            'watch': 'なし',
            'avoid': 'Scalp, Sniper (高レバ)',
        },
    }

    @classmethod
    def trigger_comment(cls, trigger_type: str, value: str = '') -> str:
        """緊急トリガー種別からアクション指示を生成"""
        if 'BTC 1h' in trigger_type:
            key = 'btc_1h'
        elif 'BTC 4h' in trigger_type:
            key = 'btc_4h'
        elif 'Fear' in trigger_type:
            key = 'fear_change'
        elif 'BTC.D' in trigger_type:
            key = 'btc_d_change'
        elif 'OI' in trigger_type:
            key = 'oi_change'
        else:
            return f'⚡ トリガー発火: {trigger_type}。状況確認してください。'

        t = cls.TRIGGER_ANALYSIS[key]
        return f"市場意味: {t['meaning']} / 執行: {t['action']} / 監視: {t['watch']} / 回避: {t['avoid']}"

    # ============================
    # スコアガイド
    # ============================

    @classmethod
    def score_guide_footer(cls) -> str:
        """レポート末尾に付けるスコア読み方ガイド"""
        return (
            '━━ スコアガイド ━━\n'
            '90+: 即監視 | 80+: 強候補 | 70+: 条件付き | 60-: 見送り\n'
            'T1(max130): 聖域30+出来高25+変動20+低相関25+α乖離30\n'
            'T2(max45): FR20+流動性20+清算リスク5\n'
            '合計175pt満点 / T2通過>=10pt / VETO=-100で即除外\n'
            '━━━━━━━━━━━━━'
        )

    # ============================
    # レポート全体のコメンタリー組み立て
    # ============================

    @classmethod
    def build_report_commentary(cls, report_data: dict) -> str:
        """レポートデータから「どらの解説」セクションを生成"""
        pattern = report_data.get('regime', 'F')
        fear = report_data.get('fear_greed', 50)
        btc_change = report_data.get('btc_change_24h', 0)
        t1_count = len(report_data.get('tier1_passed', []))
        t2_count = len(report_data.get('tier2_passed', []))

        lines = []

        # 結論（1行）
        conclusion = cls._build_conclusion(pattern, fear, t1_count)
        lines.append(f'【結論】{conclusion}')
        lines.append('')

        # パターン解説
        lines.append(cls.regime_comment(pattern, fear, btc_change))
        lines.append('')

        # 市場温度
        if t1_count > 200:
            lines.append(f'市場温度: 🔥 高活性({t1_count}銘柄Tier1通過)。チャンス多いが選別重要。')
        elif t1_count > 100:
            lines.append(f'市場温度: 🌤 通常({t1_count}銘柄Tier1通過)。')
        elif t1_count > 50:
            lines.append(f'市場温度: 🌥 低調({t1_count}銘柄Tier1通過)。良銘柄は限定的。')
        else:
            lines.append(f'市場温度: ❄️ 凍結({t1_count}銘柄Tier1通過)。エントリー見送り推奨。')

        # トリガー解説（emergency時）
        triggers = report_data.get('triggers', [])
        if triggers:
            lines.append('')
            lines.append('【トリガー解説】')
            for t in triggers:
                lines.append(f'  {cls.trigger_comment(t)}')

        return '\n'.join(lines)

    @classmethod
    def _build_conclusion(cls, pattern: str, fear: int, t1_count: int) -> str:
        """1行結論を生成"""
        if pattern == 'C':
            return '全面安。全ポジション決済推奨。新規エントリー禁止。'
        elif pattern == 'B' and fear <= 45:
            return 'アルト祭り＋Fear域。積極的にロング。Tier2上位を狙え。'
        elif pattern == 'B':
            return 'アルト祭りだが過熱注意。利確タイミングを意識。'
        elif pattern == 'D' and fear <= 25:
            return '恐怖の中のAlpha。低相関銘柄の先行買い。'
        elif pattern == 'D':
            return '本質Alpha探し。低相関＋高乖離のみ厳選。'
        elif fear <= 10:
            return '極限恐怖。Bot-Alpha待機。歴史的買い場の可能性。'
        elif fear >= 80:
            return '極限貪欲。天井警戒。新規ロング禁止。'
        elif t1_count < 30:
            return '市場凍結。エントリー見送り。次の動きを待つ。'
        else:
            action = Commentary.REGIME_ACTIONS.get(pattern, '状況確認中。')
            return f'パターン{pattern}。{action}'
