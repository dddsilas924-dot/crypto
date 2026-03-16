---
source_file: mew/6.txt
category: screening
tags: [ATR, volatility, wick_ratio, stability]
related_existing_logic: []
new_logic_potential: medium
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: medium
created: 2026-03-10
---

# L06: ボラ安定性

## 概要
ATR・標準偏差・ヒゲ/実体比率の3指標でボラティリティの安定性を評価する。
安定した値動きの銘柄を優先し、極端な髭や異常ボラの銘柄を除外。
板厚proxyとしてholder集中度・vol/MC比も参照。

## 核心内容
- **S判定条件（全て満たす）**:
  - ATR < avg * 0.8
  - std < avg * 0.8
  - wick_body < 0.93
- **Z判定条件（いずれか）**:
  - ATR > avg * 1.5
  - wick_body > 0.93
- **板厚proxy**: holder_top < 30% + vol/MC > 5%

## トレードロジックへの変換
- 1h足でATR・std・wick_body比を計算
- Sランク銘柄はエントリー適格、Zランクはスリッページリスクで除外
- 板厚proxyでさらにフィルタリング

## 既存システムとの統合ポイント
- Tier 1スクリーニングの安定性フィルター
- L10板厚み・スプレッドと補完関係
- ポジションサイジングの参考指標

## 実装に必要なデータ・API
- ccxt OHLCV（1h足、ATR計算用に14期間以上）
- holder情報（proxy、取得可能な場合）

## 元テキスト重要引用
- 「S: ATR<avg*0.8 AND std<avg*0.8 AND wick_body<0.93」
- 「Z: ATR>avg*1.5 OR wick_body>0.93」
- 「板厚proxy=holder_top<30%+vol/MC>5%」
