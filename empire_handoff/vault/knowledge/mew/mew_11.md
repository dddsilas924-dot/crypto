---
source_file: mew/11.txt
category: market_regime
tags: [fear_greed, social, sentiment, contrarian]
related_existing_logic: [Bot-Alpha]
new_logic_potential: low
backtest_possible: true
data_dependency: [fear_greed]
priority: medium
created: 2026-03-10
---

# L11: センチメント逆張り

## 概要
Fear & Greed Index・Altシーズン指数・ソーシャルボリュームの3指標で市場センチメントを判定。
極端な恐怖（Fear<25）を逆張り買い場、極端な強欲をVETOとする。
Fear 12は絶望底の買い場シグナル。

## 核心内容
- **ランク判定**:
  - S: Fear < 25 かつ Alt < 25 かつ Social < 0.5x
  - Z: Fear > 75 or Social > 3x or L/S > 2
- **絶望底シグナル**: Fear = 12 で絶望底買い場
- **逆張りの原則**: 大衆が恐怖の時に買い、強欲の時に売る

## トレードロジックへの変換
- Fear & Greed Indexを日次で取得・判定
- Sランク（極端恐怖）でBot-Alphaの攻撃性を上げる
- Zランク（極端強欲）でポジション縮小

## 既存システムとの統合ポイント
- Bot-Alphaの逆張りエントリー補助
- L01ドミナンス・マトリクスとの複合レジーム判定
- Tier 1の市場環境フィルター

## 実装に必要なデータ・API
- Fear & Greed Index API（alternative.me）
- Altシーズン指数（CoinMarketCap or 独自計算）
- ソーシャルボリューム（LunarCrush等）

## 元テキスト重要引用
- 「S: Fear<25∩Alt<25∩Social<0.5x」
- 「Z: Fear>75 or Social>3x or L/S>2」
- 「Fear12=絶望底買い場」
