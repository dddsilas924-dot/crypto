---
source_file: mew/12.txt
category: risk_management
tags: [CPI, event, time_window]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [none]
priority: medium
created: 2026-03-10
---

# L12: イベントリスク

## 概要
CPI発表・Pi Day・NYクローズ等の既知イベント前後でポジションを自動制御する。
イベントリスク回避はL13最終判定の最優先VETOとして機能。
週末は全ポジション停止。

## 核心内容
- **CPI発表**: 前2hで全クローズ / 後4hで再開
- **Pi Day**: ±2h停止
- **NYクローズ**: ±1h停止
- **週末**: 全停止
- **優先順位**: L13最終判定で最優先VETO（優先順位1位）

## トレードロジックへの変換
- イベントカレンダーを事前定義（CPI日程は月次更新）
- 時間ウィンドウ判定で自動クローズ/再開
- スケジューラーベースの実装

## 既存システムとの統合ポイント
- L13最終判定の最優先VETO（L12イベント > L10スリッページ > L08死FR）
- 全Botの上位レイヤーとして機能
- 既存のスケジューラー/cronと統合

## 実装に必要なデータ・API
- イベントカレンダー（手動管理 or investing.com API）
- タイムゾーン管理（UTC/EST/JST）
- 外部データ依存なし（スケジュールベース）

## 元テキスト重要引用
- 「CPI前2h全クローズ/後4h再開」
- 「Pi Day±2h停止」
- 「NYクローズ±1h停止」
- 「週末全停止」
