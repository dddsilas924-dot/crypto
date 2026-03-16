---
logic_id: L13
category: tier2_validation
tags: [liquidation, cluster, flash_crash, risk, cascade, bio]
source: multiple
tier: 2
group: C
implementable: partial
data_dependency: [ccxt_funding, ccxt_ticker, ccxt_orderbook, external_api]
priority: critical
exchange: MEXC
backtest_possible: false
---

# L13: LCEF（Liquidation Cluster Proximity / 清算クラスター近接度）

## 概要
現在価格直下に清算だまりがあるかを検知し、フラッシュクラッシュリスクを先行察知する。
BIO 3x突然死の教訓から導入された。
連鎖清算（Cascade Liquidation）リスクの事前回避が目的。

## 定義・目的
レバレッジポジションの清算（Liquidation）が特定の価格帯に集中している場合、その価格帯に到達すると連鎖清算が発生し、急激な価格崩壊を引き起こす。この「清算だまり」の位置と規模を把握し、リスクを事前に回避する。

## 判定ロジック
- **高リスク**: 現在価格の-5%以内に大規模清算クラスターが存在 → 警告
- **連鎖リスク**: Liq/OI比が高い + 板の-5%範囲が薄い → 連鎖清算の可能性大 → **除外**
- **安全**: 直下の清算クラスターが遠い or 規模が小さい → 通過
- **ヒゲキャッチ狙い**: 清算クラスター到達後の反発を狙う上級手法（リスク高）

## データ要件
- **清算データ**: 外部API（Coinglass等）。CCXT直接対応なし
- **Open Interest**: ccxt `fetch_open_interest()`
- **板厚（Depth ±5%）**: ccxt `fetch_order_book()`
- **更新頻度**: 毎時
- **MEXC互換性**: OI/板は可。清算クラスターデータは外部API必要

## データプロキシ
- 清算クラスターの直接データ取得困難な場合:
  - Liq/OI比: OI x 平均レバレッジ推定 → 清算価格帯を概算
  - Depth 5%超連鎖: 板の-5%範囲の厚さで間接判定
  - Coinglass無料APIで主要銘柄のLiquidation Heatmapを参考

## 実装ヒント
- Coinglassの清算データAPIを利用（有料プラン推奨）
- 代替: OI x 推定レバレッジ → 清算価格帯を概算
- L10（板の厚さ）の結果と組み合わせ: 板薄 + 清算クラスター近い = 最大リスク
- Tier: 2
- 計算コスト: 中量（外部API依存）

## 他ロジックとの関係
- **依存するロジック**: L10（板の厚さデータを参照）
- **連携するロジック**: L08（OIデータを共有）、L02（聖域と清算クラスターの位置関係）
- **矛盾・注意点**: 清算クラスターデータの精度は外部API依存。データ欠損時はIron Rule #3に従いNone扱い

## 元テキスト引用
「L13. LCEF (Liquidation Cluster): 現在価格直下に清算だまりがあるか（ヒゲキャッチ狙い）。」（gemini_crypto）

「LCEF (清算クラスター近接度): Flash Crash（BIO3x突然死）先行察知。Liq/OI比+Depth5%超連鎖」（surf_crypto）

「Alpha陽転∩LCEF低=買い」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: 連鎖清算リスクの高い銘柄を除外
- **エントリー**: 直下に大規模清算クラスターがない状態でのみエントリー
- **エグジット**: 保有中に直下に清算クラスター形成 → 即撤退
- **スイング（数日〜数週間）**: 日次で清算クラスター位置を確認。SLは清算クラスターの外側に設定
- **短期利確（10%+）**: 清算クラスター到達後の反発は短期利確の好機（ただしリスク高）

## 注意事項
- ⚠️ 清算クラスターデータはCCXT/MEXC APIでは直接取得不可。Coinglass等の外部APIに完全依存
- ⚠️ 「Liq/OI比」「Depth5%超連鎖」の具体的閾値はソーステキストに記載なし。運用しながら設定が必要
- ⚠️ BIO 3x突然死の具体的数値（日時、下落率等）はソーステキストに詳細なし
