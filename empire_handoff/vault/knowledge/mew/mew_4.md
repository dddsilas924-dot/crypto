---
source_file: mew/4.txt
category: sector
tags: [ecosystem, propagation, L1]
related_existing_logic: [sector_lag]
new_logic_potential: medium
backtest_possible: partial
data_dependency: [ccxt_ohlcv]
priority: medium
created: 2026-03-10
---

# L04: L1親子波及

## 概要
親チェーン（SOL/ETH/BNB/Base）のBTC相対リターンから子トークンへの波及を予測する。
波及ラグは平均1.5hで、4h/24hハイブリッド判定を行う。
セクターローテーション戦略の基盤ロジック。

## 核心内容
- **親チェーン対象**: SOL, ETH, BNB, Base
- **判定基準**: 親チェーンのBTC相対リターン
  - S: +2.0%超（24h）かつ +1.0%超（4h）
  - A: いずれかの閾値を超過
  - B: それ以外
- **波及ラグ**: 親→子への価格波及は平均1.5h
- **ハイブリッド判定**: 4h足と24h足の両方を参照

## トレードロジックへの変換
- 親チェーンのBTC相対リターンを4h/24hで監視
- Sランク親チェーンの子トークンを1.5h先行エントリー候補に
- セクター単位でのポジション管理

## 既存システムとの統合ポイント
- sector_lagロジックとの統合
- Tier 2のセクターフィルターとして機能
- L01レジームがS/A時のみ有効化

## 実装に必要なデータ・API
- ccxt OHLCV（親チェーントークン: SOL, ETH, BNB）
- 親子マッピングテーブル（手動定義またはCoinGeckoカテゴリ）

## 元テキスト重要引用
- 「親チェーン(SOL/ETH/BNB/Base)のBTC相対リターンでS/A/B判定」
- 「子トークンへの波及ラグ平均1.5h」
- 「4h/24hハイブリッド」
- 「閾値: +2.0%(24h), +1.0%(4h)」
