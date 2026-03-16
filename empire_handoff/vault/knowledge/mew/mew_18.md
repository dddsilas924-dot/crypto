---
source_file: mew/18.txt
category: market_regime
tags: [DXY, stablecoin, macro, liquidity]
related_existing_logic: []
new_logic_potential: low
backtest_possible: false
data_dependency: [external_api]
priority: low
created: 2026-03-10
---

# L18: グローバル流動性(GLM)

## 概要
マクロ経済指標（DXY）とステーブルコイン供給動向を組み合わせたマーケットレジーム判定。
グローバルな流動性環境がクリプト市場に有利か不利かを判定する。
外部データ依存のため、補助的なレジームフィルターとして位置づけ。

## 核心内容
- **Sシグナル**: DXY下落 AND ステーブルコイン発行増
- **Zシグナル（危険）**: DXY急騰 AND ステーブルコインburn
- **DXY閾値**: DXY > 100 = リスクオフ環境
- **原理**: ドル安+ステーブル流入 = クリプトへの資金流入環境

## トレードロジックへの変換
1. DXYの日次変化率を追跡（下落トレンド vs 上昇トレンド）
2. 主要ステーブルコイン(USDT/USDC)の時価総額変化を監視
3. DXY下落 + ステーブル発行増 → マーケットレジームを「有利」に設定
4. DXY急騰 + ステーブルburn → マーケットレジームを「不利」に設定、ロング抑制
5. Tier 1/2の全体的なリスク調整係数として適用

## 既存システムとの統合ポイント
- マーケットレジーム判定のマクロレイヤーとして全ロジックに影響
- L14(ポジションサイジング)のリスク配分を環境に応じて調整
- L16(サーキットブレーカー)の補助判定材料

## 実装に必要なデータ・API
- DXYリアルタイムデータ（TradingView API、Yahoo Finance等）
- ステーブルコイン時価総額データ（CoinGecko、DefiLlama等）
- ステーブルコインmint/burn イベントデータ

## 元テキスト重要引用
- 「S: DXY下落∩ステーブル発行増」
- 「Z: DXY急騰∩ステーブルburn」
- 「DXY>100=リスクオフ」
