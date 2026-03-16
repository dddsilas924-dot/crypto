---
logic_id: L14
category: tier2_validation
tags: [cross_chain, bridge, stablecoin, capital_flow, onchain]
source: multiple
tier: 2
group: C
implementable: partial
data_dependency: [onchain, external_api]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L14: CVM（Cross-Chain Velocity / クロスチェーン燃料速度）

## 概要
特定チェーンへのブリッジ流入速度を検知し、新規資金の到着/燃料不足を確認する。
実装難易度が高いため、Stablecoin時価総額で代替可能。
チェーン別の資金フローからエコシステムの活性度を判断する。

## 定義・目的
クロスチェーンブリッジを通じた資金移動の速度と方向は、特定のエコシステムへの資金流入を先行的に示す。Stablecoin（USDT/USDC/DAI）の特定チェーンへの流入は、そのチェーン上のDeFi/トレーディング活動の増加を予告する。

## 判定ロジック
- **資金流入**: 特定チェーンへのStablecoin流入増加 → そのチェーン系銘柄に追い風
- **燃料不足**: Stablecoin流入が減少 or 流出 → そのチェーン系銘柄に逆風
- **全体流入**: USDT/USDC総供給量の変化 → 市場全体の資金量指標

## データ要件
- **Stablecoin供給量（チェーン別）**: DefiLlama Stablecoins API
- **ブリッジ流量**: DefiLlama Bridges API or Dune Analytics
- **更新頻度**: 日次
- **MEXC互換性**: 不可（オンチェーンデータ）

## データプロキシ
- ブリッジ流量が取得困難な場合: Stablecoin時価総額（チェーン別）の変化率で代替
- DefiLlama `/stablecoins` APIで主要ステーブルの供給量推移を取得
- USDT.D（USDT Dominance）の変化で全体の資金フローを間接判定

## 実装ヒント
- DefiLlama APIでチェーン別ステーブル供給量を日次取得
- 7日変化率を計算し、流入/流出の方向を判定
- 実装難易度が高いため、初期実装ではStablecoin総供給量の変化率のみで簡易版を構築
- Tier: 2
- 計算コスト: 軽量（外部API 1コール + 計算）

## 他ロジックとの関係
- **依存するロジック**: なし（独立）
- **連携するロジック**: L04（先行指標: チェーン間の資金移動方向）、L21（SDR: セクターローテーション）
- **矛盾・注意点**: オンチェーンデータは遅延がある（ブロック確認時間）。リアルタイム判断には不向き

## 元テキスト引用
「L14. CVM (Cross-Chain Velocity): 特定チェーンへのブリッジ流入速度（実装難易度高のため、Stablecoin時価総額で代替可）。」（gemini_crypto）

「CVM (クロスチェーン燃料速度): 新規資金確認/燃料不足。Stable supply（USDT/USDC/DAI）flow」（surf_crypto）

「USDT Dominance ~7%（184Bドル）: 中立。安定供給、資金流入余地大」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: 資金流入中のチェーン系銘柄を優先
- **エントリー**: 該当チェーンへのStablecoin流入増加中 → そのチェーン系銘柄へのエントリーに追い風
- **エグジット**: Stablecoin流出加速 → ポジション縮小検討
- **スイング（数日〜数週間）**: 週次でチェーン別資金フロー確認
- **短期利確（10%+）**: 大規模ブリッジ流入直後の急騰で利確

## 注意事項
- ⚠️ ブリッジ流量データはCCXT/MEXC APIでは取得不可。DefiLlama/Dune等の外部API完全依存
- ⚠️ gemini_crypto自身が「実装難易度高」と記載。初期実装ではStablecoin時価総額プロキシで十分
- ⚠️ USDT Dominance "~7%（184Bドル）" はalpha_logic記載時点（2026-03-09）の値
