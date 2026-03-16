---
source_file: mew/2.txt
category: screening
tags: [recovery_rate, sacred_low, alpha]
related_existing_logic: [Bot-Alpha]
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: critical
created: 2026-03-10
---

# L02: Alpha髭下乖離・回復率

## 概要
暴落後の回復率を定量化し、反発力の強い銘柄をS/A/B/Zランクで選抜する。
聖域安値（Sacred Low）を基準に回復率を算出し、聖域割れはVETOで即除外。
Bot-Alphaの中核ロジックとして機能。

## 核心内容
- **回復率計算式**: (現在価格 - 聖域安値) / (暴落前高値 - 聖域安値) * 100
- **ランク判定**:
  - S: 回復率 80%超
  - A: 50-80%
  - B: 20-50%
  - Z: 負値（聖域割れ → VETO）
- **暴落前高値の定義**: BTC 24h下落 > 7% をトリガーとし、21日遡りLocal Max
- **髭ノイズ除外**: 3σ + 低Volume除外

## トレードロジックへの変換
- BTC暴落トリガー検知 → 21日ルックバックで暴落前高値を自動取得
- 聖域安値をリアルタイム追跡し、回復率を1h足で算出
- S/Aランク銘柄をTier 2に昇格

## 既存システムとの統合ポイント
- Bot-Alphaの銘柄選抜ロジックとして直接統合
- L05（BTC反発先行性）と組み合わせてエントリー精度向上
- 聖域割れVETOはL13最終判定に直結

## 実装に必要なデータ・API
- ccxt OHLCV（1h足、21日分）
- BTC 24h変化率（暴落トリガー判定用）

## 元テキスト重要引用
- 「回復率=(現在価格-聖域安値)/(暴落前高値-聖域安値)*100」
- 「Z:負(聖域割れVETO)」
- 「暴落前高値=BTC24h下落>7%トリガーで21日遡りLocal Max」
- 「髭ノイズ=3σ+低Vol除外」
