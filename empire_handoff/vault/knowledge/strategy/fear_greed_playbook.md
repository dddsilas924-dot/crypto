---
logic_id: fear_greed_playbook
category: strategy
tags: [fear_greed, extreme_fear, reversal, contrarian, bottom, sentiment]
source: alpha_logic
tier: na
group: strategy
implementable: true
data_dependency: [external_api, ccxt_ticker, ccxt_ohlcv]
priority: high
exchange: MEXC
backtest_possible: partial
---

# Fear & Greed 極限戦略（Extreme Fear Playbook）

## 概要
Fear & Greed Index が極限的低水準（7等）に達した局面での逆張り戦略を定義する。
過去データでExtreme Fearは底打ち反発の買い場パターン。
アルト乖離検知（L_alpha_divergence）と組み合わせて高エッジのエントリーを実現する。

## 定義・目的
Fear & Greed IndexがExtreme Fear（20以下、特に10以下）に達した局面は、歴史的に反発買いの好機となることが多い。市場参加者の過度な恐怖心理が合理的な価格水準を超えて売り込みを発生させ、その後の反発で大きなリターンが得られる。ただし、底を正確に当てることは不可能であるため、ドミナンス・マトリクス（パターンD）とAlpha乖離検知を組み合わせたフィルターが不可欠。

## 判定ロジック
### エントリートリガー
- **Fear & Greed Index < 20**: 参入検討開始（Extreme Fear）
- **Fear & Greed Index < 10**: 積極的参入検討（歴史的底値圏）
- **パターンD継続**: ドミナンス・マトリクスがパターンC（全面安）でないことを確認
- **Alpha陽転**: 対BTC騰落 > 0 の銘柄に限定（恐怖相場でも独自に強い銘柄）

### 現在地（2026-03-09時点、alpha_logic由来）
- Fear & Greed Index: **7（Extreme Fear）**
- 7日トレンド: 下落中
- BTC価格: $66,210（直近1h）
- 市場解釈: 底打ち反発の前兆形成中

### 具体的戦略
1. **地合いフィルター**: Fear & Greed < 20 AND (BTC Dom低下 or Fear & Greed < 10) → Go
2. **乖離検知**: 相関 < 0.5 AND アルファ > 3%（L_alpha_divergence参照）
3. **聖域確認**: 10/10安値の上で反発（L02参照）
4. **レバレッジ制限**: Extreme Fear局面は不確実性が高いため、レバ2x以下を推奨
5. **分割エントリー**: 一括ではなく3-5回に分割してエントリー（底の見極めが困難なため）

### エグジット条件
- **利確**: Fear & Greed > 40（恐怖解消）で部分利確。> 60 で全利確
- **損切り**: 聖域割れ（SLヒット）
- **強制決済**: パターンC移行で全ポジションクローズ

## データ要件
- **Fear & Greed Index**: Alternative.me API（`https://api.alternative.me/fng/`）
- **BTC価格**: ccxt_ticker
- **対BTC騰落率**: ccxt_ohlcv
- **Altcoin Season Index**: blockchaincenter.net
- **更新頻度**: 日次（Fear & Greed）/ 毎時（価格）
- **MEXC互換性**: Fear & Greed/Altcoin Seasonは外部API。価格は可

## データプロキシ
- Fear & Greed Index: Alternative.me無料APIで取得可能
- Altcoin Season Index: blockchaincenter.netからスクレイピング or API
- 簡易代替: BTC 24h変化率 + 出来高急増をFear代替指標に

## 実装ヒント
- Alternative.me APIを日次で呼び出し、Fear & Greed値を取得
- 閾値（< 20, < 10）でアラートレベルを段階設定
- パターンD + Fear極限の同時検知で専用パイプラインを起動
- 分割エントリーはスケジューラで24h間隔等に設定
- 計算コスト: 軽量（API 1コール + 閾値判定）

## 他ロジックとの関係
- **依存するロジック**: L01（ドミナンス・マトリクス: パターンC除外）、L02（聖域確認）
- **連携するロジック**: L_alpha_divergence（乖離検知）、L17（相関シフト）、pattern_d_playbook（パターンD戦略と統合）
- **矛盾・注意点**: Extreme Fearが常に反発を意味するわけではない。パターンCではExtreme Fearでも買い禁止

## 元テキスト引用
「Fear & Greed Index: 7（Extreme Fear）、7日トレンド下落中。過去データでこの水準は底打ち反発の買い場。」（alpha_logic）

「地合いフィルタ: BTC Dom<50%低下 or Fear&Greed<20 → Go。」（alpha_logic）

「Fear低迷は反発ブーストの典型パターン。」（alpha_logic）

「Wintermute分析通り、米株流入でcryptoリテール資金が抑制されているが、Fear低迷は反発ブーストの典型パターン。」（alpha_logic）

「保守派はアラート運用、積極派は自動エントリー。Fear低迷の今が最適構築期。」（alpha_logic）

## トレード実行への適用
- **スクリーニング**: Fear & Greed < 20 で全銘柄スクリーニングの感度を上げる（通常より多くの銘柄を通過させる）
- **エントリー**: Fear & Greed < 10 + パターンD + Alpha陽転 + 聖域反発 → 分割エントリー開始
- **エグジット**: Fear & Greed > 40 で部分利確開始。パターンC移行で全切り
- **スイング（数日〜数週間）**: Extreme Fear→Normal回復の波（通常1-3週間）に乗るスイング
- **短期利確（10%+）**: 反発初動で10%+到達なら短期利確（恐怖相場は再下落リスクあり）

## 注意事項
- ⚠️ Fear & Greed Index = 7 は alpha_logic記載時点（2026-03-09）の値。現在値はAPI経由で確認が必要
- ⚠️ BTC価格 $66,210 は alpha_logic記載時点のスナップショット
- ⚠️ 「過去データで底打ち反発の買い場」はalpha_logicの記載だが、具体的なバックテスト結果や勝率は提示されていない。⚠️ バックテスト未実施の数値
- ⚠️ Extreme Fear局面はボラティリティが極めて高く、SLが容易にヒットするリスクがある。分割エントリー + 低レバが必須
- ⚠️ 米株流入によるcryptoリテール資金抑制（Wintermute分析）の影響は、alpha_logic記載時点の市場環境に依存
- ⚠️ alpha_logicの「Bot化で月間エッジ10-20%可能」は未検証の推測値。⚠️ 未検証の非現実的数値の可能性
