# Empire Monitor — 読解・分析メモ（コード変更なし）

コードは一切変更せず、ソースの読解と構造分析のみ実施した結果をまとめる。

---

## 1. エンジン・データフロー概要

### 1.1 起動とエントリポイント
- **main.py** はZIPに含まれていない。起動は `python main.py` または `python scripts/watchdog.py` を想定。
- **EmpireMonitor** (`src/core/engine.py`) が中心。`config_path` で `config/settings.yaml` を読み、BotManager があればそれと連携する。

### 1.2 初期化で作られる主なコンポーネント
| コンポーネント | 役割 |
|----------------|------|
| CacheManager, HistoricalDB | データ・キャッシュ |
| StateManager | 銘柄状態・fear_greed 等 |
| RegimeDetector | パターン(A–F)・**fear_greed** 取得（CoinGecko / Alternative.me F&G） |
| Tier1Engine, Tier2Engine | 870→Top50→Top15 のファンネル |
| BotAlphaEngine, BotSurgeEngine | Alpha/Surge 専用エンジン |
| LevBurnEngine | 30分間隔レバ焼き（L23） |
| **_levburn_sec_engines** | LevBurn-Sec バリアント群（WS有効時のみ生成） |
| PaperTracker | ペーパー記録・同一BOT×同一銘柄 1 ポジまで |
| VetoSystem, RiskManager, ReportScheduler | リスク・レポート |

### 1.3 Fear&Greed の流れ
- **RegimeDetector.fetch_fear_greed()** が Alternative.me F&G API を叩き、**CacheManager** に 5 分 TTL でキャッシュ。
- **StateManager** が `state.fear_greed` を保持（engine が regime 更新時にセット）。
- 利用箇所:
  - **Bot-Alpha**: `check_activation(fear_greed, ...)` — Fear < 10 で発火。
  - **Bot-Surge**: Fear 25–45 + BTC 条件。
  - **Bot-MeanRevert 系**: Fear 50–80 等（各 bot_*.py の閾値）。
  - **LevBurn（30分）**: `regime_info["fear_greed"]` を `detect_burn_candidates` に渡す。
  - **LevBurn-Sec**: `regime` で `fear_greed` を受け取るが、**LONG をブロックする処理はない**（後述）。

---

## 2. LevBurn-Sec の挙動（読解結果）

### 2.1 バリアントとエンジン登録
- **engine.py** の `_SEC_VARIANT_MAP` / `_SEC_BOTKEY_MAP` で、variant 名と bot_key（例: `levburn_sec_aggressive`）が対応。
- **WebSocket が有効**なときだけ、各 `config_key`（例: `bot_levburn_sec_aggressive`）に対応する **LevBurnSecEngine** が 1 つずつ生成され、`_levburn_sec_engines[bot_key]` に格納される。
- settings.yaml の `bot_levburn_sec_*` が存在し、かつ `bots: { bot_key: { mode: paper|live } }` で disabled でなければ、そのバリアントが「有効」。

### 2.2 スキャン経路
1. **LevBurn-Sec 専用スレッド** `_levburn_sec_loop()` が 5 秒間隔で動作。
2. **ホットリスト**は WebSocket の FR 閾値で更新される。空の場合は REST の `_collect_fr_data_for_sec()` で FR を取得し、ホットリストを補完。
3. `regime_info = { "fear_greed": self.state.fear_greed, "regime": self.state.regime }` を組み立て、**メインイベントループ**に `_run_levburn_sec_scan(fr_data, regime_info)` をディスパッチ。
4. 各 `bot_key` について `engine.scan(fr_data, regime)` を実行。シグナルが出たら **direction_filter** を適用したうえで、最大 2 件まで `paper_tracker.record_signal(...)` またはライブ実行。

### 2.3 FR 評価と Fear の使われ方（bot_levburn_sec.py）

```python
# _evaluate_fr(self, fr, regime)
fear = regime.get("fear_greed", 50)
if fear < 25 and direction == "LONG":
    score += 10
elif fear > 75 and direction == "SHORT":
    score += 10
return min(50, score), direction
```

- **direction** は FR の正負のみで決まる: `SHORT` if fr_value > 0 else `LONG`。
- Fear < 25 かつ **LONG** のとき、**スコアに +10 が加算**される（LONG を「推奨」するロジック）。
- **Fear が低いときに LONG を禁止する処理はない。** 日次分析で指摘された「Fear=13 で LONG 連打」は、この「恐怖圏で LONG にボーナス」と、FR<0 → LONG の組み合わせで説明できる。

