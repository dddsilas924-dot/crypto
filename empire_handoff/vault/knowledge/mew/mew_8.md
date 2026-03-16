---
source_file: mew/8.txt
category: indicator
tags: [funding_rate, open_interest, demand_supply]
related_existing_logic: [Bot-Surge]
new_logic_potential: medium
backtest_possible: partial
data_dependency: [external_api]
priority: medium
created: 2026-03-10
---

# L08: FR/OI需給判定

## 概要
Funding Rate（FR）とOpen Interest（OI）の組み合わせで先物市場の需給バランスを判定。
負のFR + OI増加はショートスクイーズの前兆としてSランク。
+0.05%超のFRは「死のFR」としてVETO。

## 核心内容
- **ランク判定**:
  - S: FR -0.01% ~ -0.05% かつ OI +15% / +30%
  - A: FR 0.01% ~ 0.03%
  - Z: FR > +0.05%（死のFR）
- **FR計算**: 8h平均FR
- **OI変化率**: 24h基準

## トレードロジックへの変換
- 8h平均FRとOI変化率をリアルタイム監視
- Sランク（負FR + OI増）でショートスクイーズ期待のエントリー
- 死のFR（+0.05%超）で即時VETO

## 既存システムとの統合ポイント
- Bot-Surgeの需給判定ロジックとして統合
- L13最終判定の優先VETO（優先順位3位）
- L03出来高スパイクとの複合で資金流入の質を判定

## 実装に必要なデータ・API
- MEXC Funding Rate API（8h間隔）
- MEXC Open Interest API
- 外部API（Coinglass等でクロス取引所OI）

## 元テキスト重要引用
- 「S: FR-0.01~-0.05%∩OI+15%/+30%」
- 「A: FR0.01~0.03%」
- 「Z: FR>+0.05%(死のFR)」
- 「8h平均FR」
