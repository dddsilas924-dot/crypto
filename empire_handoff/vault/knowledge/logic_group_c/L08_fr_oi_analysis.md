---
logic_id: L08
category: tier2_validation
tags: [funding_rate, open_interest, short_squeeze, overheated, derivatives]
source: multiple
tier: 2
group: C
implementable: true
data_dependency: [ccxt_funding, ccxt_ticker, ccxt_open_interest]
priority: high
exchange: MEXC
backtest_possible: partial
---

# L08: FR/OI Analysis（Funding Rate / Open Interest分析）

## 概要
Funding RateとOpen Interestの組み合わせで踏み上げ・過熱・関心低下を判定する。
先物市場の需給バランスを定量的に評価するTier 2の中核ロジック。
3パターン（踏み上げ/過熱/関心低下）のフラグで銘柄の先物環境を分類する。

## 定義・目的
先物市場のFunding Rate（資金調達率）とOpen Interest（未決済建玉）は市場参加者のポジション傾向を反映する。この2指標の組み合わせパターンから、踏み上げ（Short Squeeze）のチャンス、過熱の危険、関心低下の兆候を検知する。

## 判定ロジック
- **踏み上げ（Short Squeeze）**: OI増加 + Funding Rate マイナス → ショートが積まれている状態。価格上昇で踏み上げ発生の可能性 → **加点**
- **過熱（Overheated）**: Funding Rate 異常高騰 → ロングが過密。反転リスク → **減点**
- **関心低下**: 価格横ばい + OI激減 → 市場参加者の離散 → **除外**
- **健全上昇**: 価格上昇 + OI増加 + FR適度にプラス → 新規ロングが入っている → **加点**
- 価格上昇中にOIが減少 → ショートカバー（買戻し）の可能性（AI System Prompt指摘事項）

## データ要件
- **Funding Rate**: ccxt `fetch_funding_rate()` or `fetch_funding_rate_history()`
- **Open Interest**: ccxt `fetch_open_interest()` or `fetch_open_interest_history()`
- **更新頻度**: 8時間ごと（FR確定タイミング）/ 毎時（OI）
- **MEXC互換性**: 可（MEXC Futuresは両方サポート）

## データプロキシ
- Long/Short Ratio: 一部取引所のみ提供。MEXC対応状況要確認
- FR/OI直接取得困難な場合: CCXT経由のBinance/Bybitデータをフォールバック

## 実装ヒント
- Tier 1通過銘柄のみFR/OIを取得（API呼び出し数削減）
- FR: 直近8hの確定値 + 次回予想値
- OI: 24h変化率を計算
- 3パターン（踏み上げ/過熱/関心低下）のフラグをセット
- Tier: 2
- 計算コスト: 中量（銘柄ごとにAPI呼び出し。Tier 1で絞り込み済みなので20-50銘柄程度）

## 他ロジックとの関係
- **依存するロジック**: L02/L03/L09/L17（Tier 1通過が前提）
- **連携するロジック**: L10（板の厚さ）、L13（LCEF: 清算クラスター）
- **矛盾・注意点**: FR正=ブルとは限らない。FR異常高騰は反転の前兆。OI増加も方向を見極める必要あり

## 元テキスト引用
「L08. FR/OI Analysis: 踏み上げ (Short Squeeze): OI増加 + Funding Rateマイナス。過熱 (Overheated): Funding Rate異常高騰は減点。関心低下: 価格横ばいでOI激減は除外。」（gemini_crypto）

「先物データ（Funding Rate / Long-Short Ratio）: センチ/レバ過熱。FR正=ブル、OI急増=警戒」（surf_crypto）

「価格上昇中にOIが減少している場合は、「ショートカバー（買戻し）の可能性」を必ず指摘してください。」（gemini_crypto / AI System Prompt）

## トレード実行への適用
- **スクリーニング**: 過熱・関心低下銘柄を除外
- **エントリー**: OI増加 + FRマイナス（踏み上げパターン）→ 強い買いシグナル
- **エグジット**: FR異常高騰 → 利確検討。OI急減 → ポジション再評価
- **スイング（数日〜数週間）**: FR推移のトレンドを確認。持続的にマイナス→踏み上げ蓄積
- **短期利確（10%+）**: 踏み上げ発生の急騰で即利確

## 注意事項
- ⚠️ FR「異常高騰」の閾値はソーステキストに具体値なし。運用しながら閾値を設定する必要がある
- ⚠️ OI「激減」の定義も定性的。24h変化率の閾値設定が必要
