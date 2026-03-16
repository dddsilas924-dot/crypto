---
logic_id: iron_rule_03
category: iron_rule
tags: [data_integrity, missing_data, none, hallucination_prevention, safety]
source: gemini_crypto
tier: meta
group: iron_rule
implementable: true
data_dependency: []
priority: critical
exchange: MEXC
backtest_possible: false
---

# データ欠損ルール（Iron Rule #3）

## 概要
APIからデータが取れない場合は「欠損（None）」として扱う。
決して推測値で埋めてはならない。
欠損データに基づく判定は「不明」とし、スコアリングから除外する。

## 定義・目的
データ欠損時の安全な処理を定義する。AIや補間アルゴリズムによるデータ補完は、幻覚（Hallucination）の温床となる。データが取得できない場合は明示的にNoneとし、そのフィールドに依存するロジック判定をスキップする。「分からない」を正直に扱うことで、偽シグナルの発生を防止する。

## 判定ロジック
- APIレスポンスがエラー or タイムアウト → 該当フィールドを `None` に設定
- データが取得できたが明らかに異常値（例: 価格0、出来高マイナス） → `None`
- `None` フィールドに依存するロジックは判定をスキップ（スコア0ではなく「判定不能」）
- 複数フィールドが `None` の銘柄は、Tier 1通過後もTier 2で「データ不足」フラグ付与
- AI（Tier 3）に渡すFact Blockで `None` の項目は「データなし」と明記
- 時系列データの中間欠損は線形補間禁止。欠損区間はギャップとして保持
- 欠損率が閾値を超えた場合はシステムアラート

## データ要件
- **CCXT APIエンドポイント**: 全エンドポイント共通ルール
- **更新頻度**: 不変（システム設計レベル）
- **MEXC互換性**: 該当なし（ルール定義）

## データプロキシ
- 欠損データのプロキシ代替は許可されるが、プロキシ使用時は `data_source: "proxy"` を明記
- プロキシ自体が欠損の場合はNone（二重補完禁止）

## 実装ヒント
- Pydanticモデルで `Optional[float]` を活用し、None許容フィールドを明示
- Pydanticバリデーターで異常値をNoneに変換
- ロジック関数は入力がNoneの場合に `None` を返す（NaN伝播パターン）
- pandas: NaNの伝播を利用し、欠損銘柄を自然に除外
- ログにデータ欠損率と欠損理由（timeout / error / anomaly）を記録
- Tier 3 AIプロンプトに「欠損値は『データなし』と記述してください」を含める

```python
# 実装例
class AnalysisPayload(BaseModel):
    oi_change_24h: Optional[float] = None  # None = 取得失敗
    funding_rate: Optional[float] = None
    whale_status: Optional[str] = None     # "Unknown" ではなく None
```

## 他ロジックとの関係
- **依存するロジック**: なし（最上位ルール）
- **連携するロジック**: 全21ロジック（欠損処理の統一基準）
- **矛盾・注意点**: L14（CVM）等のオンチェーンデータは欠損が多い想定。欠損=除外ではなく欠損=スキップとし、他ロジックのスコアで判定

## 元テキスト引用
「APIからデータが取れない場合は「欠損（None）」として扱い、決して推測値で埋めてはならない。」（gemini_crypto）

「数値を推測・補完してはいけません。欠損値は「データなし」と記述してください。」（gemini_crypto / AI System Prompt）

「データ不足（具体バックテストなし）を定性的フレームに変換し、プロキシ（holders/TVL/revenue/DAU）で実用化。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: データ欠損銘柄はスクリーニングスコアを「判定不能」とし、除外ではなくフラグ付与
- **エントリー**: 必須データ（価格）が欠損している銘柄にはエントリー禁止。FR/OIが欠損でもエントリー可だが「検証不完全」注記
- **エグジット**: ポジション保有中にデータ欠損が発生した場合は警告（即エグジットではない）
- **スイング（数日〜数週間）**: 日次データの欠損が3日以上続く場合は手動介入
- **短期利確（10%+）**: リアルタイム価格が取得できない場合は利確判定をスキップ

## 注意事項
- ⚠️ 「Unknown」と「None」は異なる。Unknown = データ取得成功だが判定不能、None = データ取得失敗
- ⚠️ 推測値での補完はIron Rule違反。前回値のキャリーフォワードも推測に含まれる（明示的にstaleフラグが必要）
