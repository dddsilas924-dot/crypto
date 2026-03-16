"""Bot表示名マッピング — GUI・Telegram・CLI共通
表示形式: [3文字略称] 日本語名
例: [LSA] レバ焼き秒スキャ・攻撃型
"""

# 内部名 → (略称, 日本語名)
_BOT_INFO = {
    # 基本Bot
    'alpha':          ('A01', 'アルファ（極限一撃）'),
    'surge':          ('S01', 'サージ（日常循環）'),
    'momentum':       ('M01', 'モメンタム（勢い追従）'),
    'rebound':        ('R01', 'リバウンド（反発狙い）'),
    'stability':      ('ST1', 'スタビリティ（安定収益）'),
    'trend':          ('T01', 'トレンド（方向追従）'),
    'cascade':        ('C01', 'カスケード（連鎖反応）'),
    # 平均回帰系
    'meanrevert':            ('MR1', '平均回帰（スタンダード）'),
    'meanrevert_adaptive':   ('MRA', '平均回帰（アダプティブ）'),
    'meanrevert_tight':      ('MRT', '平均回帰（タイト）'),
    'meanrevert_hybrid':     ('MRH', '平均回帰（ハイブリッド）'),
    'meanrevert_newlist':    ('MRN', '平均回帰（新規上場）'),
    'meanrevert_tuned':      ('MRU', '平均回帰（チューニング済）'),
    'meanrevert_strict_a':   ('MSA', '平均回帰（厳格A）'),
    'meanrevert_strict_b':   ('MSB', '平均回帰（超厳格B）'),
    'meanrevert_frarb':      ('MRF', '平均回帰FRArb'),
    # ブレイクアウト系
    'breakout':    ('B01', 'ブレイクアウト（突破）'),
    'btcfollow':   ('BF1', 'BTC追従'),
    'weakshort':   ('WS1', '弱者空売り'),
    'weakshort_strongfilter': ('WSF', '弱者空売り・強者除外'),
    # ボラティリティ系
    'volexhaust':  ('VE1', 'ボラ枯れ狙い'),
    'fearflat':    ('FF1', '恐怖フラット'),
    'domshift':    ('DS1', 'ドミナンスシフト'),
    'gaptrap':     ('GT1', 'ギャップトラップ'),
    # セクター系
    'sectorsync':    ('SS1', 'セクター連動'),
    'feardip':       ('FD1', '恐怖押し目'),
    'sectorlead':    ('SL1', 'セクターリード'),
    'shortsqueeze':  ('SQ1', 'ショートスクイーズ'),
    # 精密系
    'sniper':  ('SN1', 'スナイパー（狙撃）'),
    'scalp':   ('SC1', 'スキャルピング'),
    'event':   ('EV1', 'イベント駆動'),
    # ICO系
    'ico_meanrevert': ('IM1', 'ICO平均回帰'),
    'ico_rebound':    ('IR1', 'ICOリバウンド'),
    'ico_surge':      ('IS1', 'ICOサージ'),
    # 高頻度(HF)系
    'hf_meanrevert': ('HM1', 'HF平均回帰'),
    'hf_momentum':   ('HMO', 'HFモメンタム'),
    'hf_spread':     ('HSP', 'HFスプレッド'),
    'hf_break':      ('HBR', 'HFブレイク'),
    'hf_frarb':      ('HFA', 'HF FR裁定'),
    # レバ焼き系
    'levburn':                   ('LB1', 'レバ焼き（30分）'),
    'levburn_sec':               ('LS1', 'レバ焼き秒スキャ'),
    'levburn_sec_aggressive':    ('LSA', 'レバ焼き秒スキャ・攻撃型'),
    'levburn_sec_conservative':  ('LSC', 'レバ焼き秒スキャ・堅実型'),
    'levburn_sec_scalp_micro':   ('LSM', 'レバ焼き秒スキャ・マイクロ'),
    'levburn_sec_fr_extreme':    ('LSF', 'レバ焼き秒スキャ・FR極端'),
    # レバ1x固定版
    'levburn_sec_lev1':              ('L11', 'レバ焼き秒スキャ・1倍'),
    'levburn_sec_aggressive_lev1':   ('LA1', 'レバ焼き秒スキャ・攻撃型1倍'),
    'levburn_sec_conservative_lev1': ('LC1', 'レバ焼き秒スキャ・堅実型1倍'),
    'levburn_sec_scalp_micro_lev1':  ('LM1', 'レバ焼き秒スキャ・マイクロ1倍'),
    'levburn_sec_fr_extreme_lev1':   ('LF1', 'レバ焼き秒スキャ・FR極端1倍'),
    # レバ3x固定版
    'levburn_sec_lev3':              ('L31', 'レバ焼き秒スキャ・3倍'),
    'levburn_sec_aggressive_lev3':   ('LA3', 'レバ焼き秒スキャ・攻撃型3倍'),
    'levburn_sec_conservative_lev3': ('LC3', 'レバ焼き秒スキャ・堅実型3倍'),
    'levburn_sec_scalp_micro_lev3':  ('LM3', 'レバ焼き秒スキャ・マイクロ3倍'),
    'levburn_sec_fr_extreme_lev3':   ('LF3', 'レバ焼き秒スキャ・FR極端3倍'),
    # Aggressive最適化版
    'levburn_sec_agg_lev1':    ('AG1', 'レバ焼きAgg 1倍'),
    'levburn_sec_agg_lev3_ls': ('AG3', 'レバ焼きAgg 3倍'),
    'levburn_sec_agg_lev1_fr': ('AF1', 'レバ焼きAgg 1倍FR'),
    'levburn_sec_agg_lev3_fr': ('AF3', 'レバ焼きAgg 3倍FR'),
    'levburn_sec_agg_7x':     ('A7X', 'レバ焼きAgg 7倍'),
    'levburn_sec_agg_7x_so':  ('A7S', 'レバ焼きAgg 7倍SO'),
    'levburn_sec_agg_7x_fr':  ('A7F', 'レバ焼きAgg 7倍FR'),
    # Evolved全部盛り
    'levburn_sec_evo_agg':   ('EVA', 'レバ焼きEvo攻撃型'),
    'levburn_sec_evo_micro': ('EVM', 'レバ焼きEvoマイクロ'),
    'levburn_sec_evo_lev1':  ('EV1', 'レバ焼きEvo1倍'),
    # Alpha派生
    'alpha_r7': ('A07', 'アルファR7（緩和厳選）'),
}

# 旧互換: BOT_DISPLAY_NAMES (日本語名のみ)
BOT_DISPLAY_NAMES = {k: v[1] for k, v in _BOT_INFO.items()}


def get_display_name(bot_name: str) -> str:
    """内部Bot名 → [略称] 日本語名。未登録の場合はそのまま返す。"""
    info = _BOT_INFO.get(bot_name)
    if info:
        return f"[{info[0]}] {info[1]}"
    return bot_name


def get_prefix(bot_name: str) -> str:
    """内部Bot名 → 3文字略称"""
    info = _BOT_INFO.get(bot_name)
    return info[0] if info else bot_name[:3].upper()


def get_jp_name(bot_name: str) -> str:
    """内部Bot名 → 日本語名のみ（略称なし）"""
    info = _BOT_INFO.get(bot_name)
    return info[1] if info else bot_name
