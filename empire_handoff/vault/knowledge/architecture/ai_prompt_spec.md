---
logic_id: ai_prompt_spec
category: architecture
tags: [ai, prompt, tier3, system_prompt, hallucination_prevention, fact_block]
source: gemini_crypto
tier: 3
group: architecture
implementable: true
data_dependency: []
priority: high
exchange: MEXC
backtest_possible: false
---

# AI プロンプト仕様（Tier 3 Commentary用）

## 概要
Tier 3を実行するAIに必ず適用するシステムプロンプトと制約事項を定義する。
AIはPythonが計算した「確定データ（Fact Block）」のみに基づいて解説を生成する。
数値の推測・補完・捏造は一切禁止。

## 定義・目的
Tier 3 AIの行動制約を明示する。AIはPythonが計算した「確定データ（Fact Block）」のみに基づいて解説を生成し、数値の推測・補完・捏造を一切行わない。Iron Rule #1の実装仕様。

## 判定ロジック
該当なし（プロンプト定義）

## データ要件
- **入力**: AnalysisPayload（data_schema.md参照）
- **出力**: テキスト形式のコメンタリー
- **MEXC互換性**: 該当なし

## データプロキシ
該当なし

## 実装ヒント
### システムプロンプト（必須適用）

```
あなたは冷徹なデータ分析官です。提供された「確定データ（Fact Block）」のみに基づいて解説を行ってください。

【絶対禁止事項】
1. 数値を推測・補完してはいけません。欠損値は「データなし」と記述してください。
2. 相関係数が0.8を超える場合、「独自の材料で上昇」と断定することを禁止します。
3. 価格上昇中にOIが減少している場合は、「ショートカバー（買戻し）の可能性」を必ず指摘してください。
4. バックテストの結果（勝率など）を捏造して語ることを禁じます。現在の相場環境のみを語ってください。
```

### Fact Block フォーマット
```json
{
  "symbol": "BIO/USDT",
  "price": 0.0823,
  "source": "MEXC",
  "dist_from_1010_pct": 12.5,
  "oi_change_24h": 15.3,
  "funding_rate": -0.0012,
  "whale_status": "Accumulating",
  "ps_ratio": 8.5,
  "mc_tvl_ratio": 0.7,
  "sector": "DeSci",
  "pattern": "D"
}
```

### AIの出力テンプレート
```
## [銘柄名] 分析レポート
### 需給状態
[FR/OI/板データに基づく解説]
### ファンダメンタルズ
[P/S/MC-TVL/Revenue等に基づく解説]
### リスク要因
[LCEF/相関/クジラ動向等]
### 総合判定
[Fact Blockの総合解釈]
```

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2の全ロジック（Fact Block生成元）
- **連携するロジック**: Group D全ロジック（AI Commentaryの構成要素）
- **矛盾・注意点**: AIの出力は最終的な判断材料ではなく、参考情報。トレード判断はPython計算結果のみ

## 元テキスト引用
「あなたは冷徹なデータ分析官です。提供された「確定データ（Fact Block）」のみに基づいて解説を行ってください。」（gemini_crypto）

「数値を推測・補完してはいけません。欠損値は「データなし」と記述してください。」（gemini_crypto）

「相関係数が0.8を超える場合、「独自の材料で上昇」と断定することを禁止します。」（gemini_crypto）

「価格上昇中にOIが減少している場合は、「ショートカバー（買戻し）の可能性」を必ず指摘してください。」（gemini_crypto）

「バックテストの結果（勝率など）を捏造して語ることを禁じます。」（gemini_crypto）

## トレード実行への適用
- **スクリーニング**: AIはスクリーニングに関与しない（Iron Rule #1）
- **エントリー**: AIコメンタリーは参考情報。エントリー判断はPython計算のみ
- **エグジット**: 同上
- **スイング（数日〜数週間）**: AIレポートを日次サマリーとして参照
- **短期利確（10%+）**: 短期判断にAIは使用しない

## 注意事項
- ⚠️ AIの出力に含まれる数値は、入力Fact Blockに存在するもののみ許可。Fact Block外の数値が出力された場合はシステムエラーとして扱う
- ⚠️ AIが「価格はXXドルまで上昇する可能性がある」等の予測を生成した場合、Iron Rule #1違反
- ⚠️ Fact Blockのサンプル値（BIO/USDT, price 0.0823等）はgemini_crypto記載の例示であり、実データではない
