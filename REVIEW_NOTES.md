# Code Review Notes — orchestrator.py

這份檔案記錄本次對 `orchestrator.py` 所做的雙方審稿（Codex GPT-5.4 × Claude Opus 4.7）結果與修正決策。

## 審稿流程

1. Claude 透過 `tmux-bridge` 把檔案丟進平行 pane 的 Codex CLI
2. Codex 回傳 16 條發現 + 嚴重度排序
3. Claude 獨立做第二輪分析
4. 兩邊交集的高嚴重度項目全部修；Claude 獨家發現的較小項目一併收進來

## 兩邊共同發現（都判「必修」，已修）

| # | 問題 | Codex | Claude | 修正 |
|---|------|-------|--------|------|
| 1 | Discord 429 未處理、平行發送會撞 rate limit | H | H | `dc_send()` 加 `Retry-After` 重試 + `_DC_SEND_LOCK` 序列化 |
| 2 | Gateway health check 硬性依賴，只跑 Gemini 也會被卡死 | H | M | 依 `PRIMARY/RESEARCH/FAST_MODEL` 動態決定是否檢查 |
| 3 | `_is_failed_report()` 只看 `❌` 前綴過於脆弱 | M | M | 加入空字串/極短判斷與錯誤關鍵字檢查 |
| 4 | `search_and_answer()` 錯誤吞掉、靜默 fallback | M | M | 每步都 log；最終 LLM 失敗時回傳已蒐集到的搜尋結果 |
| 5 | `write_text()` 無 `encoding`、在 try 之外 | M | M | 顯式 `utf-8`，寫檔納入 try/except |
| 6 | 輸出被 `[:1800]` 又 `[:1900]` 雙重硬切 | M | L | 拿掉外層截斷，交給 `dc_send()` 切段 |
| 7 | `threading` import 與 `_discord_client` 為死碼 | L | L | 移除；同時重用 `threading.Lock()` 作 Discord 序列化 |
| 8 | 外部 API 無 retry/backoff | H | M | 用 `urllib3 Retry` 做共用 Session |

## Codex 獨家發現

- **敏感資料外洩（TRIP_CONTEXT 含姓名/訂位代號 AOQI83）**：改為從 `.env` 讀取，提供安全預設值
- **Prompt injection 硬化**：搜尋結果包 `<search_results>` 標籤 + system prompt 明確說明為資料非指令
- **`.env` parser 太簡化**：支援 `export`、引號包裹、行內註解
- **`call_gemini()` 未檢查 API key**：進函式就 fail fast
- **Run ID 隔離輸出**：評估後判為範圍外，暫未納入（涉及 CLI / `!status` API 變動）

## Claude 獨家發現

- **`asyncio.get_event_loop()` 在 Python 3.10+ 已 deprecated**：改 `asyncio.get_running_loop()`
- **Brave `search_lang="jp"` 非 ISO 639-1**：改 `ja`
- **SOUL.md `read_text()` 未指定 encoding**：顯式 `utf-8`

## 未採納（刻意保留原狀）

- **`PLAN_KEYWORDS` 子字串比對可能誤觸發**（Claude 的觀察）
  - 使用體驗上目前未造成問題；硬修可能反而誤殺使用者。
- **Run ID + `output/<run_id>/` 目錄化**（Codex 建議）
  - 牽動 `!status` / CLI 行為，範圍過大；單機用已夠用。
- **全面改寫為 `logging` 取代所有 `print()`**
  - 已加上 `logger = logging.getLogger("orchestrator")` 並在關鍵錯誤用 `logger.exception()`；
    其餘 `log()` / `print()` 留作輕量訊息，保持現有風格。

## 驗證

```bash
python3 -m py_compile orchestrator.py   # ✅ OK
grep -E "AOQI83|JX31[45]|曾|劉" orchestrator.py   # ✅ 0 matches
```
