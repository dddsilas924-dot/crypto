---
logic_id: iron_rule_01
category: iron_rule
tags: [ai_safety, hallucination_prevention, tier_structure, prompt_engineering]
source: gemini_crypto
tier: meta
group: iron_rule
implementable: true
data_dependency: []
priority: critical
exchange: MEXC
backtest_possible: false
---

# AIの役割制限（Iron Rule #1）

## 概要
AIは「Tier 3」の文章生成（解説）のみを担当する。
価格判定、スクリーニング、計算には一切関与させない。
過去のAI価格幻覚（Hallucination）事故を教訓とした絶対制約である。

## 定義・目的
AIが数値データを「推測」「補完」「生成」することを完全に禁止し、Pythonで計算済みの確定データ（Fact Block）に基づくコメンタリーのみを許可するルール。Tier 1/Tier 2は100% Pythonルールベースで処理し、AIの介在余地を排除する。

## 判定ロジック
- **Tier 1（全870銘柄スクリーニング）**: Pythonルールベースのみ。AI関与禁止
- **Tier 2（需給・健全性検証）**: Pythonルールベースのみ。AI関与禁止
- **Tier 3（最終候補〜20銘柄）**: AIがFact Blockに基づきコメンタリーを生成
- AIの出力に含まれる数値は、入力Fact Blockに存在するもののみ許可
- 相関係数が0.8を超える場合、「独自の材料で上昇」と断定することを禁止

## データ要件
- **CCXT APIエンドポイント**: 該当なし（ルール定義のみ）
- **更新頻度**: 不変（システム設計レベル）
- **MEXC互換性**: 該当なし

## データプロキシ
該当なし。ルール定義であり、データ取得は不要。

## 実装ヒント
- AIへの入力は必ず `AnalysisPayload`（Pydanticモデル）で型検証済みのFact Blockのみとする
- AIの出力に数値が含まれる場合、入力Fact Blockとの照合バリデーションを実装
- System Promptに絶対禁止事項を明記（数値推測禁止、欠損は「データなし」記述、バックテスト結果捏造禁止）
- 価格上昇中にOIが減少している場合は「ショートカバーの可能性」を必ず指摘させる
- 計算コスト: 軽量（バリデーションのみ）

## 他ロジックとの関係
- **依存するロジック**: なし（最上位ルール）
- **連携するロジック**: 全21ロジック（特にGroup D: L06, L07, L12, L15, L16, L19, L20, L21）
- **矛盾・注意点**: Group DロジックはすべてこのルールのスコープであるTier 3内で動作する

## 元テキスト引用
「AIは「Tier 3」の文章生成（解説）のみを担当する。価格判定、スクリーニング、計算には一切関与させない。」（gemini_crypto）

「あなたは冷徹なデータ分析官です。提供された「確定データ（Fact Block）」のみに基づいて解説を行ってください。」（gemini_crypto / AI System Prompt）

「数値を推測・補完してはいけません。欠損値は「データなし」と記述してください。」（gemini_crypto / AI System Prompt）

## トレード実行への適用
- **スクリーニング**: 100% Pythonルールベース。AIの推奨に基づくスクリーニング禁止
- **エントリー**: AIの推奨でエントリーしてはならない。Tier 1/2のPython計算結果のみで判断
- **エグジット**: AIのコメントでエグジット判断しない。5MA割れ等のルールベース判断のみ
- **スイング（数日〜数週間）**: 保有中のAIコメンタリーは参考情報のみ。売買判断はPython
- **短期利確（10%+）**: 利確判断はPython計算のみ

## 注意事項
- ⚠️ Iron Rule #1は全ロジックに優先する最上位制約。違反するロジック実装は即却下
- ⚠️ AIが「価格はXXドルまで上昇する可能性がある」等の予測を生成した場合、システムエラーとして処理すること
