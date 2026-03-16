---
source: user_hypothesis
category: strategy
tags: [new_listing, IPO, IEO, mean_reversion, short, volatility]
related_existing_logic: [bot_meanrevert, bot_weakshort, bot_meanrevert_newlist]
new_logic_potential: high
backtest_possible: true
data_dependency: [ccxt_ohlcv, database_is_new_listing]
priority: critical
created: 2026-03-11
---

# L22: 新規上場銘柄（IPOアルト）の価格挙動パターン

## 仮説

### 初動の過剰上昇
- 板薄・価格発見未成熟・ナラティブ最大化により上場直後〜数日で+50%〜+300%の急騰
- エアドロップ受取者・初期投資家のFOMOが加速要因

### 資金回収フェーズ
- 初期投資家・エアドロ勢・MMの利確で上場後1〜4週間に30〜80%下落
- トークンアンロックスケジュールとの連動

### 極端なボラティリティ
- 板薄・OI未成熟・クジラ影響で1日20〜60%の値幅
- Funding Rateが極端に偏りやすい（ショートスクイーズ/ロングスクイーズ）

### Mean Reversionが機能しやすい
- 過剰価格形成の反動で短期平均回帰が発生
- 既存銘柄よりMean Reversion戦略の期待値が高い可能性

## フィルター条件

| フィルター | 条件 | 理由 |
|-----------|------|------|
| 上場日フィルター | 上場から30日/60日/90日以内 | 価格発見プロセスの期間 |
| 流動性 | 24h Volume > $5M | スリッページ抑制 |
| ボラティリティ | ATR/Price > 12% or 日次変動率 > 20% | 十分な値幅確保 |
| セクター優先 | AI, Meme, Gaming, DePIN, RWA | ナラティブ主導セクター |

## 検証ポイント

1. **新規銘柄バイアスの有無**: 既存Bot（MeanRevert/WeakShort）が新規銘柄に偏っていないか
2. **新規銘柄専用戦略の成立可否**: 新規銘柄のみを対象とした戦略が十分なPFを達成するか
3. **既存Botの新規銘柄依存度**: 新規銘柄を除外した場合のPF変化

## 戦略候補

### ICO-MeanRevert（ハイプ崩壊ショート）
- 上場後急騰からの反落をショート
- RSI > 70 + 出来高減少がトリガー

### ICO-Rebound（暴落後リバウンドロング）
- Fear < 40で大幅下落した新規銘柄のリバウンド
- RSI < 30 + 出来高増加がトリガー

### ICO-Surge（出遅れキャッチアップロング）
- 同セクターリーダーの上昇に対する出遅れ銘柄
- セクターラグを利用したロング
