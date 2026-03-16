---
source_file: mew/C.txt
category: indicator
tags: [whale, CEX_reserve, outflow]
related_existing_logic: [L09]
new_logic_potential: low
backtest_possible: false
data_dependency: [external_api]
priority: low
created: 2026-03-10
---

# Deep Logic C: クジラ沈黙率(WSR)

## 概要
大口ホルダーのCEXからColdウォレットへの移動を追跡し、売り拒否HODLの意思を検出。
板が薄い真空状態でAlpha陽転時の爆発力を上方修正する指標。
L09(既存クジラロジック)を補完する行動分析レイヤー。

## 核心内容
- **Sシグナル**: 全供給の0.2%以上が24h内にCEX → Coldウォレットに移動 = 売り拒否HODL
- **効果**: 板薄の真空化 → Alpha陽転時の爆発力を上方修正
- **原理**: 大口が取引所から引き出す = 売る意思なし = 供給側の締め付け

## トレードロジックへの変換
1. 対象トークンの大口ウォレット(供給0.2%以上保有)を特定
2. 24h以内のCEX → Coldウォレット移動を検出
3. 移動量が全供給の0.2%以上なら「クジラ沈黙」状態と判定
4. 板の厚み(オーダーブック深度)を確認し、真空度を評価
5. クジラ沈黙 + 板薄 + Alpha陽転 → エントリー優先度を上方修正

## 既存システムとの統合ポイント
- L09(クジラ関連ロジック)の行動分析を強化
- L19(クジラ結束力)のホルダー分析と連携
- L17(相関シフト)のAlpha陽転判定と組み合わせて爆発力を予測

## 実装に必要なデータ・API
- オンチェーントランザクションデータ（Etherscan、Solscan等）
- CEXウォレットラベリングデータ
- トークン供給量データ
- オーダーブック深度データ（CCXT経由）

## 元テキスト重要引用
- 「全供給0.2%以上が24h内にCEX→Cold移動=売り拒否HODL」
- 「板薄真空化→Alpha陽転時爆発力上方修正」
