# 3月13日以降にエントリーした銘柄一覧とBOT・条件の整理

ペーパートレードで **2026年3月13日以降** にエントリーした銘柄を洗い出し、どのBOTが・どんな条件で動いたかをわかりやすくまとめた。

---

## 1. 全体サマリー

| 項目 | 数値 |
|------|------|
| **エントリー総数** | 428件 |
| **銘柄数** | 13銘柄 |
| **作動したBOT** | すべて **LevBurn-Sec 系**（レバ焼き1秒足スキャン） |

※ Alpha / Surge / MeanRevert など他BOTからのエントリーはこの期間なし。

---

## 2. 銘柄別・BOT別エントリー数

| 銘柄 | LONG | SHORT | 主な作動BOT | エントリー数 |
|------|------|-------|-------------|-------------|
| **COS_USDT** | ○ | — | aggressive, aggressive_lev1/lev3, scalp_micro, levburn_sec, fr_extreme, agg_* 等 | **168件** |
| **TAG_USDT** | — | ○ | aggressive, levburn_sec, scalp_micro | **75件** |
| **RESOLV_USDT** | ○ | — | aggressive, agg_*, levburn_sec, scalp_micro 等 | **55件** |
| **TOWNS_USDT** | ○ | — | aggressive, agg_*, scalp_micro | **26件** |
| **THE_USDT** | ○ | — | levburn_sec, agg_*, aggressive, evo_*, fr_extreme 等 | **28件** |
| **DENT_USDT** | ○ | — | aggressive, levburn_sec, scalp_micro | **14件** |
| **MELANIA_USDT** | ○ | — | aggressive, scalp_micro | **5件** |
| **SIREN_USDT** | ○ | — | aggressive_lev1, scalp_micro_lev1 | **3件** |
| **AGT_USDT** | — | ○ | aggressive, aggressive_lev1/lev3 | **3件** |
| **LYN_USDT** | ○ | — | aggressive | **1件** |
| **NAORIS_USDT** | — | ○ | aggressive | **1件** |
| **TRUMPOFFICIAL_USDT** | ○ | — | aggressive | **1件** |
| **VVV_USDT** | ○ | — | aggressive | **1件** |

※ 同一銘柄に複数BOTがそれぞれエントリーするため、銘柄あたりの「トレード数」はBOT数×決済回数で増える。

---

## 3. この期間のエントリー経路（Tier1・ドミナンスの位置づけ）

### 3.1 今回のエントリーは「LevBurn-Sec」だけ

3月13日以降のペーパーエントリーは **すべて LevBurn-Sec 系BOT** から。

- **Alpha**（Fear<10 極限一撃）・**Surge**（Fear 25–45）・**MeanRevert**（Fear 50–80）などは、この期間は条件を満たさずエントリーなし。
- **30分間隔の LevBurn** は、Tier1通過銘柄を対象にFRスキャンするが、シグナルは別経路。今回の428件はすべて **1秒足スキャンの LevBurn-Sec**。

### 3.2 LevBurn-Sec の銘柄の選ばれ方（Tier1との関係）

- **Tier1（870→Top50）**  
  - メインループでは「聖域割れなし（L02）」「出来高スパイク（L03）」「先行指標（L04）」「ボラ急変（L09）」「相関シフト（L17）」などでスクリーニング。
  - **30分 LevBurn** は、この **Tier1通過銘柄の上位50** のFRを取得し、**FRが閾値を超えた銘柄を「ホットリスト」に載せる**。
- **LevBurn-Sec** は **「ホットリストに載った銘柄」だけ** を5秒ごとにスキャンする。
  - ホットリストは主に「30分LevBurnでTier1通過銘柄のFRを取った結果、閾値超えだったもの」で更新される。
  - そのため、**今回エントリーした銘柄は「いずれかの時点でTier1を通過し、かつFRが閾値を超えた」と解釈してよい**（実装は「Tier1通過→FR取得→閾値超えでホット入り→LevBurn-Secがスキャン」）。
- **ドミナンス（L01）**  
  - BTC.D / Total MC などでパターンA〜F（リスクオン/オフ）を判定し、**メインループのレジーム**として使われる。
  - LevBurn-Sec の**銘柄選定**には使っていない。  
  - ただし **Fear&Greed** は LevBurn-Sec に渡しており、「Fear<25 かつ LONG」のときにFRスコアに +10 するなど、**スコア調整**には使っている（LONGを止める条件にはなっていない）。

### 3.3 まとめ（条件の関係）

