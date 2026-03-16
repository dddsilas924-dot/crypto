---
logic_id: L07
category: tier3_commentary
tags: [sector, etf_flow, sosovalue, institutional, rwa, ai_sector, defi]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [external_api]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L07: Sector Flow（セクター資金流入 / ETFフロー）

## 概要
SoSoValue等のETFフローデータとセクター別資金流入を照合し、機関投資家の動向を把握する。
BTC ETF/ETH ETFの大規模フローは市場全体の方向性に影響する。
RWA/AI/DeFi等のセクター別熱量を監視する。

## 定義・目的
BTC ETF/ETH ETFのフローデータ、及びRWA/AI/DeFi等のセクター別資金流入を監視する。機関投資家の大規模な資金移動は市場全体の方向性に影響するため、先行指標として活用する。

## 判定ロジック
- **機関流入**: BTC ETF/ETH ETFに大規模流入 → 市場全体にポジティブ
- **機関流出**: ETFから大規模流出 → リスクオフの兆候
- **セクター熱**: 特定セクター（RWA/AI/DeFi）への集中流入 → そのセクター銘柄に追い風
- **BUIDL等のトークン化ファンド**: RWA（Real World Asset）セクターの機関採用指標

## データ要件
- **ETFフロー**: SoSoValue API or スクレイピング
- **セクター別時価総額**: CoinGecko categories API
- **更新頻度**: 日次
- **MEXC互換性**: 不可（外部データ）

## データプロキシ
- SoSoValue APIが利用不可の場合: BTC/ETH大口取引フロー + セクター別時価総額変化率で代替
- セクター分類: CoinGecko `/coins/categories` で取得可能

## 実装ヒント
- SoSoValueのETFフローページをスクレイピング（API提供状況要確認）
- CoinGeckoのcategories APIでセクター別時価総額を日次取得
- セクター間の相対変化率を計算
- AIへのFact Blockにセクター流入データを含める
- Tier: 3
- 計算コスト: 軽量（外部API数コール）

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L04（先行指標: ETH/SOLの相対強度）、L21（SDR: セクターローテーション）
- **矛盾・注意点**: ETFフローデータは1日遅延。リアルタイム判断には不向き

## 元テキスト引用
「L07. Sector Flow: SoSoValue等のETFフローデータとの照合。」（gemini_crypto）

「SoSo Value セクター資金流入 & ETF: セクター熱/機関動向。RWA/AI/DeFi inflow + BUIDL等」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: セクター熱の高い分野を優先スクリーニング
- **エントリー**: 機関流入増加セクターの銘柄を優先エントリー
- **エグジット**: ETF大規模流出 → ポジション全体の縮小検討
- **スイング（数日〜数週間）**: セクターローテーションに合わせたポジション調整
- **短期利確（10%+）**: セクター過熱（集中流入後の反転兆候）で利確

## 注意事項
- ⚠️ SoSoValueのAPIは公式提供の有無が不明。スクレイピング依存になる可能性あり
- ⚠️ ETFフローデータは1日遅延のため、リアルタイムの急変には対応不可
