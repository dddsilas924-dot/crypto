---
source_file: mew/13.txt
category: strategy
tags: [final_judgment, VETO, SSS]
related_existing_logic: []
new_logic_potential: none
backtest_possible: false
data_dependency: [none]
priority: high
created: 2026-03-10
---

# L13: 最終総合ランク

## 概要
L01-L12の全ロジック判定を集約し、最終的なSSS/EXIT判定を行う。
1つでもZランクがあればVETOでEXIT。全S/A かつ Z無しでSSSランク。
VETO優先順位: L12イベント > L10スリッページ > L08死FR。

## 核心内容
- **SSSランク条件**: 全ロジックがS/A かつ Z無し
- **EXIT条件**: 1つでもZランクがあればVETOで即EXIT
- **VETO優先順位**:
  1. L12: イベントリスク（最優先）
  2. L10: スリッページリスク
  3. L08: 死のFR（+0.05%超）
- **判定フロー**: L12→L10→L08の順でVETOチェック後、残りロジックを集約

## トレードロジックへの変換
- 全L01-L12のランク判定結果を入力として受け取る
- VETO優先順位に従い、最優先VETOから順にチェック
- SSS判定時のみエントリー許可、それ以外は待機またはEXIT

## 既存システムとの統合ポイント
- Tier 3最終判定レイヤーとして全Botの意思決定ゲートウェイ
- 全L01-L12のランク出力を集約するハブ
- Telegramアラートのトリガー

## 実装に必要なデータ・API
- 外部データ依存なし（L01-L12の出力を集約）
- 各ロジックのランク判定結果（内部データフロー）

## 元テキスト重要引用
- 「SSS=全S/A無Z」
- 「EXIT=1つZでVETO」
- 「優先順位: 1.L12イベント>2.L10スリッページ>3.L08死FR」
