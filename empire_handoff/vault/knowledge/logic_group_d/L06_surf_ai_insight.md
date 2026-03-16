---
logic_id: L06
category: tier3_commentary
tags: [ai_commentary, onchain, fundamental, gap_analysis, revenue, tvl]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [external_api, onchain]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L06: Surf AI Insight（テクニカル x ファンダギャップ分析）

## 概要
テクニカル指標とファンダメンタルズの乖離をAIが分析し、隠れた投資機会やリスクを文章化する。
Pythonが計算した確定事実（Revenue/TVL/クジラflow等）をAIに渡し、ギャップの解説を生成させる。
Iron Rule #1に基づき、AIはFact Blockの解説のみを行う。

## 定義・目的
テクニカル的に売られすぎ（安値圏）なのにファンダメンタルズが改善中の銘柄、またはテクニカル的に過熱なのにファンダが悪化中の銘柄を検出する。Pythonが計算した確定事実をAIに渡し、ギャップの解説を生成させる。

## 判定ロジック
- **ポジティブギャップ**: テクニカル弱（価格下落）+ ファンダ改善（Revenue増/TVL増/クジラ蓄積） → 買い候補
- **ネガティブギャップ**: テクニカル強（価格上昇）+ ファンダ悪化（Revenue減/TVL減/クジラ売却） → 売り候補
- AIはFact Blockに基づきギャップの解説のみを行う（Iron Rule #1厳守）

## データ要件
- **Revenue/Fees**: Token Terminal API or DefiLlama `/fees`
- **TVL**: DefiLlama `/tvl`
- **クジラflow**: オンチェーン分析（Dune/Nansen等）
- **更新頻度**: 日次
- **MEXC互換性**: 不可（外部API/オンチェーン）

## データプロキシ
- Revenue: DefiLlama `/fees` エンドポイント
- TVL: DefiLlama `/tvl` エンドポイント
- クジラflow: 取引所の大口取引データ（CCXT trades → 大口フィルター）で間接推定

## 実装ヒント
- Tier 2通過銘柄のみ対象（5-20銘柄）
- Pythonでテクニカル指標（RSI/MA乖離率等）とファンダ指標（Revenue変化率/TVL変化率等）を計算
- 両方のスコアをFact Blockとしてまとめ、AIプロンプトに渡す
- AIの出力は「ギャップ解説文」のみ。スコアや判定はPython側で実施
- Tier: 3
- 計算コスト: 中量（外部API + AI呼び出し）

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L20（NPS: ネットワーク生産性）のデータを参照
- **矛盾・注意点**: AIの出力を鵜呑みにしない。数値判断はPythonのみ（Iron Rule #1）。⚠️ Iron Rule #1 と矛盾の可能性: AIの解説が事実上のスクリーニング機能を持たないよう注意

## 元テキスト引用
「L06. Surf AI Insight: テクニカルとファンダメンタルのギャップ分析。」（gemini_crypto）

「Surf AI 深掘り分析: オンチェーンインサイト。Revenue/TVL/クジラflow解読」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: Tier 3のコメンタリーとして最終判断の参考材料（スクリーニング判断はPython）
- **エントリー**: ポジティブギャップ（テクニカル弱+ファンダ強）→ 逆張りエントリーの参考
- **エグジット**: ネガティブギャップ（テクニカル強+ファンダ弱）→ 利確検討の参考
- **スイング（数日〜数週間）**: ファンダ改善トレンドの確認でスイング保有継続判断
- **短期利確（10%+）**: テクニカル過熱+ファンダ未改善なら短期利確

## 注意事項
- ⚠️ AIの出力は参考情報であり、トレード判断のSource of Truthではない（Iron Rule #1）
- ⚠️ Revenue/TVLデータは外部API依存であり、データ欠損時はIron Rule #3に従いNone扱い
