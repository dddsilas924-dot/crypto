---
title: Empire Monitor ナレッジベース
version: "1.0"
created: 2026-03-09
source: gemini_crypto.txt, surf_crypto.txt
---

# Empire Monitor ナレッジベース

## 運用前提
- **取引所**: MEXC先物（将来: Binance, Bybit, PerpDEX）
- **対象**: 先物銘柄のみ（約870ペア）
- **スタイル**: スイングトレード + 短期利確（10%+）
- **レバレッジ**: 2-3x
- **監視サイクル**: 毎時定点観測
- **24時間365日稼働**

## Iron Rules（絶対遵守）
1. [[iron_rules/ai_role_restriction]] - AIはTier 3コメンタリーのみ。計算・判定への関与禁止
2. [[iron_rules/source_of_truth]] - 数値データはCCXT（MEXC API）経由の生値のみ
3. [[iron_rules/data_missing_rule]] - データ欠損はNone。推測値で埋めない
4. [[iron_rules/tier_structure]] - Tier 1→2→3のファンネル構造を厳守

## ドミナンス・マトリクス（市場環境認識）
- [[dominance_matrix/six_patterns]] - 6パターン定義
- [[dominance_matrix/current_regime]] - 現在のレジーム判定

| パターン | BTC価格 | BTC.D | Total MC | 執行判定 |
|----------|---------|-------|----------|----------|
| A: BTC独走 | 上昇 | 上昇 | 上昇 | 静観 |
| B: アルト祭 | 上昇 | 低下 | 上昇 | **全力買い** |
| C: 全面安 | 下落 | 上昇 | 下落 | **全切り** |
| D: 本質Alpha | 下落 | 低下 | 横ばい | **先行買い** |
| E: じわ下げ | 横ばい | 上昇 | 横ばい | 静観 |
| F: アルト循環 | 横ばい | 低下 | 横ばい | **短期狙い** |

## 21ロジック一覧

| # | ロジック名 | Group | Tier | Priority | 実装可否 | 概要 |
|---|-----------|-------|------|----------|----------|------|
| L01 | Dominance Matrix | A | meta | critical | true | BTC.D/USDT.D/TOTAL3でリスクオン/オフ判定 |
| L02 | Alpha Sanctuary | B | 1 | critical | true | **最重要**。10/10安値（聖域）割れ=即除外 |
| L03 | Inflow | B | 1 | high | true | 出来高スパイク検知（資金流入先特定） |
| L04 | Leading Indicator | B | 1 | high | true | ETH/BTC, SOL/ETH相対強度 |
| L06 | Surf AI Insight | D | 3 | medium | partial | テクニカル×ファンダギャップ分析 |
| L07 | Sector Flow | D | 3 | medium | partial | ETFフロー/セクター資金流入 |
| L08 | FR/OI Analysis | C | 2 | high | true | 踏み上げ/過熱/関心低下判定 |
| L09 | Immediate Entry | B | 1 | high | true | 異常ボラティリティ急変検知 |
| L10 | Liquidity Health | C | 2 | critical | true | 板厚チェック。VETO権発動 |
| L12 | Mindshare | D | 3 | medium | partial | SNS言及数/センチメント |
| L13 | LCEF | C | 2 | critical | partial | 清算クラスター近接度（Flash Crash防止） |
| L14 | CVM | C | 2 | medium | partial | クロスチェーンStablecoin流入速度 |
| L15 | WSR | D | 3 | medium | partial | クジラ保持率変化 |
| L16 | SSD | D | 3 | medium | partial | 供給ショック/取引所在庫急減 |
| L17 | CACS | B | 1 | high | true | BTC相関シフト（独自走銘柄検出） |
| L18 | GLM | A | meta | high | partial | グローバル流動性/DXY逆相関 |
| L19 | WCA | D | 3 | low | false | クジラ結束力（同時エントリー検出） |
| L20 | NPS | D | 3 | high | partial | P/S, MC/TVL割安判定 |
| L21 | SDR | D | 3 | high | partial | セクターローテーション現在地 |

| L23 | LevBurn | C | 2 | high | true | レバレッジ焼き（FR/OI/清算連鎖検知） |
| L24 | LevBurn-Sec | C | 2 | high | true | 1秒足スキャルピング（FR偏り+リアルタイム初動検知） |

**注**: L05, L11は欠番（元テキストで定義なし）

## Group A: Market Regime（環境認識）
全銘柄スコアリングの「係数」として機能
- [[logic_group_a/L01_dominance_matrix]] - ドミナンス・マトリクス
- [[logic_group_a/L18_global_liquidity]] - グローバル流動性モデル

## Group B: Tier 1 Screening（全数スクリーニング）
Pythonによる軽量計算。870銘柄の「足切り」
- [[logic_group_b/L02_alpha_sanctuary]] - **最重要**: 聖域（10/10安値）判定
- [[logic_group_b/L03_inflow]] - 出来高スパイク検知
- [[logic_group_b/L04_leading_indicator]] - ETH/BTC, SOL/ETH先行指標
- [[logic_group_b/L09_immediate_entry]] - 異常ボラティリティ急変検知
- [[logic_group_b/L17_correlation_shift]] - BTC相関シフト検出

