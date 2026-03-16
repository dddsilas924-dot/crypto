Empire Monitor - 仮想通貨自動売買システム
==========================================

起動方法
--------
■ 通常起動（落ちたら手動で再起動）
  python main.py

■ Watchdog付き起動（落ちたら自動再起動）★推奨
  python scripts/watchdog.py
  python scripts/watchdog.py --max-restarts 100 --cooldown 5

■ GUI無効で起動
  python main.py --no-gui

■ ポート指定
  python main.py --port 8888


ダッシュボード
--------------
http://127.0.0.1:8080（デフォルト）


BOT一覧
--------
[LevBurn-Sec Aggressive最適化版] ★新規追加
  levburn_sec_agg_lev1      レバ焼きAgg 1倍       TP3%/SL1% フィルタなし   BT Sharpe 9.92
  levburn_sec_agg_lev3_ls   レバ焼きAgg 3倍       TP3%/SL1% フィルタなし   BT Sharpe 8.23
  levburn_sec_agg_lev1_fr   レバ焼きAgg 1倍FR     TP3%/SL1% FR方向フィルタ BT Sharpe 7.41 WR79.1%
  levburn_sec_agg_lev3_fr   レバ焼きAgg 3倍FR     TP3%/SL1% FR方向フィルタ BT Sharpe 6.82
  levburn_sec_agg_7x        レバ焼きAgg 7倍       TP3%/SL1% フィルタなし   BT Sharpe 6.79
  levburn_sec_agg_7x_so     レバ焼きAgg 7倍SO     TP3%/SL1% SHORT限定     BT Sharpe 6.16
  levburn_sec_agg_7x_fr     レバ焼きAgg 7倍FR     TP3%/SL1% FR方向フィルタ BT Sharpe 5.97

[MeanRevert-Strict] ★新規追加
  meanrevert_strict_a       平均回帰（厳格A）     Fear55-75 MA25% RSI>75  BT Sharpe 3.17
  meanrevert_strict_b       平均回帰（超厳格B）   Fear60-80 MA30% RSI>80  BT Sharpe 3.73 WR75%

[Alpha派生] ★新規追加
  alpha_r7                  アルファR7（緩和厳選） Fear<30 Alpha≥1.5      BT Sharpe 1.61

[既存BOT]
  levburn_sec               レバ焼き秒スキャ
  levburn_sec_aggressive    レバ焼き秒スキャ・攻撃型
  levburn_sec_conservative  レバ焼き秒スキャ・堅実型
  levburn_sec_scalp_micro   レバ焼き秒スキャ・マイクロ
  levburn_sec_fr_extreme    レバ焼き秒スキャ・FR極端
  + 各 _lev1 / _lev3 バリアント
  meanrevert                平均回帰（スタンダード）
  meanrevert_tight          平均回帰（タイト）
  + adaptive / hybrid / newlist / tuned
  surge / alpha / scalp / weakshort / sniper / event 他


方向フィルター（direction_filter）
-----------------------------------
settings.yaml の各BOT設定に direction_filter を指定:
  none        LONG/SHORT両方（デフォルト）
  short_only  SHORTシグナルのみ許可
  fr          FR方向フィルター: FR>0→SHORTのみ, FR<0→LONGのみ


バックテスト
------------
■ 派生BOTバックテスト（6年）
  python scripts/run_variant_backtest.py

■ Aggressive系深掘り（2年, 45コンフィグ）
  python scripts/run_aggressive_all60.py

■ Megaバックテスト（全BOT, 6年）
  python scripts/run_mega_backtest.py

■ TP/SLシミュレーション（ペーパーデータ再検証）
  python scripts/sim_tpsl_grid.py

結果は vault/backtest_results/ に出力。


Watchdog仕様
-------------
- main.pyが異常終了（exit code≠0）したらcooldown秒後に自動再起動
- 30秒以内の急速クラッシュが5回連続 → バックオフ（待機時間増加）
- クラッシュログ: vault/logs/crash_YYYYMMDD_HHMMSS.log
- 監視ログ: vault/logs/watchdog.log
- exit code 0（Ctrl+C等）→ 再起動しない
- 最大再起動回数（デフォルト50回）で停止


HTMLレポート
------------
vault/docs/
  bot_catalog.html                  BOTカタログ（ロジック解説）
  bot_catalog_full.html             BOTカタログ＋バックテスト全データ
  variant_backtest_report.html      派生BOTバックテスト結果（104コンフィグ）
  aggressive_depth_full_report.html Aggressive系45コンフィグ全データ
  tpsl_simulation_report.html       TP/SLシミュレーション（40パターン）
  paper_trading_report_2days.html   ペーパートレード2日間成績


ペーパートレード制限ルール
--------------------------
- 同一BOT×同一銘柄: 1ポジションまで（MAX_POSITIONS_PER_BOT_SYMBOL=1）
- 異なるBOT間: 同じ銘柄の保有OK（レバ違いの比較用）
- ペーパー仮想資金: $10,000（PAPER_CAPITAL_USDT）
- 往復コスト: 0.22%（ROUND_TRIP_COST_PCT）


既知の注意点
------------
- バックテストの銘柄スキャンはsectorテーブルのアルファベット順先頭200。
  ETH/SOL/XRP等のH以降の銘柄はスキャンされていない。
  ペーパートレードはTier1通過銘柄を使うため対象が異なる。
- ペーパーとバックテストの成績乖離が大きい（WR: BT69-79% vs Paper37%）
  主因: スリッページ、リアルタイム遅延、銘柄セットの違い


ディレクトリ構成
----------------
config/          設定ファイル（settings.yaml）
data/            DB（empire_monitor.db, historical.db）
scripts/         バックテスト・ユーティリティスクリプト
src/core/        エンジン、ポートフォリオ、リスク管理
src/signals/     BOTシグナルモジュール
src/backtest/    バックテストエンジン
src/ui/          GUIダッシュボード
src/execution/   注文執行
src/fetchers/    データ取得
vault/           ナレッジ、レポート、バックテスト結果
