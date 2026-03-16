---
logic_id: system_design
category: architecture
tags: [architecture, directory, pipeline, ccxt, pydantic, asyncio]
source: multiple
tier: na
group: architecture
implementable: true
data_dependency: []
priority: high
exchange: MEXC
backtest_possible: false
---

# システム設計

## 概要
Tier構造ベースの870銘柄監視システム "Empire Monitor"。
CCXT + Pydantic + asyncioで構築し、テンプレート駆動型設計を採用する。
Iron Rulesをシステム全体に横断的に適用する。

## 定義・目的
Empire Monitorシステム全体のアーキテクチャを定義する。テンプレート駆動型設計を維持し、ロジック追加時にPythonコード変更を最小化する。AI幻覚防止をアーキテクチャレベルで保証する。

## 判定ロジック
該当なし（設計ドキュメント）

## データ要件
該当なし（設計ドキュメント）

## データプロキシ
該当なし

## 実装ヒント
### ディレクトリ構成
```
trading_engine/
├── main.py                     # エントリーポイント（毎時cron）
├── core/
│   ├── config_loader.py        # active_config.yaml 読込
│   ├── logic_parser.py         # .md → YAML → dict
│   ├── condition_eval.py       # 条件ツリー再帰評価
│   └── indicator_map.py        # インジケーター関数マッピング
├── pipeline/
│   ├── regime_detector.py      # Group A: L01 + L18（環境認識）
│   ├── tier1_engine.py         # Group B: L02, L03, L09, L17
│   ├── tier2_engine.py         # Group C: L08, L10, L13
│   └── tier3_commentary.py     # Group D: AI Commentary
├── execution/
│   ├── order_executor.py       # MEXC API 発注（CCXT経由）
│   ├── failsafe.py             # フェイルセーフ
│   └── position_tracker.py     # ポジション状態管理
├── data/
│   ├── data_fetcher.py         # CCXT統合データ取得
│   ├── data_validator.py       # 異常値チェック（Iron Rule #3）
│   └── external_fetcher.py     # 外部API（CoinGecko/DefiLlama等）
├── output/
│   ├── csv_manager.py          # 日次/月次CSV
│   ├── reporter.py             # 日次レポート生成
│   └── notifier.py             # Discord/Telegram通知
└── tests/
```

### gemini_crypto記載のオリジナル構成
```
project_root/
├── config/
│   ├── settings.py          # 閾値設定 (TIER1_THRESHOLD = 20 等)
│   └── asset_master.csv     # 監視対象マスタ (Symbol, 10/10_Low, Sector)
├── src/
│   ├── models/schemas.py    # Pydanticによる厳格な型定義
│   ├── fetchers/            # CCXT (MEXC) 実装
│   ├── signals/
│   │   ├── tier1_engine.py  # L02, L03, L09, L17 実装
│   │   └── tier2_engine.py  # L08, L10, L13 実装
│   ├── ai/
│   │   └── commentary.py    # Tier 3 プロンプトビルダー
│   └── orchestration/       # パイプライン制御
└── logs/                    # 実行ログ
```

### 技術スタック
- **言語**: Python 3.11+
- **取引所API**: ccxt（MEXC Futures）
- **データ検証**: Pydantic v2
- **非同期**: asyncio + aiohttp
- **インジケーター**: pandas + pandas-ta
- **フェイルセーフ**: tenacity + pybreaker
- **通知**: Discord Webhook + Telegram Bot API
- **スケジューラ**: cron / systemd timer
- **AI Commentary**: Claude API（Tier 3のみ）

### 設計原則
1. Iron Rules をシステム全体に横断的に適用
2. Tier構造によるファンネル型フィルタリング
3. Pydanticによる厳格な型定義（AI幻覚防止）
4. テンプレート駆動（ロジック追加でPython変更不要）
5. フェイルセーフ（APIエラー時の安全な停止）

## 他ロジックとの関係
- 全ロジックの実行基盤
- Iron Rules を全レイヤーに適用

## 元テキスト引用
gemini_crypto記載のディレクトリ構成とデータスキーマを参照。

「AIの幻覚を防ぐため、以下のデータ構造を遵守すること。」（gemini_crypto）

## トレード実行への適用
該当なし（設計ドキュメント）

## 注意事項
- ⚠️ gemini_crypto原文では取引所が「Binance/Bybit」だが、本プロジェクトではMEXCに変更。CCXT経由のため影響は限定的
- ⚠️ ディレクトリ構成は2パターン（gemini_crypto版と拡張版）が存在。プロジェクトの進行に応じて選択