## Group C: Tier 2 Validation（需給・健全性検証）
Tier 1通過銘柄のデリバティブ/板情報検証
- [[logic_group_c/L08_fr_oi_analysis]] - Funding Rate / Open Interest分析
- [[logic_group_c/L10_liquidity_health]] - 板の厚さ・健全性（VETO権）
- [[logic_group_c/L13_lcef]] - 清算クラスター近接度
- [[logic_group_c/L14_cvm]] - クロスチェーン燃料速度
- [[logic_group_c/L23_leverage_burn]] - レバレッジ焼きパターン（FR/OI/投機度）
- [[mew/mew_24_levburn_sec]] - LevBurn-Sec 1秒足スキャルピング

## Group D: Tier 3 Commentary（AI解説）
Pythonが計算した確定事実をAIが文章化
- [[logic_group_d/L06_surf_ai_insight]] - テクニカル×ファンダギャップ
- [[logic_group_d/L07_sector_flow]] - セクター資金流入/ETF
- [[logic_group_d/L12_mindshare]] - SNSセンチメント
- [[logic_group_d/L15_wsr]] - クジラ保持率
- [[logic_group_d/L16_ssd]] - 供給ショック
- [[logic_group_d/L19_wca]] - クジラ結束力
- [[logic_group_d/L20_nps]] - ネットワーク生産性（P/S割安判定）
- [[logic_group_d/L21_sdr]] - セクターローテーション

## 執行ルール
- [[execution/truth_rules]] - 真実の鉄則（200MA/5MA/資産防衛）
- [[execution/target_selection]] - ターゲット銘柄選定基準
- [[execution/operation_flow]] - 運用フロー（パイプライン実行順序）

## アーキテクチャ
- [[architecture/system_design]] - システム設計・ディレクトリ構成
- [[architecture/data_schema]] - Pydanticデータスキーマ
- [[architecture/ai_prompt_spec]] - Tier 3 AIプロンプト仕様

## 戦略
- [[strategy/core_philosophy]] - コア哲学（パターンD + 実需Alpha）
- [[strategy/pattern_d_playbook]] - パターンD プレイブック
- [[strategy/risk_management]] - リスク管理

## ソース対照

| カテゴリ | gemini_crypto由来 | surf_crypto由来 | 両方 |
|----------|-------------------|-----------------|------|
| Iron Rules | ai_role_restriction, source_of_truth, data_missing_rule, tier_structure | - | - |
| Dominance Matrix | - | current_regime | six_patterns |
| Group A | - | - | L01, L18 |
| Group B | - | - | L02, L03, L04, L09, L17 |
| Group C | - | - | L08, L10, L13, L14 |
| Group D | - | - | L06, L07, L12, L15, L16, L19, L20, L21 |
| 執行ルール | - | truth_rules, target_selection | operation_flow |
| アーキテクチャ | data_schema, ai_prompt_spec | - | system_design |
| 戦略 | - | core_philosophy, pattern_d_playbook | risk_management |

## ロジック→実装マッピング

| Logic | スクリーニング | エントリー | エグジット | ポジション管理 | 備考 |
|-------|---------------|-----------|-----------|---------------|------|
| L01 | 環境係数 | パターンB/D/F許可 | パターンC全切り | 全体係数 | meta |
| L02 | 聖域割れ除外 | 聖域反発=買い | 聖域割れ=損切り | SL位置決定 | **最重要** |
| L03 | Volume上位抽出 | 出来高伴走確認 | 出来高急減=警告 | - | |
| L04 | セクター判定 | L1強弱でセクター選択 | L1弱体化=利確 | - | |
| L08 | - | 踏み上げ=買い | FR過熱=利確 | OI監視 | Tier 2 |
| L09 | Top gainers | 急変初動乗り | 急落=即退 | - | 緊急チャネル |
| L10 | VETO除外 | 板厚確認 | 板薄化=縮小 | スリッページ管理 | **VETO最優先** |
| L13 | - | 清算リスク確認 | LCEF高=即退 | SL外側設定 | Flash Crash防止 |
| L14 | チェーン選択 | 資金流入確認 | 流出=縮小 | - | |
| L17 | Alpha検出 | BTC非相関=買い | 相関復帰=利確 | - | |
| L18 | マクロ係数 | DXY下落=追い風 | DXY急騰=縮小 | - | |
| L06-L21(D) | - | 参考情報 | 参考情報 | - | Tier 3 AI |
| truth_rules | 200MA下除外 | 200MA上必須 | 5MA割れ=全決済 | - | 鉄則 |

## 制約・注意事項
- Iron Rules（鉄の掟）は最優先。他のロジックがIron Rulesと矛盾する場合はIron Rulesが勝つ
- gemini_crypto.txtの元テキストに含まれる勝率等の数値のうち「捏造」と明記されているものは各MDで注記済み
- surf_crypto.txtの非現実的数値には各MDで「⚠️ 未検証・現実性要確認」と注記済み
- 定性的判断（「定性プロキシ」等）は無理に数値化せず、そのまま記述
- L05, L11は元テキストで定義なし（欠番）
- truth_rulesの10:30ルール/見せ板ルールは日本株固有。仮想通貨24時間市場への再解釈が必要
