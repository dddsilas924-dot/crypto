---
source_file: mew/10.txt
category: risk_management
tags: [orderbook, spread, liquidity]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [ccxt_orderbook]
priority: medium
created: 2026-03-10
---

# L10: 板厚み・スプレッド

## 概要
オーダーブックの板厚みとスプレッドで流動性リスクを評価する。
スプレッド0.5%をデッドラインとし、超過銘柄はスリッページリスクで除外。
L13最終判定の優先VETO（優先順位2位）。

## 核心内容
- **ランク判定**:
  - S: spread < 0.1% かつ depth/vol > 5%
  - Z: spread > 0.5% or depth/vol < 0.01
- **デッドライン**: スプレッド 0.5%
- **板厚み指標**: depth / volume 比率

## トレードロジックへの変換
- エントリー前にリアルタイムでスプレッド・板厚みをチェック
- Z判定で即時エントリー拒否
- ポジションサイズを板厚みに応じて動的調整

## 既存システムとの統合ポイント
- L13最終判定の優先VETO（優先順位2位: L12イベント > L10スリッページ > L08死FR）
- L06ボラ安定性と補完関係
- 全エントリーの最終ゲートキーパー

## 実装に必要なデータ・API
- ccxt orderbook（MEXC先物）
- リアルタイムBid/Askスプレッド
- オーダーブック深度データ

## 元テキスト重要引用
- 「S: spread<0.1%+depth/vol>5%」
- 「Z: spread>0.5% or depth/vol<0.01」
- 「スプレッド0.5%デッドライン」
