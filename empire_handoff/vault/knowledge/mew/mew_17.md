---
source_file: mew/17.txt
category: screening
tags: [correlation, alpha, BTC_independence]
related_existing_logic: [Bot-Alpha]
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv]
priority: critical
created: 2026-03-10
---

# L17: 相関シフト(CACS)

## 概要
BTC相関からの脱却度を測定し、独自の資金流入がある銘柄を抽出するスクリーニングロジック。
Pearson相関係数とAlpha(超過リターン)の組み合わせで、BTC影響下の偽シグナルを排除。
BTC連動脱却は独自資金流入の証明となる。

## 核心内容
- **Sランク条件**: Pearson_r(4h/24h) < 0.3 AND Alpha > 0
- **Aランク条件**: r < 0.5 AND Alpha > 0
- **Zランク条件（除外）**: r > 0.85（BTCの影に過ぎない）
- **Alpha計算**: Alpha = token_return - BTC_return
- **原理**: BTC連動脱却 = 独自資金流入の証明

## トレードロジックへの変換
1. 4h足・24h足でBTC価格とトークン価格のPearson相関係数を算出
2. 同期間のAlpha(超過リターン)を計算
3. r < 0.3 かつ Alpha > 0 の銘柄をSランクとしてTier 2通過
4. r > 0.85 の銘柄はZランクとして即除外
5. 相関係数は動的に変化するため、定期的（4h毎）に再計算

## 既存システムとの統合ポイント
- Tier 1スクリーニングの主要フィルターとして機能
- Bot-Alpha計算ロジックと直接連携
- L16(サーキットブレーカー)のBTC-Alt相関監視と計算を共有

## 実装に必要なデータ・API
- CCXT経由のOHLCVデータ（BTC + 対象トークン、4h/24h足）
- Pearson相関係数の計算ライブラリ（numpy/scipy）
- BTC価格の基準データ

## 元テキスト重要引用
- 「S: Pearson_r(4h/24h)<0.3 AND Alpha>0」
- 「A: r<0.5 AND Alpha>0」
- 「Z: r>0.85(BTC影)」
- 「Alpha=token_ret-BTC_ret」
- 「BTC連動脱却=独自資金流入証明」
