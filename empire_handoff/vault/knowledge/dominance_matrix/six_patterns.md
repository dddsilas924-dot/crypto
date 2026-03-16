---
logic_id: dominance_matrix
category: market_regime
tags: [btc_dominance, total_mc, capital_flow, regime, six_patterns]
source: multiple
tier: meta
group: iron_rule
implementable: true
data_dependency: [ccxt_ticker, external_api]
priority: critical
exchange: MEXC
backtest_possible: partial
---

# ドミナンス・マトリクス 6パターン

## 概要
BTC価格・BTCドミナンス（BTC.D）・Total Market Capの3変数で市場の資金循環パターンを6分類する。
全トレード判断の最上位フィルターとして機能する。
個別銘柄分析の前に、まず「今の海はどちら向きか」を確認する。

## 定義・目的
市場全体の資金の流れ（海流）を数学的に分類し、アルトコインへのエントリー可否を判定する。6パターンの分類により、現在の市場フェーズを客観的に識別し、それぞれに応じた執行判定を行う。

## 判定ロジック

| パターン | BTC価格 | BTC.D | Total MC | 資金の流れ（市場真実） | 執行判定 |
|----------|---------|-------|----------|-------------------------|----------|
| **A: BTC独走** | 上昇 | 上昇 | 上昇 | アルト→BTC吸い上げ | 静観 |
| **B: アルト祭** | 上昇 | 低下 | 上昇 | BTC溢れ→アルト全力 | **全力買い** |
| **C: 全面安** | 下落 | 上昇 | 下落 | アルト→USDT/Fiat逃避 | **全切り** |
| **D: 本質Alpha** | 下落 | 低下 | 横ばい | BTC→特定アルト（聖域） | **先行買い** |
| **E: じわ下げ** | 横ばい | 上昇 | 横ばい | BTC集中、アルト退屈下げ | 静観 |
| **F: アルト循環** | 横ばい | 低下 | 横ばい | BTC利確→アルト短期 | **短期狙い** |

### パターン判定の閾値（定性的）
- 「上昇/下落」: 直近24h〜7d変化率の方向
- 「横ばい」: 変化率が±2%以内（目安）
- BTC.Dの変化方向が最重要シグナル
- パターンC検知時は即時アラート（全ポジションクローズ検討）

## データ要件
- **BTC/USDT価格**: ccxt_ticker（MEXC）
- **BTC.D**: TradingView or CoinGecko API（CCXT直接取得不可）
- **Total Market Cap**: CoinGecko API or TradingView
- **USDT.D**: TradingView（補助指標）
- **更新頻度**: 1時間ごと
- **MEXC互換性**: BTC価格のみ直接取得可。BTC.D/Total MCは外部API必要

## データプロキシ
- BTC.D: CoinGecko `/global` エンドポイント or CCXT全ペアの時価総額比率から計算
- Total MC: CoinGecko `/global` エンドポイント
- USDT.D: USDT時価総額 / Total MC で近似計算

## 実装ヒント
- BTC価格変化率、BTC.D変化率、Total MC変化率の3値を毎時計算
- 3値の方向（上昇/下落/横ばい）の組み合わせでパターン分類
- パターンC検知時は即時アラート（全ポジションクローズ検討）
- パターンD時のみアルトエントリー開始
- Tier: meta（全Tierの前段で実行）
- 計算コスト: 軽量

## 他ロジックとの関係
- **依存するロジック**: なし（最上位レイヤー）
- **連携するロジック**: L01（同一ロジックの詳細版）、全ロジック（環境係数として適用）
- **矛盾・注意点**: パターンCでは他の全ロジックがポジティブでも新規エントリー禁止

## 元テキスト引用
「BTC価格、BTCドミナンス（BTC.D）、Total Market Cap（全体流入）の相関で市場真実を数学的に分類。」（surf_crypto）

「L01. Dominance Matrix: BTC.D / USDT.D / TOTAL3 の推移からリスクオン/オフを判定。」（gemini_crypto）

「現在地: パターンD（本質Alpha）（BTC下落∩ドミナンス低下∩Total維持 = BTC売却→特定アルト先行買い）」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: パターン判定結果を全銘柄スコアの乗数係数に
- **エントリー**: パターンB/D/Fでのみ新規エントリー許可。A/C/Eは静観or全切り
- **エグジット**: パターンC移行検知で全ポジション即時クローズ
- **スイング（数日〜数週間）**: パターンD→Bの移行で利確検討（アルト祭ピーク）
- **短期利確（10%+）**: パターンF（アルト循環）で短期回転狙い

## 注意事項
- ⚠️ gemini_cryptoは「BTC.D/USDT.D/TOTAL3」の3変数、surf_cryptoは「BTC価格/BTC.D/Total MC」の3変数と、若干異なる変数セットを使用。⚠️ ソース間で見解が異なる
- ⚠️ 「横ばい」の閾値（±2%）は目安であり、ソーステキストに厳密な数値定義はない
