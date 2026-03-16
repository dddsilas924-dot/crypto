---
logic_id: L_sector_rotation_lag
category: tier1_screening
tags: [sector_lag, rotation, solana, ai_sector, timing, cascade]
source: alpha_logic
tier: 1
group: B
implementable: partial
data_dependency: [ccxt_ohlcv, ccxt_ticker]
priority: high
exchange: MEXC
backtest_possible: true
---

# L_sector_rotation_lag: セクター内ラグ検知（Sector Rotation Lag Detection）

## 概要
セクター内の先導銘柄→出遅れ銘柄へのラグ（遅延伝播）パターンを検出する。
SOL→JUP 2日、SOL→JTO 4.75日のラグが実証されている。
先導銘柄の動きから出遅れ銘柄のエントリータイミングを予測する。

## 定義・目的
同一セクター（例: Solanaエコシステム、AIセクター）内では、先導銘柄の価格変動がラグをもって後発銘柄に伝播する。このラグを定量化することで、出遅れ銘柄への最適なエントリータイミングを算出する。alpha_logic.txtの分析でSolana/AIセクターのラグパターンが実証されている。

## 判定ロジック
### Solanaエコシステム（2026-02-24〜03-09の2週間データに基づく）
- **SOL→JUP**: ラグ約2日。SOL/JUP比率700ピーク
- **SOL→JTO**: ラグ約4.75日。出遅れJTO狙いが有効
- SOL staking 69%安定、Prop AMMs volume 65-70%シェア奪取

### AIセクター
- **TAO起点**: TAO max alpha 6.41%、Mindshareトップ
- TAO→他AI銘柄への乖離検知で二波目捕捉

### 汎用ラグ検出ロジック
1. セクター内の先導銘柄を特定（変化率の先行性で判定）
2. 先導銘柄の変動から他銘柄への遅延相関を計算
3. ラグ日数を算出（クロス相関のピーク位置）
4. ラグ経過後の出遅れ銘柄にエントリーシグナル

## データ要件
- **セクター内全銘柄の日次OHLCV**: ccxt_ohlcv（MEXC Futures）
- **セクター分類マスタ**: asset_master.csv
- **クロス相関計算用の過去30日データ**
- **更新頻度**: 日次
- **MEXC互換性**: 可（価格データ）

## データプロキシ
- SOL TVL: DefiLlama API（$6.5B、2026-02-09時点）
- SOL Revenue: Dune Analytics（$1-5M安定、Priority 60%）
- Prop AMMs volume: Dune Analytics

## 実装ヒント
- scipy `correlate` or pandas `shift()` でクロス相関を計算
- ラグ日数 = クロス相関が最大になるシフト量
- セクター内の先導/後発を日次で更新
- 先導銘柄が上昇開始 → ラグ日数経過後に出遅れ銘柄アラート
- Tier: 1
- 計算コスト: 中量（セクターごとにクロス相関計算）

## 他ロジックとの関係
- **依存するロジック**: L02（聖域判定通過が前提）、L04（先行指標: L1レベルの動向）
- **連携するロジック**: L_alpha_divergence（乖離検知と組み合わせ）、L21（SDR: セクターローテーション）
- **矛盾・注意点**: ラグ日数は市場環境により変動する。固定値として使用せず、ローリング計算が推奨

## 元テキスト引用
「Solanaエコ: SOL/JUPラグ2日、SOL/JTO4.75日。DuneデータでSOL staking 69%安定、Prop AMMs volume 65-70%シェア奪取。出遅れJTO狙いが有効。」（alpha_logic）

「AIセクタ: TAO max alpha 6.41%、Mindshareトップ。セクター内TAO起点→他AI銘柄の乖離検知で二波目捕捉。」（alpha_logic）

「循環エントリー: SOL+2/4.75日でJUP/JTO、TAO起点AI。」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: 先導銘柄が変動開始 → ラグ経過後の出遅れ銘柄を優先候補に
- **エントリー**: SOL上昇開始後2日 → JUPエントリー。4.75日 → JTOエントリー
- **エグジット**: アルファ逆転 or BTC Dom反転で退出
- **スイング（数日〜数週間）**: ラグパターンに沿ったセクター内ローテーションスイング
- **短期利確（10%+）**: 出遅れ銘柄のキャッチアップ急騰で10%+利確

## 注意事項
- ⚠️ SOL→JUP 2日、SOL→JTO 4.75日のラグ値は、2026-02-24〜03-09の2週間データに基づく。市場環境により変動する
- ⚠️ ラグ超過（予想日数を過ぎても出遅れ銘柄が反応しない）は偽陽性リスク。JTOの負アルファ（-1.06%）例のように、ラグが伝播しないケースもある
- ⚠️ SOL TVL $6.5B、SOL Revenue $1-5M等の数値はDune Analytics由来であり、CCXT/MEXC APIでは取得不可
- ⚠️ pump.fun卒業トークン100-200/日というエコシステム活性データもDune由来
