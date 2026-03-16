"""
Grok API x_search PoC — ダマシ相場検知テスト

目的: X(Twitter)のリアルタイム投稿からファンダメンタル情報をキャッチし、
     一時的な価格急変（ダマシ）を検知できるか検証

アーキテクチャ:
  1. x_search で銘柄関連のXポストを取得
  2. Grokに「ファンダ要因による急変か？類似銘柄への波及は？」を判定させる
  3. JSON構造化レスポンスで score/reason/related_symbols を返す

コスト見積:
  - x_search: $0.005/回
  - grok-4-1-fast token: ~$0.20/1M input, $0.50/1M output
  - 1回の銘柄チェック: ~$0.01未満
  - 1日100回チェック: ~$1/日
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta


XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_ENDPOINT = "https://api.x.ai/v1/responses"
MODEL = "grok-4-1-fast-non-reasoning"


# ===== テスト1: 銘柄のXセンチメント取得 =====
async def check_symbol_sentiment(symbol: str, session: aiohttp.ClientSession) -> dict:
    """
    指定銘柄のXポストを検索し、ファンダ要因を検知する。

    Returns:
        {
            "symbol": "TRUMP",
            "sentiment": "bullish" | "bearish" | "neutral",
            "score": -1.0 ~ 1.0,
            "is_fundamental": true/false,
            "fundamental_reason": "大統領が暗号資産支持を表明...",
            "damashi_risk": "high" | "medium" | "low",
            "related_symbols": ["MELANIA", "MAGA", ...],
            "confidence": 0.0 ~ 1.0,
            "post_count": 42
        }
    """
    # 銘柄名のマッピング (ティッカー → 検索キーワード)
    keyword_map = {
        "TRUMPOFFICIAL": "TRUMP coin crypto $TRUMP",
        "MELANIA": "MELANIA coin crypto $MELANIA",
        "DENT": "DENT crypto $DENT",
        "RESOLV": "RESOLV crypto $RESOLV",
        "TAG": "TAG crypto $TAG",
        "LYN": "LYN crypto $LYN",
        "NAORIS": "NAORIS crypto $NAORIS",
    }

    # _USDT を除去
    clean_symbol = symbol.replace("_USDT", "").replace("/USDT:USDT", "")
    search_query = keyword_map.get(clean_symbol, f"{clean_symbol} crypto")

    # 過去24時間の投稿を検索
    from_date = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d")
    to_date = datetime.utcnow().strftime("%Y-%m-%d")

    payload = {
        "model": MODEL,
        "input": [
            {
                "role": "user",
                "content": f"""Search X for recent posts about "{search_query}" in the last 24 hours.

Analyze the posts and return a JSON object (no markdown, raw JSON only) with this structure:
{{
  "symbol": "{clean_symbol}",
  "sentiment": "bullish" or "bearish" or "neutral",
  "score": float from -1.0 (extremely bearish) to 1.0 (extremely bullish),
  "is_fundamental": true if there is a real news event or announcement driving the price (not just speculation),
  "fundamental_reason": "brief description of the fundamental catalyst if any, empty string if none",
  "damashi_risk": "high" if a sudden fundamental event could cause a temporary spike that reverses,
                  "medium" if there is some news but unclear impact,
                  "low" if organic market movement,
  "related_symbols": ["list of related/correlated crypto tokens that might be affected"],
  "confidence": float 0.0 to 1.0 indicating how confident you are in this assessment,
  "post_volume": "high" or "medium" or "low" (relative to normal for this token),
  "key_posts_summary": "1-2 sentence summary of the most impactful posts found"
}}

