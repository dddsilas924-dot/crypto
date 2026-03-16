---
logic_id: operation_flow
category: execution
tags: [pipeline, cron, tier1, tier2, tier3, notification, telegram, discord]
source: multiple
tier: na
group: execution
implementable: true
data_dependency: [ccxt_ohlcv, ccxt_ticker, ccxt_orderbook, ccxt_funding, external_api]
priority: critical
exchange: MEXC
backtest_possible: false
---

# 運用フロー（パイプライン実行順序）

## 概要
毎時実行のパイプラインで870銘柄をスキャンし、Tier 1→2→3のファンネルで最終候補を抽出・通知する。
実行順序: Group A → Truth Rules → Tier 1 → Tier 2 → Tier 3 → Target Selection → 通知。
急変検知（L09）は毎分の別チャネルで並行実行する。

## 定義・目的
システム全体の実行フローを定義する。各ステップの実行順序、データの受け渡し、通知の仕組みを規定。

## 判定ロジック
### 実行パイプライン

```
1. 環境認識（Group A: L01 + L18）
   - ドミナンス・マトリクスでパターン判定
   - パターンC → 全ポジションクローズ指示 → 終了
   - パターンA/E → 新規エントリー停止 → 既存ポジション管理のみ

2. 鉄則チェック（truth_rules）
   - 200MA/5MA確認
   - 5MA割れポジション → 即クローズ指示

3. Tier 1 スクリーニング（Group B: L02, L03, L04, L09, L17）
   - 870銘柄 → 20-50銘柄に絞り込み
   - L02聖域割れ → 即除外
   - 残銘柄にL03/L04/L09/L17スコア付与

4. Tier 2 検証（Group C: L08, L10, L13, L14）
   - 20-50銘柄 → 5-20銘柄に絞り込み
   - L10 VETO → 即除外
   - L08 FR/OI + L13 LCEF でリスク評価

5. Tier 3 AI Commentary（Group D: L06, L07, L12, L15-L16, L19-L21）
   - 5-20銘柄のFact Block生成
   - AI解説文生成

6. ターゲット選定（target_selection）
   - 統合スコアで最終ランキング
   - 上位銘柄をエントリー候補に

7. 通知（Telegram/Discord）
   - 聖域乖離率、需給状態、AIコメント
   - エントリー/エグジットシグナル
```

### 実行頻度
- **毎時**: パイプライン全体（Tier 1-3）
- **毎分**: 急変検知（L09）、価格アラート
- **日次**: MA計算更新、バリュエーション指標更新

## データ要件
- 全Tierのデータ要件を統合（各ロジック参照）
- **更新頻度**: 毎時（メインパイプライン）
- **MEXC互換性**: 部分的（外部API併用）

## データプロキシ
各ロジックのデータプロキシ参照

## 実装ヒント
- Python asyncioで並列処理（Tier 1の各ロジックは並列実行可能）
- Tier間のデータ受け渡しはPydanticモデルで型安全に
- 各Tier完了後にログ出力（通過銘柄数、処理時間）
- エラー時はtenacity + pybreakerでリトライ/サーキットブレーカー
- 計算コスト: 全体で中量（Tier 1: 軽量、Tier 2: 中量、Tier 3: 中量）

## 他ロジックとの関係
- **依存するロジック**: 全21ロジック + Iron Rules + Truth Rules
- **連携するロジック**: 通知システム（notifier）
- **矛盾・注意点**: 実行順序は厳守。Group A → Truth Rules → Tier 1 → Tier 2 → Tier 3 → Target Selection → 通知

## 元テキスト引用
「毎時実行 (Cron/Loop): Pythonスクリプトが全銘柄をスキャン。」（gemini_crypto）

「Tier 1 Filter: 10/10安値を割っている銘柄を即時破棄。」（gemini_crypto）

「Tier 2 Check: 残った銘柄の板・OIを確認。板スカスカ銘柄を破棄。」（gemini_crypto）

「Tier 3 Analysis: 生き残った数銘柄（本命）について、AIがレポートを作成。」（gemini_crypto）

「Notification: Telegram/Discord に「聖域乖離率」「需給状態」「AIコメント」を通知。」（gemini_crypto）

「監視サイクル: 1時間定点観測（現象捕捉+リスク先行+実需質評価）。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: パイプライン全体がスクリーニングプロセス
- **エントリー**: パイプライン最終出力のターゲットリストからエントリー
- **エグジット**: 毎時パイプラインで保有銘柄の状態を継続監視
- **スイング（数日〜数週間）**: 日次サマリーでスイング判断
- **短期利確（10%+）**: 毎分の急変検知（L09）で短期機会を捕捉

## 注意事項
- ⚠️ パイプラインの実行順序は厳守。順序変更はシステム全体の整合性に影響
- ⚠️ 870銘柄の全数スキャンはAPI Rate Limitに注意。バッチ処理とキャッシュの活用が必須
