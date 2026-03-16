---
source_file: mew/1.txt
category: market_regime
tags: [BTC.D, Total_MC, regime]
related_existing_logic: [regime.py]
new_logic_potential: medium
backtest_possible: true
data_dependency: [ccxt_ticker]
priority: high
created: 2026-03-10
---

# L01: ドミナンス・マトリクス

## 概要
BTC価格・BTC.D・Total MC(Total3推奨)の3軸方向判定によるS-Zランク5段階の市場レジーム分類。
Sランク=アルト黄金期を示し、既存regime.pyのA-Fパターンと対応する。
1h更新、CoinGecko/globalエンドポイントを使用。

## 核心内容
- **3軸方向判定**: BTC価格 / BTC.D / Total3 の各変化率を閾値で上昇・横ばい・下落に分類
- **閾値設定**: BTC ±2.8%, BTC.D ±1.2%, Total3 ±1.0%
- **5段階ランク**:
  - S: アルト黄金期（BTC横ばい or 微上昇、BTC.D下落、Total3上昇）
  - A: アルト優勢
  - B: 中立
  - C: BTC優勢
  - Z: アルト冬（BTC.D急上昇、Total3下落）
- 更新頻度: 1h

## トレードロジックへの変換
- regime.pyの既存A-Fパターンをこの5段階に統合またはマッピング
- Sランク時のみアグレッシブなアルトエントリー許可
- Z判定時はアルトポジション縮小/VETO

## 既存システムとの統合ポイント
- regime.pyのレジーム判定ロジックを拡張
- Tier 1スクリーニングの前段フィルターとして機能
- 全ロジックの基盤レジームとしてL13総合判定に供給

## 実装に必要なデータ・API
- CoinGecko `/global` エンドポイント（BTC.D, Total MC）
- ccxt ticker（BTC価格）
- Total3（CoinGecko or TradingView）

## 元テキスト重要引用
- 「S-Zランク5段階。BTC価格/BTC.D/Total MC(Total3推奨)の3軸方向判定」
- 「閾値: BTC±2.8%, BTC.D±1.2%, Total3±1.0%」
- 「Sランク=アルト黄金期」
- 「既存regime.pyのA-Fパターンと対応」