Focus on:
- Real news events (regulations, partnerships, listings, political events)
- Sudden spikes in discussion volume
- Influential accounts posting about the token
- Cross-token correlations (meme coins moving together)
"""
            }
        ],
        "tools": [
            {
                "type": "x_search",
                "from_date": from_date,
                "to_date": to_date,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with session.post(XAI_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                return {"error": f"HTTP {resp.status}: {error_text}", "symbol": clean_symbol}

            data = await resp.json()

            # レスポンスからテキスト部分を抽出
            output_text = ""
            citations = data.get("citations", [])

            # Responses API の output 構造を解析
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text = content.get("text", "")

            # JSON抽出（```json ... ``` を除去）
            text = output_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            try:
                result = json.loads(text)
                result["_citations"] = citations
                result["_raw_length"] = len(output_text)
                return result
            except json.JSONDecodeError:
                return {
                    "symbol": clean_symbol,
                    "raw_response": output_text[:500],
                    "error": "JSON parse failed"
                }

    except Exception as e:
        return {"error": str(e), "symbol": clean_symbol}


# ===== テスト2: 複数銘柄の一括チェック =====
async def batch_check_sentiment(symbols: list[str]) -> list[dict]:
    """複数銘柄のセンチメントを並行チェック"""
    async with aiohttp.ClientSession() as session:
        tasks = [check_symbol_sentiment(s, session) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if not isinstance(r, Exception) else {"error": str(r)} for r in results]


# ===== テスト3: ダマシ判定ロジック =====
def evaluate_damashi_risk(sentiment_data: dict) -> dict:
    """
    センチメントデータからダマシリスクを評価

    判定基準:
    - is_fundamental=True → ファンダ起因の動き
    - post_volume=high + score極端 → 過熱/パニック
    - related_symbols多い → セクター連動、ダマシリスク高
    - confidence低い → 情報不足、トレード回避推奨
    """
    if "error" in sentiment_data:
        return {"action": "SKIP", "reason": f"データ取得エラー: {sentiment_data['error']}"}

    is_funda = sentiment_data.get("is_fundamental", False)
    damashi = sentiment_data.get("damashi_risk", "low")
    score = sentiment_data.get("score", 0)
    confidence = sentiment_data.get("confidence", 0)
    volume = sentiment_data.get("post_volume", "low")
    related = sentiment_data.get("related_symbols", [])

    # 判定ロジック
    risk_score = 0
    reasons = []

    if is_funda:
        risk_score += 3
        reasons.append(f"ファンダ要因検知: {sentiment_data.get('fundamental_reason', '?')}")

    if damashi in ("high", "medium"):
        risk_score += 2 if damashi == "high" else 1
        reasons.append(f"ダマシリスク: {damashi}")

    if volume == "high":
        risk_score += 1
        reasons.append("投稿量急増")

    if abs(score) > 0.7:
        risk_score += 1
        reasons.append(f"極端なセンチメント: {score:.2f}")

    if len(related) >= 3:
        risk_score += 1
        reasons.append(f"類似銘柄連動: {', '.join(related[:5])}")

    if confidence < 0.3:
        risk_score += 1
        reasons.append("情報信頼度低")

    # アクション決定
    if risk_score >= 4:
        action = "BLOCK"  # エントリー禁止
    elif risk_score >= 2:
        action = "CAUTION"  # レバ半減 or ポジションサイズ縮小
    else:
        action = "OK"  # 通常通り

    return {
        "action": action,
        "risk_score": risk_score,
        "reasons": reasons,
        "recommendation": {
            "BLOCK": "エントリー禁止 — ファンダ起因の急変リスク高。類似銘柄も回避",
            "CAUTION": "注意 — レバレッジ半減、ポジションサイズ50%推奨",
            "OK": "通常通りエントリー可能"
        }[action]
    }


# ===== メイン =====
async def main():
    if not XAI_API_KEY:
        print("=" * 60)
        print("XAI_API_KEY が未設定です")
        print()
        print("設定方法:")
        print("  1. https://console.x.ai/ でAPIキーを取得")
        print("     ($25の無料クレジット付き)")
        print("  2. 環境変数に設定:")
        print("     set XAI_API_KEY=xai-xxxxxxxxxxxxx")
        print("  3. または .env ファイルに追記:")
        print("     XAI_API_KEY=xai-xxxxxxxxxxxxx")
        print()
        print("コスト見積:")
        print("  - x_search: $0.005/回")
        print("  - grok-4-1-fast token: ~$0.001/回")
        print("  - 1回の銘柄チェック合計: ~$0.006")
        print("  - 1日100回 = ~$0.60/日")
        print("=" * 60)

        # APIキーなしでもダマシ判定ロジックのテストは可能
        print("\n--- ダマシ判定ロジック単体テスト ---\n")

        # シミュレーションデータ: TRUMPダマシ相場
        mock_trump = {
            "symbol": "TRUMP",
            "sentiment": "bullish",
            "score": 0.85,
            "is_fundamental": True,
            "fundamental_reason": "トランプ大統領がビットコイン準備金に関する大統領令に署名",
            "damashi_risk": "high",
            "related_symbols": ["MELANIA", "MAGA", "TREMP", "DJT"],
            "confidence": 0.8,
            "post_volume": "high",
            "key_posts_summary": "Trump signed executive order on Bitcoin reserve, meme coins pumping"
        }

        mock_tag = {
            "symbol": "TAG",
            "sentiment": "bearish",
            "score": -0.3,
            "is_fundamental": False,
            "fundamental_reason": "",
            "damashi_risk": "low",
            "related_symbols": [],
            "confidence": 0.6,
            "post_volume": "low",
            "key_posts_summary": "Normal trading activity, no significant news"
        }

        mock_resolv = {
            "symbol": "RESOLV",
            "sentiment": "neutral",
            "score": 0.1,
            "is_fundamental": False,
            "fundamental_reason": "",
            "damashi_risk": "low",
            "related_symbols": [],
            "confidence": 0.4,
            "post_volume": "low",
            "key_posts_summary": "Minimal discussion about RESOLV"
        }

        for mock in [mock_trump, mock_tag, mock_resolv]:
            print(f"銘柄: {mock['symbol']}")
            print(f"  センチメント: {mock['sentiment']} (score={mock['score']})")
            print(f"  ファンダ要因: {mock['is_fundamental']}")
            if mock['fundamental_reason']:
                print(f"  理由: {mock['fundamental_reason']}")

            risk = evaluate_damashi_risk(mock)
            print(f"  → アクション: {risk['action']} (risk_score={risk['risk_score']})")
            print(f"  → {risk['recommendation']}")
            for r in risk['reasons']:
                print(f"    - {r}")
            print()

        return

    # APIキーがある場合: 実際にGrok APIを呼び出す
    print("=" * 60)
    print("Grok x_search リアルタイムセンチメント検証")
    print(f"時刻: {datetime.now().isoformat()}")
    print("=" * 60)

    # ペーパートレードで使われた銘柄をチェック
    test_symbols = [
        "TRUMPOFFICIAL_USDT",
        "MELANIA_USDT",
        "TAG_USDT",
        "RESOLV_USDT",
    ]

    print(f"\n対象銘柄: {', '.join(test_symbols)}\n")

    results = await batch_check_sentiment(test_symbols)

    for result in results:
        symbol = result.get("symbol", "?")
        print(f"\n{'='*40}")
        print(f"銘柄: {symbol}")
        print(f"{'='*40}")

        if "error" in result:
            print(f"  エラー: {result['error']}")
            if "raw_response" in result:
                print(f"  生レスポンス: {result['raw_response'][:200]}")
            continue

        print(f"  センチメント: {result.get('sentiment', '?')} (score={result.get('score', '?')})")
        print(f"  ファンダ要因: {result.get('is_fundamental', '?')}")
        print(f"  理由: {result.get('fundamental_reason', 'なし')}")
        print(f"  ダマシリスク: {result.get('damashi_risk', '?')}")
        print(f"  投稿量: {result.get('post_volume', '?')}")
        print(f"  関連銘柄: {result.get('related_symbols', [])}")
        print(f"  信頼度: {result.get('confidence', '?')}")
        print(f"  要約: {result.get('key_posts_summary', '?')}")
        print(f"  引用数: {len(result.get('_citations', []))}")

        # ダマシ判定
        risk = evaluate_damashi_risk(result)
        print(f"\n  ★ ダマシ判定: {risk['action']} (risk_score={risk['risk_score']})")
        print(f"  ★ {risk['recommendation']}")
        for r in risk['reasons']:
            print(f"    - {r}")


if __name__ == "__main__":
    asyncio.run(main())
