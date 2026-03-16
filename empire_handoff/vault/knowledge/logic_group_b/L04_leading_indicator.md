---
logic_id: L04
category: tier1_screening
tags: [eth_btc, sol_eth, relative_strength, l1, institutional, tvl, etf]
source: multiple
tier: 1
group: B
implementable: true
data_dependency: [ccxt_ohlcv, ccxt_ticker, external_api]
priority: high
exchange: MEXC
backtest_possible: true
---

# L04: Leading Indicator（先行指標 / ETH vs SOL相対強度）

## 概要
ETH/BTC、SOL/ETH等の相対強度比較でL1覇権と機関資金の流入方向を判定する。
L1チェーン間の相対強度はアルトコイン全体の方向性を先行的に示す。
ETF Flow（BTC ETF/ETH ETF）との照合で機関動向を断定する。

## 定義・目的
主要L1チェーン間の相対強度は資金の流れの先行指標となる。ETH/BTCの上昇は機関投資家のリスクオン姿勢を示し、SOL/ETHの上昇はリテール/DeFi資金のハイベータ志向を示す。これらの比率変化がアルトコイン全体の方向性を先行的に示す。

## 判定ロジック
- **ETH/BTC上昇**: 機関資金がETHに流入 → アルト全体にポジティブ
- **ETH/BTC下落**: 機関資金がBTC回帰 → アルトに逆風
- **SOL/ETH上昇**: ハイベータ資金がSOLエコ系に集中 → SOL系アルトに追い風
- **SOL/ETH下落**: リスク回避 → ハイベータ銘柄に逆風
- 追加: TVL変化率、ETF Flow（BTC ETF/ETH ETF）との照合

## データ要件
- **ETH/BTC価格**: ccxt_ticker（MEXC）
- **SOL/ETH価格**: ccxt_ticker（MEXC）or 計算（SOL/USDT / ETH/USDT）
- **ETF Flow**: 外部API（SoSoValue等）
- **TVL**: DefiLlama API
- **更新頻度**: 1時間ごと（価格）/ 日次（ETF Flow/TVL）
- **MEXC互換性**: 価格は可。ETF Flow/TVLは外部API

## データプロキシ
- ETF Flow: SoSoValue APIが利用不可の場合、BTC/ETH大口取引の方向で代替
- TVL: DefiLlama無料API（`/protocols`）

## 実装ヒント
- ETH/BTC, SOL/ETHの24h/7d変化率を計算
- 方向の組み合わせでセクター判定（L1強/弱、ハイベータ強/弱）
- 結果を環境係数としてセクター別に適用
- Tier: 1
- 計算コスト: 軽量（2ペアの価格比較）

## 他ロジックとの関係
- **依存するロジック**: なし
- **連携するロジック**: L01（マクロ環境と組み合わせ）、L21（SDR: セクターローテーション）
- **矛盾・注意点**: ETH/BTCとSOL/ETHが逆方向の場合、市場が分裂状態。慎重に判断

## 元テキスト引用
「L04. Leading Indicator: ETH/BTC, SOL/ETH 等の相対強度比較。」（gemini_crypto）

「先行指標（ETH vs SOL）: L1覇権/機関流入断定。ETH/BTC vs SOL/BTC + TVL/ETF flow」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: 強いL1のエコシステム銘柄を優先
- **エントリー**: ETH/BTC上昇中 → ETH系DeFi銘柄にエントリー有利
- **エグジット**: ETH/BTC急落 → ETH系銘柄の利確検討
- **スイング（数日〜数週間）**: L1相対強度の週足トレンドに沿ったセクター選択
- **短期利確（10%+）**: L1強弱の急変時はセクター入れ替え

## 注意事項
- ⚠️ ETF Flowデータは1日遅延。リアルタイム判断には不向き
- ⚠️ SOL/ETHペアがMEXC先物に存在しない場合、SOL/USDTとETH/USDTから間接計算が必要
