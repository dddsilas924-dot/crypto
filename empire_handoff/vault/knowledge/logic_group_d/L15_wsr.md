---
logic_id: L15
category: tier3_commentary
tags: [whale, supply_ratio, exchange_reserve, smart_money, chz]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [onchain, external_api]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L15: WSR（Whale Supply Ratio / クジラ保持率）

## 概要
大口保有者（クジラ）の保有率変化を監視し、プロの逃げ足を先行察知する。
CHZ天井時のクジラ売却が教訓。
Exchange Reserve減少 + Inflow=0 はクジラ蓄積の兆候。

## 定義・目的
クジラ（大口保有者）の行動は市場に大きなインパクトを与える。クジラが蓄積中（Accumulating）であれば上昇の追い風、売却中（Dumping）であれば天井の兆候。

## 判定ロジック
- **蓄積中（Accumulating）**: Exchange Reserve減少 + Inflow = 0 → クジラが取引所から引き出し保有 → ポジティブ
- **売却中（Dumping）**: Exchange Reserve増加 + 大口取引所への入金 → 売却準備 → ネガティブ
- **不明（Unknown）**: データ不十分 → None扱い（Iron Rule #3）

## データ要件
- **Exchange Reserve**: CryptoQuant API or Glassnode
- **クジラウォレット追跡**: Nansen or Arkham Intelligence
- **更新頻度**: 日次
- **MEXC互換性**: 不可（オンチェーンデータ）

## データプロキシ
- 簡易代替: CCXT大口取引のフロー分析（取引サイズ上位のnet方向）
- DefiLlama CEX透明性データの活用

## 実装ヒント
- CryptoQuant/Glassnode APIで主要銘柄のExchange Reserveを取得
- 7日変化率を計算
- 結果をAnalysisPayloadの `whale_status` フィールドに設定
- Tier: 3
- 計算コスト: 軽量（API 1コール + 計算）

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L16（SSD: 供給ショック）、L19（WCA: クジラ結束力）
- **矛盾・注意点**: クジラの行動は操作可能（フェイクアウト）。単独判断は危険

## 元テキスト引用
「L15. WSR (Whale Supply Ratio): 大口保有率の変化。」（gemini_crypto）

「WSR (クジラ保持率): プロ逃げ足監視（CHZ天井）。Exchange reserve/inflowゼロ=耐性」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: Tier 3コメンタリーの参考材料
- **エントリー**: クジラ蓄積中 → エントリーの追加確認材料
- **エグジット**: クジラ売却開始 → 利確検討の参考
- **スイング（数日〜数週間）**: クジラ蓄積トレンド継続 → スイング保有継続
- **短期利確（10%+）**: クジラの大量売却兆候で即利確

## 注意事項
- ⚠️ Exchange ReserveデータはCCXT/MEXC APIでは取得不可。CryptoQuant/Glassnode等の有料API依存
- ⚠️ CHZ天井の具体的数値（日時、価格等）はソーステキストに詳細なし
- ⚠️ クジラの行動はフェイクアウト（意図的な偽シグナル）の可能性あり。単独判断禁止
