---
source_file: mew/9.txt
category: indicator
tags: [whale, CEX_flow, holder]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [external_api]
priority: low
created: 2026-03-10
---

# L09: 大口ウォレット動向

## 概要
大口ウォレット（Whale）のCEXへの入出金フローで需給を判定する。
MC 0.5%超のoutflowはSランク（大口が引き出し=保有意思）。
proxyとしてholder変化率やtop trader動向を参照。

## 核心内容
- **ランク判定**:
  - S: MC 0.5%超のoutflow（4h以内）
  - Z: MC 0.5%超のinflow（売却準備）
  - A: 小口取引のみ / 静観
- **proxy指標**: holder変化率 / top traderポジション

## トレードロジックへの変換
- 大口CEXフローを4h単位で監視
- Sランク（大口outflow）は保有確信の補助シグナル
- Zランク（大口inflow）はポジション縮小の警告

## 既存システムとの統合ポイント
- Tier 3の補助指標として機能（単独では使用しない）
- L03出来高スパイクの裏付けとして参照
- データ取得困難な場合はproxy（holder変化率）で代替

## 実装に必要なデータ・API
- オンチェーン分析API（Arkham, Nansen等）
- CEX入出金フローデータ
- proxy: CoinGecko holder情報、MEXC top traderデータ

## 元テキスト重要引用
- 「S: MC0.5%超outflow(4h)」
- 「Z: MC0.5%超inflow」
- 「A: 小口/静観」
- 「proxy=holder変化/top trader」
