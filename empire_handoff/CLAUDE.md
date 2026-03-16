# CLAUDE.md - Empire Monitor (Crypto Trading System)

## プロジェクト概要
仮想通貨870銘柄のリアルタイム監視・自動売買システム。
MEXC先物を主要取引所とし、21ロジックによるTier 1→2→3のファンネル構造で銘柄選抜。

## Git
- リモート: (REDACTED)
- ブランチ: main

## シェルコマンドルール
- PowerShell環境（Windows）
- UTF-8前提
- pythonコマンドでPython実行

## ナレッジ参照ルール
### 参照パス
vault/knowledge/ 配下に、トレード知識をテーマ別に格納。

### 参照手順
1. ロジック改良時は、まず vault/knowledge/_INDEX.md を読む
2. _INDEX.md のロジック一覧から、作業対象に関連するナレッジファイルを特定する
3. 関連ナレッジファイルを読み、原則を理解した上でロジックを設計する

### Iron Rules（絶対遵守）
1. AIはTier 3コメンタリーのみ。価格判定・計算にAIを関与させない
2. 数値データはCCXT（MEXC API）経由の生値のみをSource of Truthとする
3. データ欠損はNone。推測値で埋めない
4. Tier 1→2→3のファンネル構造を厳守

## 取引所
- 主要: MEXC（先物 Perpetual Futures）
- 将来: Binance, Bybit, PerpDEX

## テスト
- pytest でユニットテスト
- scripts/test_system.py で統合テスト（Telegram送信含む）
