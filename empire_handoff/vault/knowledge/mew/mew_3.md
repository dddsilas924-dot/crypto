---
source_file: mew/3.txt
category: screening
tags: [volume_spike, wash_trade, 48h_SMA]
related_existing_logic: [Bot-Surge]
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: critical
created: 2026-03-10
---

# L03: 出来高スパイク(資金流入ランキング)

## 概要
24h出来高と48h SMAの比率で資金流入の強度を判定する。
Wash Trade対策として出来高成長/トランザクション成長比を監視し、異常値を強制除外。
Bot-Surgeの中核ロジック。

## 核心内容
- **Volume Ratio計算**: Volume_Ratio = 24h_vol / 48h_SMA
- **ランク判定**:
  - S: 3.0x超
  - A: 1.5-3.0x
  - B: 0.8-1.5x
  - C/Z: 0.8未満
- **Wash Trade対策**: vol成長 / tx成長 > 2.5 で強制C/Z格下げ

## トレードロジックへの変換
- 48h SMAをローリング計算し、24h出来高との比率をリアルタイム監視
- Sランク銘柄を資金流入ランキングとしてリスト化
- Wash Trade検知で自動除外フィルター

## 既存システムとの統合ポイント
- Bot-Surgeのスクリーニングロジックとして直接統合
- Tier 1の出来高フィルターとして全銘柄に適用
- L02回復率と組み合わせて「回復+資金流入」の複合シグナル

## 実装に必要なデータ・API
- ccxt OHLCV（1h足、48h分以上）
- トランザクション数（Wash Trade対策用、取得可能な場合）

## 元テキスト重要引用
- 「Volume_Ratio=24h_vol/48h_SMA」
- 「S:3.0x超, A:1.5-3.0x, B:0.8-1.5x, C/Z:0.8未満」
- 「Wash対策: vol成長/tx成長>2.5で強制C/Z」