### 2.4 direction_filter（engine.py で適用）
- `short_only`: シグナルのうち `direction == 'SHORT'` のみ採用。
- `fr`: FR>0 なら SHORT のみ、FR<0 なら LONG のみ採用（FR と逆方向は捨てる）。
- `none`: 全方向採用。

いずれも **Fear の値では制御していない**。

---

## 3. ペーパートレードの制限（現状）

### 3.1 実装されている制限
- **PaperTracker.MAX_POSITIONS_PER_BOT_SYMBOL = 1**
- **count_open_positions_per_bot(bot_type, symbol)** で「その BOT × その銘柄」のオープンポジション数を数え、1 以上なら `record_signal` が **-1** を返して記録しない。

### 3.2 存在しない制限
- **BOT 横断での「同一銘柄の合計オープン数」上限はない。**
- そのため、levburn_sec / levburn_sec_aggressive / levburn_sec_lev1 / … など **18 個の BOT** がそれぞれ 1 ポジションずつ COS で持つと、**同一銘柄に 18 ポジション**まで積める。日次分析の「COS に 168 トレード、72%」はこの構造と整合的。

---

## 4. BOT 登録と設定の流れ

### 4.1 BotManager（bot_manager.py）
- **BOT_REGISTRY**:  bot 名（例: `levburn_sec_aggressive`）→ settings のキー（例: `bot_levburn_sec_aggressive`）の対応が固定で列挙されている。
- `initialize()` で `config.get(config_key, {})` が存在する BOT だけ **BotWorker** が作成され、`workers[bot_name]` に入る。
- **mode** は `config.get('bots', {}).get(bot_name, {}).get('mode', 'paper')` で取得。未指定は `paper`。

### 4.2 LevBurn-Sec が「有効」になる条件
1. **config に `websocket.enabled: true`** があり、`ws_feed` が生成されている。
2. **config に該当する `bot_levburn_sec_*` セクション**がある（中身は空でも可）。
3. **BotManager** を使う場合、`bots.<bot_key>.mode` が `disabled` でない。

Evolved（evo_agg, evo_micro, evo_lev1）は BOT_REGISTRY にあり、engine の _SEC_*_MAP にもあるが、**settings.yaml で bot_levburn_sec_evo_* が無効 or 未定義**だとエンジンは作られても Worker が無い、または mode が disabled になり得る。日次分析の「Evolved 未発火」は、設定の未登録 or 無効が原因の可能性が高い。

---

## 5. バックテストとペーパー乖離 — コードから言えること

| 要因 | コード上の根拠 |
|------|----------------|
| **LONG 偏り（Fear 低いとき）** | LevBurn-Sec の `_evaluate_fr` は Fear<25 かつ LONG のときに **+10 点**。LONG を止めるロジックはない。 |
| **銘柄集中** | 同一 BOT×同一銘柄 1 ポジのみ。BOT 横断の銘柄上限なし → 全 BOT が同じ銘柄に 1 ポジずつ乗れる。 |
| **Evolved 未発火** | BOT_REGISTRY と engine のマップにはあるが、config の `bot_levburn_sec_evo_*` や `bots.*.mode` の有無・値次第でスキャン対象から外れ得る。 |
| **スリッページ・遅延** | ペーパーは `record_signal` で entry_price をそのまま記録。約定価格・約定時刻の差は記録していない（別テーブルやログがあれば要確認）。 |

---

## 6. まとめ（読解・分析のみ）

1. **Fear と LONG の関係**  
   LevBurn-Sec は Fear を「LONG をブロックする」ためには使っておらず、**Fear<25 かつ LONG のときにスコアを加算**している。日次分析で提案された「Fear<20 で LONG 禁止」は、現状コードには存在しない。

2. **銘柄集中**  
   ペーパーでは「1 BOT 1 銘柄 1 ポジ」のみ。BOT 横断の同一銘柄ポジ数上限はないため、多数 BOT が同じ銘柄（例: COS）に同時にポジションを持てる。

3. **設定とエンジンの対応**  
   LevBurn-Sec 系は、WebSocket 有効 + 対応する `bot_levburn_sec_*` 設定 + BotManager の mode の 3 つが揃って初めて稼働する。Evolved が「未発火」なら、config の該当セクションと `bots.<key>.mode` を確認する必要がある。

4. **今後の検証候補（コード変更は行わない前提）**  
   - `vault/export/trade_records.csv` や `paper_signals` のスキーマに「シグナル価格・時刻」と「約定価格・時刻」があるか確認し、スリッページ・遅延の算出可否を整理する。  
   - settings.yaml の `bots` と `bot_levburn_sec_*` の対応を一覧化し、Evolved がスキャン対象に入っているか確認する。

以上。コード変更は一切行っていない。
