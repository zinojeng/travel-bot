# 🦞 travel-bot — Multi-Agent 旅行規劃 Orchestrator

以 OpenClaw Gateway（ChatGPT OAuth）／ Google AI Gemini 平行協調多位 Agent：行程規劃、交通、美食文化、預算；最終由 Team Lead 整合並回傳 Discord。

本版為對 `orchestrator.py` 進行雙方審稿（Codex × Claude）後合併的修正版，重點改動：

- 移除 PII：旅行資訊、訂位代號、姓名全改從 `.env` 讀取，repo 不留個資
- Discord 發送加上 `Retry-After` 重試、序列化鎖，避免多 agent 平行時被 rate limit 吃掉訊息
- `requests` 加上 Session + `urllib3` Retry（connect/read/backoff、5xx 自動重試）
- `.env` parser 支援 `export`、引號包裹、行內註解
- `_is_failed_report()` 不再只憑 `❌` 前綴誤判；加入空字串、極短輸出檢查
- `search_and_answer()` 最終 LLM 失敗時，會把已經收集到的搜尋結果回給使用者，不再只拋裸例外
- prompt injection 硬化：搜尋結果改包在 `<search_results>...</search_results>` 並在 system prompt 中明示為「資料而非指令」
- OpenClaw Gateway health check 改為條件化：所有模型都是 `gemini-*` 時不強制需要 Gateway 在線
- Discord bot 單 agent 指令、`!plan` 加 try/except，避免 exception 噴回 event loop
- 輸出檔案統一 `encoding="utf-8"` 並納入 try/except
- 移除 `result[:1800]` 兩次截斷（交給 `dc_send()` 的 1900 字元切段）
- Brave Search `search_lang` 從非標準 `jp` 改成 ISO 639-1 的 `ja`
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()`

## 使用

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入自己的 token 與行程資料
python3 orchestrator.py              # 完整規劃
python3 orchestrator.py --agent itinerary-planner
python3 orchestrator.py --dc-only    # 只啟動 Discord Bot
python3 orchestrator.py --no-dc      # 跑規劃但不發 Discord
```

## 架構

```
orchestrator.py
├─ call_openclaw / call_gemini         LLM dispatcher
├─ web_search (Brave)                   搜尋
├─ search_and_answer                    搜尋 + 回答兩段流程
├─ run_agent / run_all_agents_parallel  單 agent / 全 agent 平行
├─ integrate_reports                    Team Lead 彙整
└─ run_discord_bot                      Discord Bot 互動模式
```

Agents 的 `SOUL.md` 放在 `agents/<agent-name>/SOUL.md`，缺檔會用預設 system prompt。
