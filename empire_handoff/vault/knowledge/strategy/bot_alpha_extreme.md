---
logic_id: bot_alpha
category: strategy
tags: [fear_greed, extreme_fear, one_shot, high_leverage]
source: alpha_logic
tier: meta
group: strategy
implementable: true
data_dependency: [fear_greed_api, ccxt_ohlcv, ccxt_ticker]
priority: critical
exchange: MEXC
backtest_possible: true
---

# Bot-Alpha: 極限一撃モード

## 概要
Fear & Greed Index < 10（年1-3回）で発火する一撃必殺モード。
BTC下落局面で低相関・高アルファ銘柄を狙い撃ちする。
alpha_logic.txt の分析データに基づく高エッジ戦略。

## 定義・目的
極端な恐怖相場（Extreme Fear）は歴史的に底打ち反発の買い場。直近データ（2026-02-24〜03-09の2週間データに基づく）で、Fear 7 の環境下でJTO（相関0.17）やTAO（max alpha 6.41%）が BTC下落耐性を示し、大幅なアルファを記録。このパターンを自動検知しシグナル化する。

## 発動条件
1. Fear & Greed Index < 10
2. BTC日次リターン ≤ -1%
3. BTC.D（ドミナンス）前日比 -0.5%以上下落

三条件同時成立でのみ発火。

## 対象銘柄
- BTC相関 < 0.5 の低相関銘柄
- アルファ > 3%（BTC比）
- 具体例（2026-02-24〜03-09の2週間データに基づく）:
  - JTO: 相関 0.17, BTC独立性最高
  - TAO: max alpha 6.41%, AIセクターリーダー
  - JUP: 相関 0.85だが alpha 5.85%

## エントリー・エグジット
- エントリー: 条件成立後即時、レバレッジ3倍
- TP: +6-10%（アルファ逆転で利確）
- SL: -3%（聖域価格下）
- ポジションサイズ: 資金の30%（レバ3倍で実質90%）

## 過去実績
- 2025年: Fear < 10 は6日発生
- 2026年1-3月: 10日以上発生（Extreme Fear継続期）
- 推定勝率: 80%超（⚠️ alpha_logic.txt推定値、正式バックテスト要）

## リスク
- 偽陽性（Fearが更に下がり続ける場合）
- 流動性枯渇時のスリッページ
- 「⚠️ 2026-02-24〜03-09の2週間データに基づく。サンプル数が限定的」

## 元テキスト引用
「JTOのような低相関銘柄（相関0.17）がBTC下落耐性を示し、最大アルファ6.4%超を記録」- alpha_logic.txt
「Bot実装では、相関<0.5かつアルファ>3%の乖離シグナルを基準にすれば、ダマシを抑えた高エッジ戦略が構築可能」- alpha_logic.txt
