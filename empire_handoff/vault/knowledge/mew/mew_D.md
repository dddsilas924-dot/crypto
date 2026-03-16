---
source_file: mew/D.txt
category: screening
tags: [supply_shock, burn, illiquid_supply]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [external_api]
priority: low
created: 2026-03-10
---

# Deep Logic D: 供給ショック(SSD)

## 概要
トークン供給の減少率と需要増加率の関係から供給ショック状態を検出するスクリーニングロジック。
Revenue増加と供給絞りが同時に発生する銘柄を最優先で抽出。
デフレーショナリー・トークノミクスの実効性を定量評価する。

## 核心内容
- **供給ショック条件**: 供給減少率 > 需要増加率
- **最優先抽出条件**: Revenue増 + 供給絞り = 供給ショック
- **分析要素**: burn量、illiquid supply比率、ステーキングロック量
- **原理**: 供給制約下での需要増 = 価格上昇圧力の構造的優位

## トレードロジックへの変換
1. トークンの流通供給量の変化率を日次で計算（burn、ロック等を含む）
2. 需要指標（取引量、DAU、Revenue）の変化率を同期間で計算
3. 供給減少率 > 需要増加率 の銘柄を供給ショック候補として抽出
4. Revenue増 + 供給減少が同時発生する銘柄を最優先ランクに昇格
5. Tier 1スクリーニングのファンダメンタル最優先フィルターとして適用

## 既存システムとの統合ポイント
- L20(ネットワーク生産性)のRevenue分析と連携
- Tier 1スクリーニングの供給サイド評価レイヤーとして機能
- L19/L-C(クジラ分析)のHODL行動による実質的供給減少と補完関係

## 実装に必要なデータ・API
- トークン供給量データ（CoinGecko、トークン固有API）
- burn/mint イベントデータ（オンチェーン）
- ステーキング/ロック量データ（DefiLlama等）
- Revenue/取引量データ（Token Terminal等）

## 元テキスト重要引用
- 「供給減少率>需要増加率」
- 「Revenue増+供給絞り=供給ショック最優先抽出」
