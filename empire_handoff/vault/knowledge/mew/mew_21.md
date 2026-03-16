---
source_file: mew/21.txt
category: sector
tags: [sector_rotation, relative_strength, mindshare]
related_existing_logic: [sector_mapping]
new_logic_potential: medium
backtest_possible: partial
data_dependency: [ccxt_ohlcv]
priority: medium
created: 2026-03-10
---

# L21: セクターローテ(SDR)

## 概要
セクター間の資金ローテーションを検出し、次に注目されるセクターを予測するロジック。
相対強度(RS)の変化率とマインドシェアの推移を追跡。
AI/DeSci/RWA等の主要セクターを対象とする。

## 核心内容
- **Sシグナル**: RS変化率が上位20%（資金流入加速セクター）
- **Zシグナル（危険）**: 前週1位から流出（旬が終わったセクター）
- **追跡対象**: セクター別gainers数、マインドシェア推移
- **主要セクター**: AI、DeSci、RWA等

## トレードロジックへの変換
1. セクター分類マスタに基づき、各銘柄をセクターに割り当て
2. セクター別の平均リターン（RS）を日次/週次で計算
3. RS変化率（加速度）を算出し、上位20%を「ホットセクター」に分類
4. 前週RS1位セクターからの流出パターンを検出
5. ホットセクター所属銘柄をTier 1で優遇、流出セクターは抑制

## 既存システムとの統合ポイント
- sector_mapping（セクター分類マスタ）と直接連携
- Tier 1スクリーニングのセクターフィルターとして機能
- L17(相関シフト)と組み合わせ、セクター内でのBTC独立度を評価

## 実装に必要なデータ・API
- CCXT経由のOHLCVデータ（セクター別RS計算）
- セクター分類マスタ（銘柄→セクターのマッピング）
- マインドシェアデータ（LunarCrush、Kaito等のソーシャル指標）

## 元テキスト重要引用
- 「S: RS変化率上位20%」
- 「Z: 前週1位から流出」
- 「セクター別gainers/mindshare追跡」
- 「AI/DeSci/RWA」
