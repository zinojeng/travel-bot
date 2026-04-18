## 變更摘要
<!-- 一句話描述這個 PR 想解決什麼 -->

## 變更類型
- [ ] Bug fix
- [ ] 新功能 / 新 agent
- [ ] Refactor
- [ ] 文件 / prompt 調整
- [ ] CI / build 設定

## 影響範圍
<!-- 列出受影響的檔案與函式，例如 orchestrator.py::run_agent、AGENTS["transport-expert"] 等 -->

## 驗證
- [ ] `python3 -m py_compile orchestrator.py` 通過
- [ ] 本地跑過 `python3 orchestrator.py --no-dc --agent <對應 agent>`，輸出合理
- [ ] 若改動 Discord 發送邏輯，已手動驗證訊息完整送出（無截斷、無 429 遺失）
- [ ] 若改動 search/LLM 呼叫鏈，已確認 retry / timeout / error 訊息可讀

## PII / Secret 檢查
- [ ] `orchestrator.py` 沒有硬編姓名、訂位代號、API token
- [ ] 新增的環境變數都在 `.env.example` 補上，且沒有真實值
- [ ] commit diff 內不含 `.env`、`*.token`、`secrets.json` 等敏感檔

## 相關議題 / 上下文
<!-- 連結 issue、Codex review、討論串等 -->
