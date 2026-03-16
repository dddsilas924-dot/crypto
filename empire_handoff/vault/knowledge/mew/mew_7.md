---
source_file: mew/7.txt
category: indicator
tags: [MA_deviation, overheating, MA20, MA80]
related_existing_logic: []
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: high
created: 2026-03-10
---

# L07: MA乖離率・過熱判定

## 概要
1h足MA20/MA80からの乖離率で過熱度を判定する。
適正乖離帯をSランク、過熱帯をB/Zランクとし、MA20+25%を調整限界とする。
エントリータイミングと利確判断の両方に使用。

## 核心内容
- **ランク判定**:
  - S: 1h_MA20乖離 +3~8%, MA80乖離 0~5%
  - B: MA20乖離 8~20%
  - Z: MA20乖離 > 30% or < 0%
- **調整限界**: MA20 + 25% で 90%の確率で調整発生
- **使用MA**: 1h足 MA20, MA80

## トレードロジックへの変換
- リアルタイムでMA20/MA80乖離率を計算
- Sランク帯でのみエントリー許可
- MA20+25%接近時に利確シグナル発信

## 既存システムとの統合ポイント
- Tier 2のエントリーフィルターとして機能
- L02回復率がS/Aでも、MA乖離がZなら過熱VETOを発動
- 利確ロジックのトリガーとしてL13に供給

## 実装に必要なデータ・API
- ccxt OHLCV（1h足、MA80計算用に80期間以上）

## 元テキスト重要引用
- 「S: 1h_MA20乖離+3~8%, MA80 0~5%」
- 「B: MA20 8~20%」
- 「Z: MA20>30% or <0%」
- 「限界=MA20+25%で90%調整」
