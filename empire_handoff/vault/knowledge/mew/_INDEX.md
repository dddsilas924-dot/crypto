# mew/ ナレッジ インデックス

vault/knowledge/mew/ 配下に、25件のトレードロジックナレッジを構造化格納。
元ファイル: vault/knowledge/mew/*.txt (L01-L21 + Deep Logic A-D)

## カテゴリ別一覧

### market_regime（市場環境判定）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_1.md | L01: ドミナンス・マトリクス | high | BTC/ETHドミナンス×F&Gで4象限分類 |
| mew_11.md | L11: センチメント逆張り | medium | SNS/ニュースの極端センチメントで逆張り |
| mew_18.md | L18: グローバル流動性(GLM) | low | M2/DXY/金利差でマクロ流動性評価 |
| mew_B.md | Deep Logic B: ステーブル流入速度(CVM) | low | USDT/USDC時価総額変化率で資金流入判定 |

### screening（銘柄選別）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_2.md | L02: Alpha髭下乖離・回復率 | critical | 髭下からの回復率でリバウンド銘柄検出 |
| mew_3.md | L03: 出来高スパイク | critical | 20日平均比の出来高急増で注目銘柄検出 |
| mew_6.md | L06: ボラ安定性 | medium | ATR/ヒゲ比で安定した値動きの銘柄選別 |
| mew_17.md | L17: 相関シフト(CACS) | critical | BTC相関の急変で独自材料銘柄検出 |
| mew_20.md | L20: ネットワーク生産性(NPS) | low | オンチェーン活動量で実需評価 |
| mew_D.md | Deep Logic D: 供給ショック(SSD) | low | 取引所残高急減で供給逼迫検出 |

### entry（エントリー）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_5.md | L05: BTC反発先行性 | critical | BTC下落後の反発タイミングでエントリー |
| mew_A.md | Deep Logic A: 清算クラスター(LCEF) | medium | 大量清算後の反転ポイントでエントリー |

### exit（エグジット）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_15.md | L15: ATRトレール利確損切 | critical | ATR倍率ベースの動的TP/SL |

### indicator（指標・補助）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_7.md | L07: MA乖離率・過熱判定 | high | MA20/50乖離率で過熱・割安判定 |
| mew_8.md | L08: FR/OI需給判定 | medium | Funding Rate × OI変化で需給バランス |
| mew_9.md | L09: 大口ウォレット動向 | low | クジラウォレットの送金パターン |
| mew_19.md | L19: クジラ結束力(WCA) | low | 上位ウォレットの同期行動度 |
| mew_C.md | Deep Logic C: クジラ沈黙率(WSR) | low | 大口の活動停止率で蓄積期検出 |

### risk_management（リスク管理）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_10.md | L10: 板厚み・スプレッド | medium | オーダーブック深度で流動性リスク評価 |
| mew_12.md | L12: イベントリスク | medium | 予定イベント前後のポジション制御 |
| mew_14.md | L14: ケリー基準ポジションサイジング | high | 勝率×ペイオフ比でポジションサイズ算出 |
| mew_16.md | L16: サーキットブレーカー | high | 連続損失・DD閾値で自動停止 |

### sector（セクター分析）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_4.md | L04: L1親子波及 | medium | L1トークン→エコシステム銘柄への波及 |
| mew_21.md | L21: セクターローテ(SDR) | medium | セクター間の資金循環パターン |

### strategy（総合戦略）
| File | Logic | Priority | 概要 |
|------|-------|----------|------|
| mew_13.md | L13: 最終総合ランク | high | 全ロジックの重み付け統合スコア |
| mew_22_ipo_alt.md | L22: IPOアルト価格挙動 | critical | 新規上場銘柄の過熱→崩壊パターン、専用Bot3種 |

## 優先度別

### critical（即実装候補）
- L02, L03, L05, L15, L17

### high（次期実装候補）
- L01, L07, L13, L14, L16

### medium
- L04, L06, L08, L10, L11, L12, L21, Deep-A

### low（データ取得困難 or 効果未検証）
- L09, L18, L19, L20, Deep-B, Deep-C, Deep-D

## Bot実装との対応

| Bot | 使用ロジック | バックテスト結果 |
|-----|------------|----------------|
| Bot-Alpha | L01(F&G), L17(相関) | PF=1.59, データ不足 |
| Bot-Surge | L01(F&G), L03(乖離) | PF=3.50, WF実運用GO |
| Bot-Momentum | L03+L07+L15 | PF=1.02, 不採用 |
| Bot-Rebound | L02+L05+L17 | PF=1.32, 要改良 |
| Bot-Stability | L06+L07+L14 | PF=1.14, 不採用 |
