---
logic_id: L20
category: tier3_commentary
tags: [network_productivity, revenue, fees, dau, valuation, fundamental, ps_ratio]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [external_api]
priority: high
exchange: MEXC
backtest_possible: partial
---

# L20: NPS（Network Productivity Score / ネットワーク生産性）

## 概要
プロトコルの収益（Fees/Revenue）と時価総額の乖離を分析し、実需に基づく割安判定を行う。
P/S < 20x、MC/TVL < 1x を割安基準とする。
UNI > LDO の優位性判定（Revenue/DAU正規化）が例示されている。

## 定義・目的
トークンの価格は投機で動くが、プロトコルの実需（手数料収入・DAU・Revenue）は実態を反映する。時価総額に対して収益が大きいプロトコルは「稼ぐ力」があり、割安の可能性がある。クリプト特化のUnit Economics指標。

## 判定ロジック
- **P/S Ratio（Price-to-Sales）**: 時価総額 / 年間Revenue < 20x → 割安候補
- **MC/TVL Ratio**: 時価総額 / TVL < 1x → TVL対比で割安
- **DAU/Revenue正規化**: Revenue / DAU で1ユーザーあたりの収益力を評価
- **UNI > LDO優位例**: UNIのdaily burn proxyが高い = 収益力が高い

## データ要件
- **Revenue/Fees**: Token Terminal API or DefiLlama `/fees`
- **TVL**: DefiLlama `/tvl`
- **DAU**: Dune Analytics or Token Terminal
- **時価総額**: CoinGecko API or ccxt_ticker
- **更新頻度**: 日次
- **MEXC互換性**: 時価総額のみ可。他は外部API

## データプロキシ
- Revenue直接取得困難な場合: DefiLlama fees APIで代替
- DAU: DefiLlama `/dexs` でDEX取引量から間接推定

## 実装ヒント
- DefiLlama APIで Revenue/Fees/TVL を取得
- P/S = Market Cap / (Annual Revenue)
- MC/TVL = Market Cap / TVL
- 両方の指標で割安度をスコアリング
- Tier: 3（ただしスコア計算はPython。AIはスコアの解説のみ）
- 計算コスト: 軽量（API数コール + 除算）

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L06（Surf AI Insight: ファンダ分析に統合）
- **矛盾・注意点**: P/S等のバリュエーション指標は伝統金融由来。クリプトでは適用困難な銘柄もある（ミームコイン等）

## 元テキスト引用
「L20. NPS (Network Productivity): 収益（Fees/Revenue）と時価総額の乖離。割安判定。」（gemini_crypto）

「NPS (ネットワーク生産性): 実需質確認（稼ぐ力）。DAU/Revenue正規化（UNI>LDO優位）」（surf_crypto）

「実需バリュエーション: P/S<20x（収益割安）、MC/TVL<1x（TVL優位）。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: バリュエーション指標でTier 3候補をランキング
- **エントリー**: P/S < 20x + MC/TVL < 1x → 割安エントリー候補
- **エグジット**: P/S急上昇（バリュエーション過熱）→ 利確検討
- **スイング（数日〜数週間）**: Revenue成長トレンド確認でスイング保有
- **短期利確（10%+）**: バリュエーション正常化の急騰で短期利確

## 注意事項
- ⚠️ P/S < 20x、MC/TVL < 1x の閾値はsurf_crypto記載の基準。ミームコイン等Revenueが存在しない銘柄には適用不可
- ⚠️ Revenue/DAUデータは外部API依存。データ品質・カバレッジに注意
- ⚠️ UNI > LDO の優位性判定は特定時点の比較であり、恒常的なものではない
