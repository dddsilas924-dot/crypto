---
logic_id: L12
category: tier3_commentary
tags: [sns, sentiment, narrative, kol, twitter, mindshare]
source: multiple
tier: 3
group: D
implementable: partial
data_dependency: [external_api]
priority: medium
exchange: MEXC
backtest_possible: false
---

# L12: Mindshare（SNSの熱量・センチメント）

## 概要
SNSでの言及数・センチメントを数値化済みデータとして取得し、ナラティブシフトを検知する。
KOL（Key Opinion Leader）の議論トピックの変化から市場の注目先を追跡する。
数値化済みデータのみを使用し、AIの主観は排除する。

## 定義・目的
X（Twitter）等のSNSでの特定銘柄/セクターの言及頻度とセンチメント（ポジティブ/ネガティブ）の変化は、価格変動の先行指標となりうる。KOLの議論トピックの変化からナラティブシフトを検知する。

## 判定ロジック
- **ナラティブ加熱**: 言及数急増 + センチメント改善 → 注目度上昇（追い風）
- **ナラティブ冷却**: 言及数減少 → 関心離散（逆風）
- **FUD検知**: 言及数急増 + センチメント悪化 → パニック売りの可能性
- **数値化済みデータを使用**: AIの主観ではなく、定量化されたセンチメントスコアを参照

## データ要件
- **言及数/センチメント**: LunarCrush API or Santiment API
- **KOL議論トピック**: X API（有料）
- **Mindshareランキング**: Asksurf（asksurf.ai/hub/mindshare）
- **更新頻度**: 日次（API制限依存）
- **MEXC互換性**: 不可（SNSデータ）

## データプロキシ
- LunarCrush/Santiment API利用不可の場合: Google Trends + X検索頻度で簡易代替
- Kaito等の無料ツールでMindshareデータ取得可能

## 実装ヒント
- LunarCrush APIでSocial Volume / Social Sentimentを取得
- 7日移動平均との比較で急変を検知
- AIへのFact Blockにセンチメントスコアを含める
- Tier: 3
- 計算コスト: 軽量（API 1コール + 計算）

## 他ロジックとの関係
- **依存するロジック**: Tier 1/2通過が前提
- **連携するロジック**: L21（SDR: ナラティブシフトとセクターローテーションの関連）
- **矛盾・注意点**: SNSセンチメントは操作可能（ボット等）。単独では判断材料にしない

## 元テキスト引用
「L12. Mindshare: SNSでの言及数・センチメント（数値化済みデータを使用）。」（gemini_crypto）

「Mindshare（SNSの熱量・センチメント）: ナラティブシフト。X/KOL議論+センチ変化」（surf_crypto）

「TAO max alpha 6.41%、Mindshareトップ」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: Tier 3のコメンタリー参考材料
- **エントリー**: センチメント改善 + 他ロジックと合致 → エントリーの追加確認材料
- **エグジット**: センチメント急悪化 → 利確/損切り検討の参考
- **スイング（数日〜数週間）**: ナラティブの持続性を確認しスイング保有判断
- **短期利確（10%+）**: SNS過熱（FOMO）のピークで短期利確

## 注意事項
- ⚠️ SNSセンチメントはボット操作やFOMO/FUDに影響されやすい。単独判断は危険
- ⚠️ TAO Mindshareトップの情報はalpha_logic記載時点（2026-03-09前後）のもの
