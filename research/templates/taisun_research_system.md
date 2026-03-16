name: taisun-research-system  
version: "2.2"  
description: "4ステップで技術リサーチ→アーキテクチャ設計→レポート生成"  
estimated\_time: "15～30分"  
══════════════════════════════════════  
入力  
══════════════════════════════════════  
input:  
build\_target: "\[BUILD\_TARGET\]" \# ← ここに「作りたいもの」を記述  
══════════════════════════════════════  
PRE-FLIGHT（開始前確認）  
══════════════════════════════════════  
pre\_flight:  
env\_vars:  
• { name: ANTHROPIC\_API\_KEY, required: true, falback: nul }  
• { name: XAI\_API\_KEY, required: false, falback: "mega-research-plus で代替" }  
• { name: X\_BEARER\_TOKEN, required: false, falback: "HN Algolia \+ Bluesky で代替" }  
• { name: TAVILY\_API\_KEY, required: false, falback: "open-websearch で代替" }  
• { name: NEWSAPI\_KEY, required: false, falback: "RSS直接取得で代替" }  
on\_missing\_build\_target: "「何を構築したいですか？」と確認してから開始"  
start\_message: ¦  
TAISUN v2 起動 ¦ 対象: {build\_target}  
モード: {XAI\_API\_KEY ? 'omega-research' : 'mega-research-plus'}  
X API: {X\_BEARER\_TOKEN ? 'X APIトレンド取得' : 'HN/Bluesky代替'}  
4ステップで実行します...  
══════════════════════════════════════  
STEP 1: キーワード宇宙の展開  
══════════════════════════════════════  
step1:  
name: "キーワード宇宙の展開"  
paralel: true  
tasks:  
keyword\_extraction:  
skil: keyword-mega-extractor  
falback: keyword-free  
prompt: ¦  
「{build\_target}」のキーワードを展開:  
• core\_keywords (5～10個)  
• related (技術・ツール・概念)  
• compound (「～自動化」「～API」等)  
• rising\_2026 (急上昇・代理指標付き)  
• niche (競合少ない切り口)  
• tech\_stack\_candidates  
• mcp\_skils\_needed  
出力: CSV形式 \+ カテゴリ別リスト  
inteligence\_research:  
skil: inteligence-research  
run\_in\_background: true  
sources: "GIS 31ソース（HN/Reddit/X 340アカウント/FRED経済指標）"  
x\_trends:  
condition: "X\_BEARER\_TOKEN が存在する場合"  
endpoints:  
• "GET /2/tweets/search/recent?query={keywords} lang:ja \-is:retweet\&max\_results=100"  
• "GET /2/tweets/search/recent?query={keywords} lang:en min\_faves:5\&max\_results=100"  
• "GET /2/trends/by/woeid?id=1118370 \# 日本トレンドTOP20"  
errors:  
403: "inteligence-research の X\_WATCH\_ACCOUNTS（340件）で代替"  
429: "5秒待機後リトライ（最大3回）"  
no\_token: "HN Algolia API \+ Bluesky Firehose で代替"  
output: "キーワードリスト \+ SNS初期データを保存 → STEP 2 へ"  
══════════════════════════════════════  
STEP 2: ディープリサーチ（必ず2回）  
══════════════════════════════════════  
step2:  
name: "ディープリサーチ（2回実施・省略禁止）"  
pass1:  
description: "3エージェント並列（run\_in\_background: true）"  
result\_max\_chars: 500 \# 各エージェント・メインコンテキスト保護  
agent\_a:  
role: "MCP・スキル・拡張機能の発掘"  
urls:  
• [https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)  
• [https://mcp.so](https://mcp.so/)  
• [https://smithery.ai](https://smithery.ai/)  
• [https://composio.dev](https://composio.dev/)  
• [https://pulsemcp.com](https://pulsemcp.com/)  
• [https://cursor.directory](https://cursor.directory/)  
• [https://mcpservers.org](https://mcpservers.org/)  
• [https://github.com/punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)  
• [https://github.com/trending?since=weekly](https://github.com/trending?since=weekly)  
• [https://trendshift.io](https://trendshift.io/)  
tasks:  
• "{build\_target} 関連MCPサーバーを全特定（Stars急増率・無料枠・セキュリティで評価）"  
• "即インストール可能なものをインストールコマンド付き表形式で TOP20"  
• "Claude Code Skils Library から関連スキルも特定"  
output: "research/agent\_a\_mcp.md"  
agent\_b:  
role: "API・ライブラリ・SaaS・パッケージ調査"  
urls:  
• [https://apis.guru/api-list.json](https://apis.guru/api-list.json)  
• [https://rapidapi.com](https://rapidapi.com/)  
• [https://npmjs.com](https://npmjs.com/)  
• [https://pypi.org](https://pypi.org/)  
• [https://npmtrends.com](https://npmtrends.com/)  
• [https://bundlejs.com](https://bundlejs.com/)  
• [https://libraries.io](https://libraries.io/)  
• [https://huggingface.co/api](https://huggingface.co/api)  
• [https://paperswithcode.com/api/v1](https://paperswithcode.com/api/v1)  
• [https://osv.dev](https://osv.dev/) \# CVE脆弱性（必須）  
• [https://nvd.nist.gov/developers/vulnerabilities](https://nvd.nist.gov/developers/vulnerabilities)  
• [https://socket.dev](https://socket.dev/) \# npmサプライチェーン攻撃検知  
• [https://choosealicense.com](https://choosealicense.com/)  
tasks:  
• "{build\_target} に必要なAPI/ライブラリを網羅的にリストアップ"  
• "コスト・セキュリティ・ライセンスで評価・無料枠/OSS代替比較表"  
• "CVE/脆弱性リスクを全候補で確認（osv.dev \+ socket.dev）"  
output: "research/agent\_b\_api.md \+ research/cost\_breakdown.csv"  
agent\_c:  
role: "アーキテクチャ・最新トレンド・コミュニティ調査"  
urls:  
• [https://hn.algolia.com/api/v1/search](https://hn.algolia.com/api/v1/search)  
• [https://www.reddit.com/r/LocalLLaMA/new/](https://www.reddit.com/r/LocalLLaMA/new/)  
• [https://www.reddit.com/r/ClaudeAI/new/](https://www.reddit.com/r/ClaudeAI/new/)  
• [https://docs.bsky.app](https://docs.bsky.app/)  
• [https://export.arxiv.org/api/query](https://export.arxiv.org/api/query)  
• [https://microservices.io](https://microservices.io/)  
• [https://dev.classmethod.jp](https://dev.classmethod.jp/)  
• [https://zenn.dev/topics/{keyword}/feed](https://zenn.dev/topics/%7Bkeyword%7D/feed)  
• [https://qita.com/tags/{keyword}/feed.atom](https://qita.com/tags/%7Bkeyword%7D/feed.atom)  
• [https://b.hatena.ne.jp/hotentry/it](https://b.hatena.ne.jp/hotentry/it)  
• [https://github.com/mehdihadeli/awesome-software-architecture](https://github.com/mehdihadeli/awesome-software-architecture)  
tasks:  
• "2026年時点の最新アーキテクチャベストプラクティス特定"  
• "HN/Reddit/Zenn/Qita から「本当の課題」と「未解決ニーズ」を抽出"  
• "類似OSS/SaaSの比較（Stars推移・更新頻度）"  
• "SOLID \+ CQRS \+ Event-driven 設計の適用可否判定"  
• "Mermaid C4 アーキテクチャ図作成（コンポーネント・データフロー・外部API含む）"  
output: "research/agent\_c\_arch.md \+ architecture.mermaid"  
pass2:  
description: "ギャップ補完リサーチ（Pass1の不足・不明確点を補完）"  
skil: omega-research  
falback: mega-research-plus  
architecture:  
layer1: "Grok-4 Agent Tools \+ Exa semantic search"  
layer2: "Tavily \+ Brave \+ NewsAPI \+ SerpAPI \+ Perplexity"  
layer3: "GIS 31ソース \+ X API v2（340アカウント監視）"  
layer4: "Arxiv \+ Papers with Code \+ HF Daily"  
synthesis: "Grok-4 最終統合（重複排除→クロス検証→スコアリング）"  
focus:  
• "Pass1で「不明」「要確認」とした全項目"  
• "セキュリティリスクが高いツールの代替案"  
• "コスト試算の精度向上"  
• "日本語コミュニティの反応（Zenn/Qita/はてブ）"  
output: "全エージェント結果を統合 → STEP 3 へ"  
══════════════════════════════════════  
STEP 3: 必要なものを全て揃える  
══════════════════════════════════════  
step3:  
name: "システム構築に必要なものを全て揃える"  
trend\_score:  
formula: ¦  
TrendScore \=  
0.35 × stars\_delta\_7d  
0.25 × npm\_growth\_30d  
0.20 × x\_engagement\_score  
0.10 × hn\_reddit\_score  
0.10 × recency\_score  
x\_engagement\_score \=  
0.4 × (likes \+ retweets) / impressions  
0.3 × influencer\_mentions \# 監視340件  
0.3 × trend\_position\_score \# 日本トレンド順位  
thresholds:  
hot: "\> 0.7 ★★★ 即採用推奨"  
warm: "0.4～0.7 ★★ 要検討"  
cold: "\< 0.4 ★ 採用非推奨"  
no\_x\_token: "HN Algolia API \+ Bluesky Firehose で代替"  
output: "TOP10表（hot/warm/cold色分け）+ research/discovered\_tools.json"  
compliance\_check:  
role: "プロダクト法務/セキュリティ担当"  
checks:  
• "データ取得・保存の規約/著作権/PI 観点確認"  
• "X API 利用規約（Developer Agreement）準拠"  
• "OSSライセンス（MIT/Apache/GPL/AGPL）と商用利用可否"  
• "CVE/脆弱性チェック（osv.dev \+ socket.dev \+ nvd.nist.gov）"  
• "robots.txt 自動遵守方針"  
• "APIキー管理（.env \+ .gitignore 必須）"  
output: "research/risk\_register.md \+ research/compliance\_notes.md"  
architecture:  
role: "Principal Architect"  
principles: "SOLID \+ CQRS \+ Event-driven \+ API-first"  
tech\_stack:  
runtime: "Node.js 22 LTS (TypeScript strict)"  
database: "PostgreSQL 16 \+ pgvector"  
cache: "Redis 7"  
queue: "BulMQ"  
monitoring: "Prometheus \+ Grafana"  
deploy: "Docker Compose → Kubernetes (Phase 3)"  
cicd: "GitHub Actions"  
layers:  
ingestion: "X API v2 / RSS 50+ / GitHub API / MCP poling / NewsAPI / Arxiv"  
processing: "keyword-mega-extractor / omega-research / TrendScore / 重複排除"  
storage: "PostgreSQL \+ pgvector / Redis"  
output: "Markdown/PDF / Mermaid C4図 / Slack/LINE通知"  
security:  
• "APIキー: 環境変数のみ（ハードコード禁止）"  
• ".env を .gitignore に追加"  
• "robots.txt 自動遵守（robots-parser）"  
• "OAuth2 優先 / PI 最小化"  
• "npm audit 週次実行"  
output: "research/architecture\_final.md \+ architecture.mermaid（更新版）"  
implementation\_plan:  
phase1:  
period: "1ヶ月"  
budget: "$20～50/月"  
tasks:  
• { task: "X API v2 Bearer Token 設定・接続確認", hours: 1, skil: "develop-backend" }  
• { task: "omega-research 動作確認・テスト実行", hours: 2, skil: "build-feature" }  
• { task: "コアAPI統合（Exa/X API/主要ライブラリ）", hours: 3, skil: "build-feature" }  
• { task: "PostgreSQL \+ pgvector セットアップ", hours: 3, skil: "postgresql" }  
• { task: "TrendScore 計算エンジン実装", hours: 4, skil: "develop-backend" }  
• { task: "日次レポート自動生成スクリプト", hours: 3, skil: "data-engineer" }  
success\_criteria:  
• "X API で最新ツイートが取得できる"  
• "TrendScore が正しく計算される"  
• "MD レポートが自動生成される"  
phase2:  
period: "1～3ヶ月"  
budget: "$100～200/月"  
features:  
• "daily-news-report: 毎朝8時自動配信"  
• "n8n: X/SNS トレンド → Slack 通知"  
• "BulMQ: クロールジョブ管理"  
• "RSS 50+フィード統合（RSSHub）"  
phase3:  
period: "3～6ヶ月"  
budget: "$300～500/月"  
features:  
• "Elasticsearch: 全文検索高速化"  
• "Kafka: リアルタイムストリーム処理"  
• "Kubernetes: コンテナオーケストレーション"  
• "Composio: 982ツールキット一括統合"  
output: "全成果物を統合 → STEP 4 へ"  
══════════════════════════════════════  
STEP 4: レポート提出・ユーザー確認待ち  
══════════════════════════════════════  
step4:  
name: "ユーザーへのレポート提出・提案"  
output\_dir: "research/runs/{YYYY-MM-DD}\_\_system-proposal/"  
files:  
• { name: "report.md", description: "12セクション完全レポート（省略禁止）" }  
• { name: "report.pdf", description: "PDF版（/pdf-official スキル使用）" }  
• { name: "architecture.mermaid", description: "C4アーキテクチャ図（最終版）" }  
• { name: "discovered\_tools.json", description: "発見ツール全件（TrendScore付き）" }  
• { name: "keyword\_universe.csv", description: "キーワード宇宙（STEP1出力）" }  
• { name: "cost\_breakdown.csv", description: "コスト試算表（Phase 1～3）" }  
• { name: "x\_trends.json", description: "X/SNSトレンドデータ（取得できた場合）" }  
report\_sections: \# 全12セクション・省略禁止  
1: "Executive Summary（価値・差別化・コスト・ROI・なぜ今か）"  
2: "市場地図（MCP/Skils/API全体マップ・競合比較・OSS vs SaaS）"  
3: "X/SNSリアルタイムトレンド分析（340アカウント・感情分析・予測）"  
4: "Keyword Universe（全キーワード・代理指標付き）"  
5: "データ取得戦略（全ソース・規約遵守・無料枠・コスト発生タイミング）"  
6: "正規化データモデル（TypeScript interface / PostgreSQL設計）"  
7: "TrendScore 算出結果（hot★★★/warm★★/cold★ 採用推奨TOP5）"  
8: "システムアーキテクチャ図（Mermaid C4必須）"  
9: "実装計画（Mermaid Ganttチャート・3フェーズ）"  
10: "セキュリティ/法務/運用設計（CVE・ライセンス・RunBook）"  
11: "リスクと代替案（確率・影響・代替手段の表）"  
12: "Go/No-Go 意思決定（今作るべき理由TOP3・最初の1アクション）"  
completion\_message: ¦  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  
TAISUN v2 リサーチレポート完成  
対象: {build\_target}  
生成先: research/runs/{YYYY-MM-DD}\_\_system-proposal/  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  
ル 次のアクション（いずれかをお伝えください）  
Ⅰ「問題なし / 進めて」  
→ /gather-requirements \+ /sdd-ful でシステム設計を開始  
Ⅺ「追加・修正: \[内容\]」  
→ 指定箇所を修正して再提出  
よ「\[質問\] を確認したい」  
→ 詳細調査して回答  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  
wait\_for\_user: true \# 04 ユーザー承認なしに要件定義・実装に進まないこと  
══════════════════════════════════════  
品質基準（全STEPで遵守）  
══════════════════════════════════════  
quality:  
min\_sources\_per\_finding: 3  
citation\_required: true \# 数値・コストには出典URL必須  
code\_samples: true \# 主要コンポーネントに実装例を含める  
no\_abstract: true \# 「～が重要です」だけで終わらず具体的実装まで  
language: "日本語優先（技術用語は英語OK）"  
monthly\_budget\_limit: "$40/月（超える場合は代替手段を提示）"  
result\_max\_chars\_per\_agent: 500  
research\_passes: 2 \# Pass 1 \+ Pass 2（省略禁止）  
compact\_at\_phase\_boundary: true  
══════════════════════════════════════  
LLM ルーティング  
══════════════════════════════════════  
lm\_routing:  
• { task: "SNS・X分析", model: "Grok 3", cost\_per\_m: "$3.00" }  
• { task: "ディープリサーチ（引用付き）", model: "Perplexity Deep", cost\_per\_m: "$2.00" }  
• { task: "コード生成", model: "MiniMax M2.5", cost\_per\_m: "$0.30" }  
• { task: "バッチ高速処理", model: "Groq Maverick", cost\_per\_m: "$0.50" }  
• { task: "日本語文書生成", model: "GLM-5", cost\_per\_m: "$0.11" }  
• { task: "全力リサーチ（omega）", model: "Grok-4", cost\_per\_m: "xAI料金" }  
• { task: "汎用", model: "DeepSeek V3", cost\_per\_m: "$0.14" 