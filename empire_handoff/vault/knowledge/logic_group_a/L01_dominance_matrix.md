---
logic_id: L01
category: market_regime
tags: [btc_dominance, usdt_dominance, total3, risk_on_off, regime]
source: multiple
tier: meta
group: A
implementable: true
data_dependency: [ccxt_ticker, external_api]
priority: critical
exchange: MEXC
backtest_possible: partial
---

# L01: Dominance Matrix（ドミナンス・マトリクス）

## 概要
BTC.D / USDT.D / TOTAL3 の推移からリスクオン/オフを判定する。
全銘柄スコアリングの「係数」として機能する最上位ロジック。
6パターン分類により市場全体の資金循環を数学的に分類する。

## 定義・目的
市場全体の資金循環パターンを検知する最上位ロジック。BTC.D（ビットコインドミナンス）、USDT.D（ステーブルコインドミナンス）、TOTAL3（BTC/ETH除くアルト時価総額）の3指標で、資金がどこに流れているかを判定する。全銘柄のスコアリングに対する「係数」として機能し、個別ロジックの前段で環境認識を行う。

## 判定ロジック
- **リスクオン信号**: BTC.D低下 + USDT.D低下 + TOTAL3上昇 → アルトに資金流入
- **リスクオフ信号**: BTC.D上昇 + USDT.D上昇 + TOTAL3下落 → 安全資産へ逃避
- **Alpha検出**: BTC.D低下 + TOTAL3横ばい → 特定アルトのみに資金集中（パターンD）
- 6パターン分類の詳細は dominance_matrix/six_patterns.md 参照
- BTC.D低下開始がTOTAL3上昇のGoサイン

## データ要件
- **BTC.D**: CoinGecko `/global` or TradingView
- **USDT.D**: USDT時価総額 / Total MC
- **TOTAL3**: CoinGecko or TradingView（BTC/ETH除く時価総額）
- **更新頻度**: 1時間ごと
- **MEXC互換性**: 直接は不可。外部API必要

## データプロキシ
- TOTAL3: CCXT全銘柄のticker取得 → BTC/ETH除く時価総額合計を自前計算（計算コスト高）
- 代替: CoinGecko Free APIの `/global` エンドポイント（レート制限注意、30コール/分）
- USDT.D: CoinGeckoでUSDT時価総額取得 → Total MCで除算

## 実装ヒント
- CoinGecko APIで BTC.D, Total MC を取得
- USDT時価総額も同APIから取得
- 24h/7d変化率を計算し、方向（上昇/下落/横ばい）を判定
- パターン分類結果を環境係数（0.0〜1.5）に変換し、全銘柄スコアに乗算
- Tier: meta（Tier 1の前段で実行）
- 計算コスト: 軽量（API 1-2コールのみ）

## 他ロジックとの関係
- **依存するロジック**: なし
- **連携するロジック**: L18（GLM）と組み合わせてマクロ環境を総合判定
- **矛盾・注意点**: gemini_cryptoは「BTC.D/USDT.D/TOTAL3」、surf_cryptoは「BTC価格/BTC.D/Total MC」と若干異なる3変数を使用。⚠️ ソース間で見解が異なる。実装時はsurfの3変数（BTC価格/BTC.D/Total MC）を主軸とし、USDT.D/TOTAL3を補助とする

## 元テキスト引用
「L01. Dominance Matrix: BTC.D / USDT.D / TOTAL3 の推移からリスクオン/オフを判定。」（gemini_crypto）

「BTC価格、BTCドミナンス（BTC.D）、Total Market Cap（全体流入）の相関で市場真実を数学的に分類。」（surf_crypto）

「BTC Dominance ~50%: 安定高水準。低下開始でTOTAL3（アルト時価総額）上昇のGoサイン」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: パターンに応じた環境係数を全銘柄スコアに適用
- **エントリー**: パターンB/D/Fで新規エントリー許可。パターンA/C/Eはエントリー禁止
- **エグジット**: パターンC移行で全ポジションクローズ
- **スイング（数日〜数週間）**: パターンD時に先行買い→Bへの移行で利確
- **短期利確（10%+）**: パターンF時に短期回転

## 注意事項
- ⚠️ BTC.D/TOTAL3はMEXC APIでは直接取得不可。外部API依存のためデータ遅延リスクあり
- ⚠️ パターン分類の閾値（「横ばい」= ±2%等）はソーステキストに厳密な定義なし。運用しながら調整が必要
