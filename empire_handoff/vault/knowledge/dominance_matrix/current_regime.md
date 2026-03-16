---
logic_id: current_regime
category: market_regime
tags: [regime, pattern_d, current_state, snapshot]
source: multiple
tier: meta
group: iron_rule
implementable: false
data_dependency: [ccxt_ticker, external_api]
priority: high
exchange: MEXC
backtest_possible: false
---

# 現在のレジーム判定

## 概要
ドミナンス・マトリクスの現在地を記録・更新するためのファイル。
実装時はシステムが自動判定する。
現在はパターンD（本質Alpha）と判定されている。

## 定義・目的
市場レジームの現在地とその根拠を記録する。手動更新から自動判定への移行を想定。ソーステキスト記載時点のスナップショットであり、リアルタイム判断にはAPI経由の自動判定が必要。

## 判定ロジック
### 最終判定（surf_crypto由来: 2026-03-08時点）
- **現在パターン: D（本質Alpha）**
- BTC: 弱下落
- BTC.D: 57.8%低下傾向
- Total MC: $2.8T維持

### alpha_logic.txt由来の補完情報（2026-03-09時点）
- BTC Dom: 約50%（BTC時価総額1.38T / 総市場≈2.8T）
- Fear & Greed Index: 7（Extreme Fear）
- Altcoin Season Index: 33（BTC優位継続も低下傾向）
- BTC価格: $66,210（直近1h）

### 警戒シナリオ
- パターンC移行警戒: ドミナンスが反転上昇（↑）した場合、即全切り
- Fear & Greed = 7 は過去データで底打ち反発の買い場パターン

## データ要件
- **BTC/USDT価格推移**: ccxt_ticker
- **BTC.D推移**: CoinGecko `/global` or TradingView
- **Total Market Cap推移**: CoinGecko `/global`
- **更新頻度**: 1時間ごと（自動判定時）
- **MEXC互換性**: 部分的（BTC価格のみ直接取得可）

## データプロキシ
six_patterns.md 参照

## 実装ヒント
- 初期実装では手動更新（このファイルを編集）
- 将来的にはsix_patterns.mdのロジックで自動判定し、結果をDBに保存
- Fear & Greed Index: Alternative.me無料APIで取得可能
- Altcoin Season Index: blockchaincenter.netから取得
- 計算コスト: 軽量

## 他ロジックとの関係
- **依存するロジック**: six_patterns（パターン定義）
- **連携するロジック**: 全ロジック（現在パターンに基づく執行判定）
- **矛盾・注意点**: このファイルの情報はスナップショット。実運用時はリアルタイム判定に置き換え

## 元テキスト引用
「2026-03-08時点BTC弱下落+ドミナンス57.8%低下+Total $2.8T維持」（surf_crypto）

「パターンC移行警戒（ドミナンス反転↑）で即全切り。」（surf_crypto）

「BTCドミナンス: 約50%（BTC時価総額1.38Tドル / 総市場≈2.8Tドル）。」（alpha_logic）

「Fear & Greed Index: 7（Extreme Fear）、7日トレンド下落中。過去データでこの水準は底打ち反発の買い場。」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: パターンD継続中 = Alpha陽転銘柄への先行買い許可
- **エントリー**: パターンD + Fear極限 = 反発買いの好機形成中
- **エグジット**: パターンC移行 = 全ポジション即時クローズ
- **スイング（数日〜数週間）**: パターンD→B移行を待ちつつスイング保有
- **短期利確（10%+）**: パターンD中の急騰は短期利確（パターン維持不確実のため）

## 注意事項
- ⚠️ Total MC "$2.8T"、BTC.D "57.8%" 等の数値はsurf_crypto記載時点（2026-03-08）のスナップショット。現在値はAPI経由で確認が必要
- ⚠️ alpha_logicのBTC Dom "約50%" とsurf_cryptoの "57.8%" に差異あり。⚠️ ソース間で見解が異なる（記載時点の違いによる可能性）
- ⚠️ Fear & Greed Index = 7 は alpha_logic記載時点（2026-03-09）の値
