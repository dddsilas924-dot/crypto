---
source_file: mew/20.txt
category: screening
tags: [DAU, revenue, FDV, fundamental]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [external_api]
priority: low
created: 2026-03-10
---

# L20: ネットワーク生産性(NPS)

## 概要
プロトコルの実質的な生産性を定量化するファンダメンタル指標。
DAU(日次アクティブユーザー)、Revenue(収益)、FDV(完全希薄化時価総額)を組み合わせ、
過大評価・過小評価を判定するスクリーニングロジック。

## 核心内容
- **NPS計算式**: NPS = (DAU * Revenue) / FDV
- **Sシグナル**: NPSが右肩上がり（生産性向上トレンド）
- **Zシグナル（危険）**: Revenue = 0（収益なしプロジェクト）
- **比較基準**: セクター平均との相対比較

## トレードロジックへの変換
1. 各トークンのDAU、Revenue、FDVを日次で取得
2. NPS = (DAU * Revenue) / FDV を計算
3. 7d/30dのNPSトレンド（傾き）を算出
4. 同セクター内の平均NPSとの相対位置を判定
5. NPS右肩上がり + セクター平均以上 → Tier 1通過
6. Revenue = 0 → 即除外

## 既存システムとの統合ポイント
- Tier 1スクリーニングのファンダメンタルフィルターとして機能
- L21(セクターローテーション)のセクター分類と連携
- Tier 2の総合スコアリングにおける信頼度補強

## 実装に必要なデータ・API
- DAUデータ（DappRadar、Token Terminal等）
- プロトコル収益データ（Token Terminal、DefiLlama等）
- FDVデータ（CoinGecko、CoinMarketCap等）
- セクター分類マスタデータ

## 元テキスト重要引用
- 「NPS=(DAU×Revenue)/FDV」
- 「右肩上がり=S」
- 「Revenue=0はZ」
- 「セクター平均比較」
