---
source_file: mew/15.txt
category: exit
tags: [ATR_trail, stop_loss, take_profit, time_exit]
related_existing_logic: []
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: critical
created: 2026-03-10
---

# L15: ATRトレール利確損切

## 概要
ATR(14)ベースのトレーリングストップによる動的な損切・利確ロジック。
時間切れ撤退ルールを組み合わせ、横ばい相場での資金拘束を回避。
L02のボリュームレジーム転換やFR反転も即時撤退トリガーとする。

## 核心内容
- **トレーリングSL**: 高値 - 2 * ATR(14)
- **ATR倍率の最適値**: 2x（1x=ストップ狩り40%、3x=逃げ遅れ25%）
- **時間切れ撤退**: 4h横ばい（<1%変化）で強制撤退
- **TP設定**: entry * 2（リスクリワード 1:2）
- **即時撤退条件**: L02のボリュームレジームがBearish転換、またはFR反転時

## トレードロジックへの変換
1. エントリー時にATR(14)を計算し、初期SL = entry - 2*ATR を設定
2. 価格更新ごとにトレーリング: SL = max(現SL, 高値 - 2*ATR)
3. TP = entry + (entry - 初期SL) * 2 でRR1:2を確保
4. 4h足の変化率が1%未満なら時間切れ撤退
5. L02ボリュームレジーム・FR反転を監視し、条件合致で即撤退

## 既存システムとの統合ポイント
- L14(ケリー基準)のATR計算と共有
- L02(ボリュームレジーム)の状態変化をトリガーとして監視
- Tier 3エントリー後のポジション管理フローに直接組み込み

## 実装に必要なデータ・API
- CCXT経由のOHLCVデータ（ATR(14)計算、4h足変化率）
- リアルタイム価格フィード（トレーリング更新用）
- Funding Rate データ（FR反転検出用）

## 元テキスト重要引用
- 「トレールSL=高値-2*ATR(14)」
- 「2xATR最適(1x=刈り40%, 3x=逃げ遅れ25%)」
- 「4h横ばい(<1%変化)で時間切れ撤退」
- 「TP=entry*2(RR1:2)」
- 「L02転B/FR反転で即撤退」
