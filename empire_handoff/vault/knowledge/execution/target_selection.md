---
logic_id: target_selection
category: execution
tags: [target, screening, valuation, alpha, deflation, sector, bio, pi, uni, ondo, ldo]
source: surf_crypto
tier: na
group: execution
implementable: true
data_dependency: [ccxt_ohlcv, ccxt_ticker, external_api]
priority: high
exchange: MEXC
backtest_possible: partial
---

# ターゲット銘柄の選定基準

## 概要
テクニカル聖域 + 実需バリュエーション + Alpha定義 + デフレ加速の4軸で銘柄を選定する。
パターンD ∩ Alpha陽転 ∩ 鉄則適合 ∩ 21項目低リスク = エントリー。
レバ2-3x、SL髭下が基本パラメータ。

## 定義・目的
21ロジックのスクリーニング結果から、最終的なエントリー候補を絞り込むための統合基準。定量的（P/S、MC/TVL）と定性的（Alpha、デフレ）の両面で評価する。

## 判定ロジック
### テクニカル聖域
- 2025/10/10髭下サポートを背負った位置（L02参照）
- 10/1ターゲットへの回帰ポテンシャル（BIO +450%例）

### 実需バリュエーション
- P/S < 20x（収益に対して割安）
- MC/TVL < 1x（TVLに対して時価総額が低い）

### Alpha定義
- BTC下落（Fear & Greed低位）時に対BTC騰落 > 0 を維持 = 真の強者

### デフレ加速
- バーン/供給破壊の実績（UNI daily burn proxy等）
- 循環供給量の減少トレンド

### カテゴリ優先順位
1. RWA（ONDO等）
2. DeSci/AI（BIO等）
3. DeFi（UNI/LDO等）
4. イベント（PI等）

### 統合選定フロー
パターンD ∩ Alpha陽転 ∩ 鉄則適合 ∩ 21項目低リスク = エントリー（レバ2-3x、SL髭下）

## データ要件
- **P/S**: Token Terminal or DefiLlama（Revenue + Market Cap）
- **MC/TVL**: DefiLlama（TVL + Market Cap）
- **Fear & Greed Index**: Alternative.me API
- **対BTC騰落率**: ccxt_ohlcv
- **循環供給量**: CoinGecko API
- **MEXC互換性**: 部分的

## データプロキシ
- P/S計算困難な銘柄: DefiLlama fees APIでRevenue推定
- Fear & Greed: Alternative.me無料API

## 実装ヒント
- 各基準のスコアを正規化（0-100）してウェイト付き統合
- カテゴリ優先順位はボーナス加点として実装
- 最終候補リストは10-20銘柄を上限
- Tier: na（Tier 1-3統合結果の最終判定）
- 計算コスト: 軽量（各ロジックの結果を統合するだけ）

## 他ロジックとの関係
- **依存するロジック**: L02, L08, L10, L13, L17, L20（各ロジックのスコア結果）
- **連携するロジック**: truth_rules（鉄則適合確認）、six_patterns（パターンD確認）
- **矛盾・注意点**: バリュエーション指標はDeFiプロトコル向け。ミームコインには適用困難

## 元テキスト引用
「テクニカル聖域: 2025/10/10髭下サポート背負い、10/1ターゲット回帰（BIO+450%例）。」（surf_crypto）

「実需バリュエーション: P/S<20x（収益割安）、MC/TVL<1x（TVL優位）。」（surf_crypto）

「Alpha定義: BTC下落（Fear13）で対BTC騰落>0維持=真強者。」（surf_crypto）

「選定フロー: パターンD∩Alpha陽転∩鉄則適合∩21項目低リスク=エントリー（レバ2-3x、SL髭下）。」（surf_crypto）

「ターゲット例: BIO（DeSci/10/10髭下）、PI（イベント/Pi Day）、UNI（DeFi/バーン加速）、ONDO（RWA）、LDO（P/S低位）。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: 統合スコアでランキングし上位銘柄を選定
- **エントリー**: 4軸すべてを満たす銘柄のみエントリー
- **エグジット**: Alpha消失（対BTC騰落 < 0 に転落）→ ポジション再評価
- **スイング（数日〜数週間）**: パターンD継続 + Alpha維持 → スイング保有
- **短期利確（10%+）**: 聖域反発から10%+上昇で短期利確

## 注意事項
- ⚠️ ターゲット銘柄（BIO, PI, UNI, ONDO, LDO）はsurf_crypto記載時点（2026-03-09）の候補。市場環境変化により更新が必要
- ⚠️ BIO +450% はsurf_crypto記載の過去実績であり、将来のリターンを保証しない
- ⚠️ Fear & Greed "13" はsurf_crypto記載時点の値（alpha_logicでは "7"）。⚠️ ソース間で見解が異なる（記載時点の違い）
