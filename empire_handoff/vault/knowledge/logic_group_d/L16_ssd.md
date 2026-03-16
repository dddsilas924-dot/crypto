---
logic_id: L16
category: tier3_commentary
tags: [supply_shock, exchange_reserve, burn, deflation, uni]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [onchain, external_api]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L16: SSD（Supply Shock Detector / 供給ショック検知）

## 概要
取引所在庫の急減やバーン（トークン焼却）によるデフレ加速を検知する。
供給ショックは売り圧力低下 → 価格上昇圧力を意味する。
UNIのdaily burn proxy等、プロトコル固有のデフレ要因を監視する。

## 定義・目的
取引所に存在するトークン在庫が急減すると、売り圧力が低下し供給ショック（Supply Shock）が発生する可能性がある。また、バーンメカニズムによる供給量の持続的減少は構造的なデフレ要因。

## 判定ロジック
- **供給ショック**: Exchange Reserve急減（7日で-10%以上） → 売り圧力低下 → ポジティブ
- **デフレ加速**: バーン量増加 + 循環供給量減少 → 構造的に好材料
- **在庫増加**: Exchange Reserve増加 → 売却準備の可能性 → ネガティブ

## データ要件
- **Exchange Reserve**: CryptoQuant or Glassnode
- **バーン量**: オンチェーンデータ（Etherscan/ブロックエクスプローラー）
- **循環供給量**: CoinGecko API
- **更新頻度**: 日次
- **MEXC互換性**: 不可（オンチェーンデータ）

## データプロキシ
- Exchange Reserve直接取得困難な場合: 循環供給量の変化率で間接判定
- CoinGecko APIの `circulating_supply` 変化を日次監視
- バーン量: プロトコル固有（UNI: Etherscan contract events）

## 実装ヒント
- CoinGecko APIで循環供給量を日次取得
- 供給量の7d変化率を計算
- バーン量はプロトコル固有のため、個別実装が必要
- Tier: 3
- 計算コスト: 軽量

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L15（WSR: クジラ行動と供給の関連）
- **矛盾・注意点**: Exchange Reserve減少が必ずしもポジティブとは限らない（DeFiへの移動等）

## 元テキスト引用
「L16. SSD (Supply Shock): 取引所在庫の急減。」（gemini_crypto）

「SSD (供給ショック): 在庫枯渇/デフレ加速。Reserve減少+バーン（UNI proxy、circ supply比監視）」（surf_crypto）

「デフレ加速: バーン/供給破壊（UNI daily burn proxy、circ supply比監視）。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: Tier 3コメンタリーの参考材料
- **エントリー**: 供給ショック兆候 + 他ロジック合致 → 買いの追加材料
- **エグジット**: Exchange Reserve急増 → 売り圧力増大の兆候、利確検討
- **スイング（数日〜数週間）**: デフレトレンド継続確認でスイング保有
- **短期利確（10%+）**: 供給ショックによる急騰で短期利確

## 注意事項
- ⚠️ Exchange Reserve -10% の閾値はソーステキストに明記なし。目安として設定
- ⚠️ UNI daily burn proxy の具体的計算方法はソーステキストに詳細なし
- ⚠️ Exchange Reserve減少がDeFiプロトコルへのステーキング/流動性提供の場合、売り圧力低下とは限らない
