# `before/` — 審稿前的歷史快照

`before/orchestrator.py` 是 **2026-04-12 committed backup** 的 `orchestrator.py`（來自 `backup-20260412-0111/`），作為 Codex × Claude 雙方審稿前的歷史快照保留。

> 註：本次審稿開始前，實際被編輯的版本是 937 行（該版本已在 in-place 編輯中被覆寫），此處 871 行版本是最接近、且真正留下 commit-like 快照的上游版本。兩者之間的差異主要是 agent prompt 微調，與審稿修正方向無關。

要比較「review 前 vs review 後」的主要差異，請直接看：

- 根目錄的 `REVIEW_NOTES.md`（Codex × Claude 合併結論）
- `git log -p` 首次 commit 的 `orchestrator.py`（= 修正後）

## 若要 local 做 diff

```bash
diff -u before/orchestrator.py orchestrator.py | less
```
