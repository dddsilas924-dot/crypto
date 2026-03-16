---
logic_id: iron_rule_02
category: iron_rule
tags: [data_integrity, ccxt, api, source_of_truth, price_data]
source: gemini_crypto
tier: meta
group: iron_rule
implementable: true
data_dependency: [ccxt_ohlcv, ccxt_ticker]
priority: critical
exchange: MEXC
backtest_possible: false
---

# Source of Truth（Iron Rule #2）

## 概要
数値データは必ずCCXT（MEXC API）経由で取得した生の値を正とする。
AIの内部知識やCoinGecko等の遅延データは使用しない。
すべての計算・判定の唯一の入力ソースはAPIの生値である。

## 定義・目的
AIの価格幻覚（Hallucination）事故の根本原因は、AIが内部知識から価格を「推測」したことにある。この再発を防止するため、数値データの唯一の正規ソースをCCXT経由のAPI生値と定義する。CoinGecko等の集約サイトは遅延があるため、Source of Truthとしては使用禁止。

## 判定ロジック
- 全数値データ（価格、出来高、OI、FR等）はCCXT経由でMEXC APIから取得
- 取得元をデータに付記（`source: "MEXC"`）
- 取得時刻（timestamp）を必ず記録
- データ鮮度が7日超の場合は「stale」フラグを付与し手動更新を促す
- CoinGecko、CoinMarketCap等の集約サイトは参考情報としてのみ使用可
- AIの内部知識に基づく数値は一切使用禁止

## データ要件
- **CCXT APIエンドポイント**: `exchange.fetch_ticker()`, `exchange.fetch_ohlcv()`, `exchange.fetch_funding_rate()`, `exchange.fetch_order_book()`
- **更新頻度**: リアルタイム〜1分足（Tier 1）、毎時（Tier 2）
- **MEXC互換性**: CCXT経由で全エンドポイント対応

## データプロキシ
- MEXC APIが一時停止の場合: Binance/Bybit APIをフォールバックとして使用可（ただし `source` フィールドにフォールバック使用を明記）
- オンチェーンデータ: Dune Analytics, TokenTerminal等から取得（APIキー要、`source` フィールドに記録）

## 実装ヒント
- `AnalysisPayload.source` フィールドで取得元を明示（デフォルト: "MEXC"）
- データ取得関数は `src/fetchers/` 配下に集約
- ccxtライブラリでMEXC先物APIを統一的に呼び出し
- 全データ取得関数に `source` 属性と `timestamp` を付与
- データ鮮度チェック（stale > 5分 → 警告）
- API Rate Limitを考慮し、870銘柄のTier 1スキャンはバッチ処理

## 他ロジックとの関係
- **依存するロジック**: なし（最上位ルール）
- **連携するロジック**: 全21ロジック（データ取得の基盤）
- **矛盾・注意点**: L14 CVM（クロスチェーンデータ）はMEXC APIでは取得不可のため、プロキシ（Stablecoin時価総額）で代替。プロキシ使用時も `source` を明記

## 元テキスト引用
「数値データは必ず CCXT (Binance/Bybit API) 経由で取得した生の値を正とする。AIの内部知識やCoinGecko等の遅延データは使用しない。」（gemini_crypto）

「データstale（>7d=手動更新）注記し、プロキシ活用。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: MEXC API生値のみでスコア計算。外部サイトの数値は参考情報に留める
- **エントリー**: エントリー価格はリアルタイムAPI値。遅延データでの判断禁止
- **エグジット**: ストップロス判定もAPI生値ベース
- **スイング（数日〜数週間）**: 日次データもAPI経由で取得し、手動入力を排除
- **短期利確（10%+）**: 1分足リアルタイムデータで利確判定

## 注意事項
- ⚠️ gemini_crypto原文では「CCXT (Binance/Bybit API)」だが、本プロジェクトではMEXC先物を主要取引所とする。Iron Rule #2の精神（API生値のみ）は同一
- ⚠️ CoinGecko、CoinMarketCap等の集約サイトデータは遅延があるため、Source of Truthとしては使用禁止
