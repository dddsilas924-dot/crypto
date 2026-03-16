---
logic_id: bot_surge
category: strategy
tags: [divergence, sector_rotation, daily_cycle, swing]
source: alpha_logic
tier: meta
group: strategy
implementable: true
data_dependency: [ccxt_ohlcv, ccxt_ticker, fear_greed_api]
priority: high
exchange: MEXC
backtest_possible: true
---

# Bot-Surge: 日常循環モード

## 概要
Fear 25-45の通常相場で月2-3回エントリーする循環モード。
セクター内のリーダー→フォロワー波及パターンを検知し、出遅れ銘柄にエントリー。
alpha_logic.txt のセクターラグ分析に基づく。

## 定義・目的
BTC乖離（対BTC騰落率差 > 3%）を検知し、セクター内の波及タイミングを活用。SOL→JUP（ラグ2日）、SOL→JTO（ラグ4.75日）の循環パターンが実証されている（2026-02-24〜03-09の2週間データに基づく）。

## 発動条件
1. Fear & Greed: 25-45（通常恐怖域）
2. BTC日次リターン ≤ 0%
3. 対象銘柄のBTC乖離 > 3%

## セクター波及ロジック
| セクター | リーダー | フォロワー | ラグ（日） |
|---------|---------|-----------|-----------|
| Solana | SOL | JUP | 2.0 |
| Solana | SOL | JTO | 4.75 |
| AI | TAO | FIL, AR | 1.5-2.0 |
| BTCeco | PUPS | ORDI, DOG | 0.5-1.0 |
| RWA | ONDO | MANTRA | 3.0 |
| GameFi | FLOKI | PENGU | 1.0 |

## エントリー・エグジット
- エントリー: 乖離検知後、ラグ日数経過の出遅れ銘柄にエントリー、レバ2-3倍
- TP: +3-5%（スイング）/ +10%（延長保有）
- SL: -2%（アルファ逆転）
- ポジション: 資金の20%（レバ2倍で実質40%）

## 追加フィルタ
- 先物流動性上位
- RSI > 50
- MCap参考

## 元テキスト引用
「Solanaエコ: SOL/JUPラグ2日、SOL/JTO 4.75日」- alpha_logic.txt
「出遅れJTO狙いが有効」- alpha_logic.txt
「TAO max alpha 6.41%、Mindshareトップ」- alpha_logic.txt

## 注意事項
⚠️ ラグ日数は2026-02-24〜03-09の2週間データに基づく。市場環境変化で変動する可能性あり。
⚠️ BTCeco/RWA/GameFiのラグ値は推定。alpha_logic.txtで直接検証されたのはSolana/AIセクターのみ。
