"""トレードシリアル番号生成 — BOT別プレフィックス + 6桁通し番号

形式: [prefix]-[6桁連番]
例: S01-000001 (surge 1件目), LA7-000042 (levburn_sec_agg_7x 42件目)

プレフィックスはBOTカテゴリ(1~2文字) + 番号(1~2文字) の3文字
"""
import threading

# BOT名 → 3文字プレフィックス
BOT_PREFIX_MAP = {
    # 基本Bot
    'alpha': 'A01',
    'alpha_r7': 'A07',
    'surge': 'S01',
    'momentum': 'M01',
    'rebound': 'R01',
    'stability': 'ST1',
    'trend': 'T01',
    'cascade': 'C01',
    # 平均回帰系
    'meanrevert': 'MR1',
    'meanrevert_adaptive': 'MRA',
    'meanrevert_tight': 'MRT',
    'meanrevert_hybrid': 'MRH',
    'meanrevert_newlist': 'MRN',
    'meanrevert_tuned': 'MRU',
    'meanrevert_strict_a': 'MSA',
    'meanrevert_strict_b': 'MSB',
    'meanrevert_frarb': 'MRF',
    # ブレイクアウト系
    'breakout': 'B01',
    'btcfollow': 'BF1',
    'weakshort': 'WS1',
    'weakshort_strongfilter': 'WSF',
    # ボラティリティ系
    'volexhaust': 'VE1',
    'fearflat': 'FF1',
    'domshift': 'DS1',
    'gaptrap': 'GT1',
    # セクター系
    'sectorsync': 'SS1',
    'feardip': 'FD1',
    'sectorlead': 'SL1',
    'shortsqueeze': 'SQ1',
    # 精密系
    'sniper': 'SN1',
    'scalp': 'SC1',
    'event': 'EV1',
    # ICO系
    'ico_meanrevert': 'IM1',
    'ico_rebound': 'IR1',
    'ico_surge': 'IS1',
    # HF系
    'hf_meanrevert': 'HM1',
    'hf_momentum': 'HMO',
    'hf_spread': 'HSP',
    'hf_break': 'HBR',
    'hf_frarb': 'HFA',
    # レバ焼き系
    'levburn': 'LB1',
    'levburn_sec': 'LS1',
    'levburn_sec_aggressive': 'LSA',
    'levburn_sec_conservative': 'LSC',
    'levburn_sec_scalp_micro': 'LSM',
    'levburn_sec_fr_extreme': 'LSF',
    # レバ1x/3x固定版
    'levburn_sec_lev1': 'L11',
    'levburn_sec_aggressive_lev1': 'LA1',
    'levburn_sec_conservative_lev1': 'LC1',
    'levburn_sec_scalp_micro_lev1': 'LM1',
    'levburn_sec_fr_extreme_lev1': 'LF1',
    'levburn_sec_lev3': 'L31',
    'levburn_sec_aggressive_lev3': 'LA3',
    'levburn_sec_conservative_lev3': 'LC3',
    'levburn_sec_scalp_micro_lev3': 'LM3',
    'levburn_sec_fr_extreme_lev3': 'LF3',
    # Aggressive最適化版
    'levburn_sec_agg_lev1': 'AG1',
    'levburn_sec_agg_lev3_ls': 'AG3',
    'levburn_sec_agg_lev1_fr': 'AF1',
    'levburn_sec_agg_lev3_fr': 'AF3',
    'levburn_sec_agg_7x': 'A7X',
    'levburn_sec_agg_7x_so': 'A7S',
    'levburn_sec_agg_7x_fr': 'A7F',
    # Evolved全部盛り
    'levburn_sec_evo_agg': 'EVA',
    'levburn_sec_evo_micro': 'EVM',
    'levburn_sec_evo_lev1': 'EV1',
}


class TradeSerialGenerator:
    """スレッドセーフなシリアル番号生成器。DBから最大番号を復元。"""

    def __init__(self, db=None):
        self._counters = {}  # {prefix: current_count}
        self._lock = threading.Lock()
        if db:
            self._restore_from_db(db)

    def _restore_from_db(self, db):
        """DBの既存trade_recordsからカウンターを復元"""
        try:
            conn = db._get_conn()
            # trade_serial カラムが存在するか確認
            cols = [c[1] for c in conn.execute('PRAGMA table_info(trade_records)').fetchall()]
            if 'trade_serial' not in cols:
                conn.close()
                return

            rows = conn.execute(
                "SELECT trade_serial FROM trade_records WHERE trade_serial IS NOT NULL"
            ).fetchall()
            conn.close()

            for (serial,) in rows:
                if serial and '-' in serial:
                    prefix, num_str = serial.split('-', 1)
                    try:
                        num = int(num_str)
                        with self._lock:
                            if prefix not in self._counters or num > self._counters[prefix]:
                                self._counters[prefix] = num
                    except ValueError:
                        pass
        except Exception:
            pass

    def next_serial(self, bot_name: str) -> str:
        """次のシリアル番号を生成: PREFIX-NNNNNN"""
        prefix = BOT_PREFIX_MAP.get(bot_name, bot_name[:3].upper())
        with self._lock:
            count = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = count
        return f"{prefix}-{count:06d}"

    def get_prefix(self, bot_name: str) -> str:
        """BOT名からプレフィックスを取得"""
        return BOT_PREFIX_MAP.get(bot_name, bot_name[:3].upper())
