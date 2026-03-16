---
logic_id: L21
category: tier3_commentary
tags: [sector_rotation, capital_cycle, narrative, ai_meme_rwa, desci]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [external_api]
priority: high
exchange: MEXC
backtest_possible: partial
---

# L21: SDR（Sector Rotation / セクターローテーション）

## 概要
「AI → Meme → RWA」等の資金循環サイクルの現在地を判定する。
次の資金テレポート先を特定し、先行ポジショニングを行う。
a16z等のVCファンドの投資先変化も参考指標とする。

## 定義・目的
仮想通貨市場ではセクター間の資金循環（ローテーション）が定期的に発生する。直近のサイクルでは AI → Meme → RWA → DeSci 等の順序で資金が移動した。この循環の現在地を把握することで、次に資金が向かうセクターを予測する。

## 判定ロジック
- **ローテーション検知**: セクター別時価総額の相対変化率（7d/30d）を比較
- **加熱セクター**: 時価総額急増中 → 資金流入中だが天井リスク
- **冷却セクター**: 時価総額下落後に安定 → 次の資金流入先候補
- **カテゴリ優先**: RWA（ONDO）、DeSci/AI（BIO）、DeFi（UNI/LDO）、イベント（PI）

## データ要件
- **セクター別時価総額**: CoinGecko categories API
- **セクター別出来高**: CoinGecko categories API
- **更新頻度**: 日次
- **MEXC互換性**: 不可（外部データ）

## データプロキシ
- CoinGecko `/coins/categories` で主要セクターの時価総額・出来高を取得
- 代替: 各セクター代表銘柄の価格変化率で推定

## 実装ヒント
- CoinGecko categories APIで主要セクター（AI, Meme, RWA, DeFi, DeSci, Gaming, L1, L2）の時価総額を日次取得
- セクター間の相対パフォーマンス（7d/30d）を計算
- ヒートマップ形式で可視化
- Tier: 3
- 計算コスト: 軽量（API数コール + 計算）

## 他ロジックとの関係
- **依存するロジック**: L01（ドミナンス・マトリクスでマクロ環境確認後）
- **連携するロジック**: L04（先行指標: L1レベルの動向）、L07（Sector Flow: セクター資金流入）、L14（CVM: チェーン別資金流入）、L_sector_rotation_lag（セクター内ラグ）
- **矛盾・注意点**: セクター分類は曖昧（例: AIトークンはDeFiにも分類される場合がある）

## 元テキスト引用
「L21. SDR (Sector Rotation): 「AI → Meme → RWA」等の資金循環サイクルの現在地判定。」（gemini_crypto）

「SDR (セクターローテ): 資金テレポート先特定。AI/RWA/DeSci相対変化（ローテ監視）」（surf_crypto）

「カテゴリ優先: RWA（ONDO）、DeSci/AI（BIO）、DeFi（UNI/LDO）、イベント（PI）。」（surf_crypto）

## トレード実行への適用
- **スクリーニング**: 次のローテーション先セクターの銘柄を重点スクリーニング
- **エントリー**: 冷却後安定化セクターの割安銘柄 → 次のローテーション先として先行買い
- **エグジット**: 保有セクターが過熱ピーク → ローテーション前に利確
- **スイング（数日〜数週間）**: セクターローテーションの波に乗りスイング
- **短期利確（10%+）**: セクター加熱初期に乗り、10%+で利確

## 注意事項
- ⚠️ セクター分類は曖昧（例: BIOはDeSciにもAIにも分類可能）。分類の一貫性を保つ必要あり
- ⚠️ ローテーションサイクルの周期や順序は固定ではなく、市場環境により変動
- ⚠️ a16zローテの参考は定性的であり、自動化困難