| 条件 | 役割 |
|------|------|
| **Tier1通過** | 30分LevBurnがFRを取得する対象＝「Tier1通過の上位50」のFRが閾値超えならホットリスト入り。**今回の13銘柄は、その時点でTier1を通過していたとみなせる。** |
| **ドミナンス（L01）** | メインのレジーム判定用。LevBurn-Secの銘柄リストの絞り込みには未使用。 |
| **Fear&Greed** | LevBurn-SecのFRスコアの微調整（Fear<25でLONGに+10など）。エントリー可否のガードには未使用。 |
| **FR（資金調達率）** | **必須。** 閾値超えでホット入り。FR>0 → SHORT、FR<0 → LONG の方向決定。 |
| **1秒足トリガー** | 価格変動・出来高スパイク・約定偏り・板の偏りが、各BOTの「最低トリガースコア」を超えたときだけエントリー。 |

---

## 4. 作動したBOTとエントリー基準（わかりやすく）

いずれも **「FRで方向が決まる ＋ 1秒足でタイミングが決まる」** 構造。

### 4.1 共通の流れ（2段階）

1. **第1段階（FR）**  
   - その銘柄の **資金調達率（FR）** が一定以上（目安: 0.05%〜0.3%程度）に偏っている。  
   - **FR > 0** → ロングが溜まりすぎ → **SHORT** でエントリー。  
   - **FR < 0** → ショートが溜まりすぎ → **LONG** でエントリー。

2. **第2段階（リアルタイム）**  
   - 1秒足の **価格の急な動き**（例: 1秒で0.3%以上）  
   - **出来高の急増**（直近の出来高が平均の3倍以上など）  
   - **約定の偏り**（買いと売りの比率）  
   - **板の偏り**（買い板と売り板の厚さの比）  
   → これらをスコア化し、**バリアントごとの「最低スコア」を超えたとき** にエントリー。

### 4.2 BOT別の違い（イメージ）

| BOT名 | イメージ | エントリーの厳しさ | TP/SL | レバ |
|-------|----------|---------------------|-------|------|
| **levburn_sec** | 標準型 | やや厳しめ（スコア60以上など） | TP1.5% / SL0.5% | 10x |
| **levburn_sec_aggressive** | 攻撃型 | やや緩い（スコア50以上など） | TP3% / SL1% | 7〜15x |
| **levburn_sec_conservative** | 堅実型 | 厳しめ（スコア75以上など） | TP1% / SL0.3% | 7x |
| **levburn_sec_scalp_micro** | 超短期 | スコア高めだがTP/SLが小さい | TP0.5% / SL0.2% | 20x |
| **levburn_sec_fr_extreme** | FR極端時 | FRが特に大きいときだけ | TP2% / SL0.8% | 10x |
| **levburn_sec_agg_lev1 / agg_lev3_ls / agg_7x 等** | Aggressive最適化版 | aggressive に近いがレバや方向フィルター違い | 3% / 1% など | 1x, 3x, 7x |
| **levburn_sec_evo_*** | Evolved版 | 上に加え追加フィルター（板・OI方向など） | 同上 | 同上 |

※ 「Tier1を通過」は「30分LevBurnの対象＝ホットリストの元」という意味で効いている。「ドミナンス」は銘柄選定には使われず、レジーム用。

---

## 5. 銘柄ごとの「なぜこの銘柄にエントリーしたか」

- **COS_USDT**  
  FRがマイナス（ロング過多）と判定される時間が長く、ホットリストに長く残った。1秒足の動きも条件を満たしやすく、複数BOTが何度もLONGでエントリー。結果としてトレード数・損失が集中。

- **RESOLV_USDT**  
  〃 同様にFRマイナスでLONG候補になり、ホット入りして繰り返しエントリー。

- **TAG_USDT**  
  FRがプラス（ショート過多）と判定され、SHORTでエントリー。レポート上は成績の良い銘柄の一つ。

- **TOWNS_USDT / THE_USDT / DENT_USDT**  
  FRが閾値を超えてホット入りし、主にLONGでエントリー。

- **MELANIA_USDT / TRUMPOFFICIAL_USDT**  
  ミーム系。FRが閾値超えでホット入りし、LONGでエントリー（TRUMPはポンプ後の反転でSLに直結した例としてレポートに記載）。

- **AGT_USDT / NAORIS_USDT**  
  FRがプラス側でホット入りし、SHORTでエントリー。

- **LYN_USDT / SIREN_USDT / VVV_USDT**  
  いずれもFR閾値超えでホット入りし、LONG（SIRENはaggressive_lev1 等）で少数エントリー。

---

## 6. 参照

- エントリー元データ: `vault/export/paper_signals.csv`（3月13日以降 428件）
- LevBurn-Secロジック: `vault/knowledge/mew/mew_24_levburn_sec.md`
- ドミナンス: `vault/knowledge/logic_group_a/L01_dominance_matrix.md`
- Tier1: `src/signals/tier1_engine.py`（L02聖域, L03出来高, L04先行指標, L09ボラ, L17相関）
- エンジン上の流れ: `src/core/engine.py`（Tier1→Tier2→30分LevBurnでFR取得→ホットリスト→LevBurn-Secスキャン）

以上。
