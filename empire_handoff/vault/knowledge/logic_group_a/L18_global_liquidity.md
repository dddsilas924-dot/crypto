---
logic_id: L18
category: market_regime
tags: [macro, dxy, global_liquidity, correlation, m2]
source: multiple
tier: meta
group: A
implementable: partial
data_dependency: [external_api]
priority: high
exchange: MEXC
backtest_possible: partial
---

# L18: GLM（Global Liquidity Model / グローバル流動性同期）

## 概要
マクロ流動性とDXYの逆相関を確認し、仮想通貨市場全体への追い風/逆風を判定する。
L01と組み合わせて環境認識の係数として機能する。
DXY下落 = リスク資産への追い風という構造を検知する。

## 定義・目的
グローバルな法定通貨流動性（M2マネーサプライ、DXY等）と仮想通貨市場の時価総額の相関を監視する。DXY（ドルインデックス）が下落するとリスク資産（仮想通貨含む）に資金が流れやすい構造を検知する。

## 判定ロジック
- **追い風**: DXY下落 + M2拡大 + Total MC上昇 → マクロ環境良好
- **逆風**: DXY上昇 + M2縮小 + Total MC下落 → マクロ引き締め
- **乖離**: DXY下落なのにTotal MC下落 → クリプト固有の問題（要注意）
- DXYとTotal MCの逆相関を確認（相関係数-0.5以下が理想）

## データ要件
- **DXY（ドルインデックス）**: TradingView or Forex API
- **M2マネーサプライ**: FRED API（月次、遅延あり）
- **Total Market Cap**: CoinGecko API
- **更新頻度**: 日次（DXY）、月次（M2）
- **MEXC互換性**: 不可。外部API必要

## データプロキシ
- DXY: CCXT未対応。yfinance（`DX-Y.NYB`）or investing.com スクレイピング
- M2: FRED APIから取得（fred.stlouisfed.org）。月次データのため遅延大
- 簡易プロキシ: USDT.D の変化をDXYの代替指標として使用（完全代替ではない）

## 実装ヒント
- DXYはyfinance等で取得可能（`DX-Y.NYB`）
- 日次でDXY変化率とTotal MC変化率の相関を計算
- 30日ローリング相関係数を算出
- L01と組み合わせてマクロ環境スコアを算出
- Tier: meta（環境係数）
- 計算コスト: 軽量（日次計算）

## 他ロジックとの関係
- **依存するロジック**: なし
- **連携するロジック**: L01（ドミナンス・マトリクス）と組み合わせてマクロ+クリプト環境を総合評価
- **矛盾・注意点**: M2データは月次遅延があるため、リアルタイム判断には不向き。DXYを主軸にする

## 元テキスト引用
「L18. GLM (Global Liquidity Model): マクロ流動性とDXYの逆相関を確認。」（gemini_crypto）

「GLM (グローバル流動性同期): マクロ追い風。DXY逆相関+MC同期」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: マクロ環境スコアを全銘柄スコアの係数に
- **エントリー**: DXY下落トレンド中はエントリーに追い風（ポジションサイズ増可）
- **エグジット**: DXY急騰はリスクオフの先行指標。ポジション縮小検討
- **スイング（数日〜数週間）**: DXY週足トレンドでスイング方向を確認
- **短期利確（10%+）**: DXY急変時は短期利確を優先

## 注意事項
- ⚠️ DXY、M2はいずれもMEXC APIで取得不可。外部API完全依存
- ⚠️ M2マネーサプライは月次発表のため1-2ヶ月の遅延がある。リアルタイム判断にはDXYのみ使用
- ⚠️ DXYとクリプトの逆相関は常に成立するわけではない。相関崩壊時は他ロジックで補完
