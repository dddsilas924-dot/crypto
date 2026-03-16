---
source_file: mew/5.txt
category: entry
tags: [rebound_speed, leading, BTC_correlation]
related_existing_logic: [Bot-Alpha]
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: critical
created: 2026-03-10
---

# L05: BTC反発先行性

## 概要
BTC反発時にアルトコインがBTCより先行して反発する度合いを測定する。
3hルックバックでBTC反発比を算出し、反発先行性の高い銘柄を選抜。
Bot-Alphaのエントリータイミング精度向上に直結。

## 核心内容
- **ルックバック**: 3h
- **ランク判定**:
  - S: alt_gain > btc_gain * 1.5
  - A: alt_gain >= btc_gain
  - B: それ以外
- **推奨時間足**: 1h足が最適
- **ボラティリティ補正**: 高ボラ時 1.4倍、低ボラ時 1.6倍

## トレードロジックへの変換
- BTC反発検知後、3hルックバックでアルト/BTC反発比を計算
- Sランク銘柄を優先エントリー候補に
- ボラティリティに応じて乗数を動的調整

## 既存システムとの統合ポイント
- Bot-Alphaのエントリーロジックとして直接統合
- L02回復率と組み合わせて「回復力+先行性」の複合判定
- Tier 2→Tier 3昇格条件の一つ

## 実装に必要なデータ・API
- ccxt OHLCV（1h足、BTC + 対象アルト）
- ATRまたはボラティリティ指標（補正用）

## 元テキスト重要引用
- 「3hルックバックでBTC反発比」
- 「S: alt_gain>btc_gain*1.5, A: alt_gain>=btc_gain」
- 「1h足最適」
- 「高ボラ時1.4倍、低ボラ時1.6倍」
