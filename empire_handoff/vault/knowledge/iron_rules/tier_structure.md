---
logic_id: iron_rule_04
category: iron_rule
tags: [architecture, tier_structure, funnel, screening]
source: gemini_crypto
tier: meta
group: iron_rule
implementable: true
data_dependency: []
priority: critical
exchange: MEXC
backtest_possible: false
---

# Tier構造の厳守（Iron Rule #4）

## 概要
計算コストとAI幻覚リスクを管理するため、Tier 1→2→3のファンネル構造を維持する。
全870銘柄からTier 1で足切りし、Tier 2で検証、Tier 3でAI解説を付与する。
各Tierの境界を越えた処理の混在は禁止する。

## 定義・目的
870銘柄を一律に深い分析にかけるのは計算コストが膨大であり、AI関与範囲を限定するためにもファンネル構造が必須。上位Tierで大量銘柄を高速に足切りし、下位Tierでは少数の銘柄に対してリッチなデータを用いて精査する。

## 判定ロジック
### Tier 1: 全数スクリーニング（Python軽量計算）
- **対象**: 全870銘柄
- **処理**: 1分足レベルのルールベース判定
- **ロジック**: Group B: L02, L03, L04, L09, L17
- **出力**: 上位選抜銘柄リスト（通過率目安: 約20-50銘柄）
- 軽量計算のみ。API呼び出し最小限

### Tier 2: 需給・健全性検証（Python詳細計算）
- **対象**: Tier 1通過銘柄
- **処理**: デリバティブデータ、板情報等の取得・検証
- **ロジック**: Group C: L08, L10, L13, L14
- **出力**: 最終候補銘柄リスト（通過率目安: 約5-20銘柄）

### Tier 3: AIコメンタリー（AI文章生成）
- **対象**: Tier 2通過銘柄（〜20銘柄）
- **処理**: Fact Blockに基づくAI解説
- **ロジック**: Group D: L06, L07, L12, L15, L16, L19, L20, L21
- **出力**: 銘柄レポート（Telegram/Discord通知）

### Group A（環境認識）
- L01（ドミナンスマトリクス）, L18（GLM）は全Tierに横断的に係数として機能

## データ要件
- **CCXT APIエンドポイント**: Tier依存（Tier 1: ticker/ohlcv、Tier 2: funding_rate/order_book/open_interest）
- **更新頻度**: Tier 1は毎時、Tier 2はTier 1通過後に随時
- **MEXC互換性**: 全Tier対応

## データプロキシ
該当なし（アーキテクチャルール）。

## 実装ヒント
- `src/signals/tier1_engine.py`: L02, L03, L09, L17 実装
- `src/signals/tier2_engine.py`: L08, L10, L13 実装
- `src/ai/commentary.py`: Tier 3プロンプトビルダー
- パイプライン設計: Tier 1 → Tier 2 → Tier 3 の直列実行
- 各Tierの入出力をログに記録（銘柄数の推移を可視化）
- Tier間のデータ受け渡しはPydanticモデルで型安全に
- Tier 1のスコア閾値は `config/settings.py` の `TIER1_THRESHOLD` で管理
- Group A（L01, L18）はTier横断の環境係数として全Tierに適用

## 他ロジックとの関係
- **依存するロジック**: なし（構造定義）
- **連携するロジック**: 全21ロジック（各ロジックはTier 1/2/3のいずれかに所属）
- **矛盾・注意点**: Group Aロジック（L01, L18）はTier構造外の「環境係数」として機能

## 元テキスト引用
「Tier 1: 全870銘柄 → Pythonルールベース（1分足レベル）」（gemini_crypto）

「Tier 2: 上位選抜 → Pythonルールベース（需給・板・オンチェーン検証）」（gemini_crypto）

「Tier 3: 最終候補（〜20銘柄） → AI Commentary（事実データに基づく考察）」（gemini_crypto）

「階層構造: 第1層 (1-5): 現象観測（マクロ/Alpha）。第2層 (6-12): 深掘り/セクター/急変検知。第3層 (13-15): リスク先行。第4層 (16-21): 構造歪み/実需質。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: Tier 1で870銘柄→上位銘柄に絞り込み。聖域割れは即時除外
- **エントリー**: Tier 2通過かつTier 3レポートが出た銘柄のみエントリー候補
- **エグジット**: Tier 2のVETO（板スカスカ）発動で即撤退
- **スイング（数日〜数週間）**: Tier 3コメンタリーで中期保有の根拠を確認（参考情報として）
- **短期利確（10%+）**: Tier 1急変検知（L09）でエントリー→短期利確

## 注意事項
- ⚠️ ソース間で見解が異なる: surf_cryptoの4層構造（第1層〜第4層）とgemini_cryptoの3Tier構造（Tier 1〜3）で分類が異なる。surf_cryptoではL09（急変検知）を第2層、gemini_cryptoではTier 1（Group B）に分類
- ⚠️ Tier 3のAI関与はIron Rule #1に厳密に従うこと
