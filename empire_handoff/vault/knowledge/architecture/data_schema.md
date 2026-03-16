---
logic_id: data_schema
category: architecture
tags: [schema, pydantic, type_safety, fact_block, analysis_payload]
source: gemini_crypto
tier: na
group: architecture
implementable: true
data_dependency: []
priority: high
exchange: MEXC
backtest_possible: false
---

# データスキーマ（Pydantic型定義）

## 概要
Pydanticによる厳格な型定義でAI幻覚を防止する。
全データ構造をここで定義し、Tier間のデータ受け渡しの型安全性を保証する。
特にTier 3 AIに渡すFact Blockの構造が重要。

## 定義・目的
システム内で受け渡すデータの型を厳密に定義する。特にTier 3 AIに渡すFact Blockは、Pythonが計算済みの確定データのみを含み、AIが数値を推測する余地を排除する。Iron Rule #2（Source of Truth）と#3（データ欠損）を型レベルで強制する。

## 判定ロジック
該当なし（スキーマ定義）

## データ要件
該当なし（スキーマ定義）

## データプロキシ
該当なし

## 実装ヒント
### 主要スキーマ

```python
from pydantic import BaseModel
from typing import Optional

class AssetMaster(BaseModel):
    """銘柄マスタ"""
    symbol_id: str
    low_1010_price: float        # 聖域価格
    sector: str                  # RWA / AI / DeFi / Meme 等

class Tier1Result(BaseModel):
    """Tier 1スクリーニング結果"""
    symbol: str
    price: float
    source: str = "MEXC"
    dist_from_1010_pct: float    # 聖域乖離率（Python計算済み）
    volume_ratio: float          # 出来高スパイク倍率
    alpha_vs_btc: float          # 対BTC超過リターン
    btc_correlation_30d: float   # 30日BTC相関係数
    tier1_score: float           # Tier 1統合スコア
    passed: bool                 # Tier 1通過フラグ

class Tier2Result(BaseModel):
    """Tier 2検証結果"""
    symbol: str
    funding_rate: float
    oi_change_24h: float
    depth_2pct_usd: float        # ±2%板厚（USD）
    lcef_risk: Optional[float]   # 清算クラスターリスク（None許容）
    veto: bool                   # VETO発動フラグ
    tier2_score: float
    passed: bool

class AnalysisPayload(BaseModel):
    """Tier 3 AIに渡すFact Block"""
    symbol: str
    price: float
    source: str = "MEXC"
    dist_from_1010_pct: float
    oi_change_24h: float
    funding_rate: float
    whale_status: str            # "Accumulating" / "Dumping" / "Unknown"
    ps_ratio: Optional[float]    # P/S比率
    mc_tvl_ratio: Optional[float]
    sector: str
    pattern: str                 # "A" - "F"

class TradeSignal(BaseModel):
    """トレードシグナル"""
    symbol: str
    action: str                  # "LONG" / "CLOSE" / "ALERT"
    reason: str
    confidence: float            # 0.0 - 1.0
    leverage: float = 2.0        # デフォルト2x
    stop_loss: Optional[float]   # 聖域価格
```

### 設計原則
- 全数値フィールドは`Optional[float]`でNone許容（Iron Rule #3）
- `source`フィールドを必須化（Iron Rule #2）
- AIに渡すのは`AnalysisPayload`のみ。生のAPIレスポンスは渡さない

## 他ロジックとの関係
- 全ロジックのデータ受け渡しの基盤
- Iron Rule #2（Source of Truth）、#3（データ欠損）を型レベルで強制

## 元テキスト引用
```python
class AssetMaster(BaseModel):
    symbol_id: str
    low_1010_price: float

class AnalysisPayload(BaseModel):
    symbol: str
    price: float
    source: str = "Binance"
    dist_from_1010_pct: float
    oi_change_24h: float
    funding_rate: float
    whale_status: str
```
（gemini_crypto ※sourceを"MEXC"に変更）

## トレード実行への適用
該当なし（スキーマ定義）

## 注意事項
- ⚠️ gemini_crypto原文では `source: str = "Binance"` だが、本プロジェクトでは `source: str = "MEXC"` に変更
- ⚠️ Tier1Result/Tier2Resultはgemini_crypto原文には記載なし。実装上の拡張スキーマ
- ⚠️ `whale_status` の "Unknown" はデータ取得成功だが判定不能の場合。データ取得失敗時は None（Iron Rule #3）
