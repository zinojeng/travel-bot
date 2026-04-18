#!/usr/bin/env python3
"""
🦞 OpenClaw Travel Agent — Multi-Agent Orchestrator
透過 OpenClaw Gateway (ChatGPT OAuth) / Gemini API 協調多個 Agent 平行工作，結果匯報到 Discord。

用法:
    python3 orchestrator.py              # 啟動完整規劃
    python3 orchestrator.py --agent itinerary  # 只跑行程規劃師
    python3 orchestrator.py --dc-only    # 只啟動 Discord Bot
"""

import os
import sys
import json
import asyncio
import argparse
import time
import threading
from pathlib import Path
from datetime import datetime

import requests

# --- 設定 ---
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

def load_env():
    """載入 .env 檔"""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

load_env()

OPENCLAW_HOST = os.environ.get("OPENCLAW_HOST", "127.0.0.1")
OPENCLAW_PORT = os.environ.get("OPENCLAW_PORT", "18789")
OPENCLAW_GATEWAY_URL = f"http://{OPENCLAW_HOST}:{OPENCLAW_PORT}"
OPENCLAW_GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "openclaw/default")
RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "openclaw/default")
FAST_MODEL = os.environ.get("FAST_MODEL", "gemini-3.1-flash-lite-preview")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


# ============================================================
# LLM API 呼叫
# ============================================================

def log(msg: str):
    """即時日誌（帶時間戳）"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _load_gateway_token() -> str:
    """從 ~/.openclaw/openclaw.json 讀取 Gateway auth token"""
    if OPENCLAW_GATEWAY_TOKEN:
        return OPENCLAW_GATEWAY_TOKEN
    try:
        config_path = Path.home() / ".openclaw" / "openclaw.json"
        with open(config_path) as f:
            config = json.load(f)
        return config.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return ""


def call_openclaw(model: str, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """透過 OpenClaw Gateway 呼叫 ChatGPT（OAuth 認證，免 API Key）"""
    log(f"📡 呼叫 OpenClaw Gateway: {model}")
    log(f"   Prompt 長度: {len(user_prompt)} 字元")
    start = time.time()

    token = _load_gateway_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 注入反委派指令，防止 Gateway agent 將任務轉發給子代理
    anti_delegation = (
        "IMPORTANT: You are a direct assistant. Do NOT delegate to sub-agents, "
        "do NOT spawn any tasks, do NOT forward to experts. Answer the question "
        "directly and completely by yourself. Never say you are forwarding, "
        "dispatching, or handing off to anyone."
    )
    full_system = f"{anti_delegation}\n\n{system_prompt}" if system_prompt else anti_delegation

    messages = [{"role": "system", "content": full_system}]
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192
    }
    try:
        resp = requests.post(
            f"{OPENCLAW_GATEWAY_URL}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=300
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["choices"][0]["message"]["content"]
        elapsed = time.time() - start
        log(f"✅ OpenClaw 回應完成！耗時 {elapsed:.1f} 秒，回應 {len(result)} 字元")
        return result
    except Exception as e:
        elapsed = time.time() - start
        log(f"❌ OpenClaw Gateway 錯誤（{elapsed:.1f}秒）: {e}")
        raise


def call_gemini(model: str, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """直接呼叫 Google AI Gemini API（OpenAI 相容端點）"""
    log(f"📡 呼叫 Gemini 直連: {model}")
    log(f"   Prompt 長度: {len(user_prompt)} 字元")
    start = time.time()

    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192
    }
    try:
        resp = requests.post(
            f"{GEMINI_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["choices"][0]["message"]["content"]
        elapsed = time.time() - start
        log(f"✅ Gemini 回應完成！耗時 {elapsed:.1f} 秒，回應 {len(result)} 字元")
        return result
    except Exception as e:
        elapsed = time.time() - start
        log(f"❌ Gemini API 錯誤（{elapsed:.1f}秒）: {e}")
        raise


def call_llm(model: str, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """統一 LLM 調度：gemini-* → Google AI 直連，其餘 → OpenClaw Gateway"""
    if model.startswith("gemini-"):
        return call_gemini(model, system_prompt, user_prompt, temperature)
    return call_openclaw(model, system_prompt, user_prompt, temperature)


# ============================================================
# 🔍 網路搜尋（Brave Search API）
# ============================================================

def web_search(query: str, max_results: int = 5) -> str:
    """搜尋引擎：Brave Search API"""
    if not BRAVE_API_KEY:
        log("❌ BRAVE_API_KEY 未設定，無法搜尋")
        return "（搜尋失敗：BRAVE_API_KEY 未設定）"

    log(f"🔍 Brave Search: {query}")
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results, "search_lang": "jp"},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        if not results:
            return "（搜尋無結果）"
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(
                f"[{i}] {r.get('title', '')}\n"
                f"    {r.get('description', '')}\n"
                f"    來源: {r.get('url', '')}"
            )
        log(f"🔍 Brave 找到 {len(results)} 筆結果")
        return "\n\n".join(formatted)
    except Exception as e:
        log(f"🔍 Brave Search 錯誤: {e}")
        return f"（搜尋失敗：{e}）"


def search_and_answer(model: str, system_prompt: str, user_question: str) -> str:
    """兩步流程：先搜尋 → 再用搜尋結果回答"""
    log("🧠 Step 1: 生成搜尋關鍵字...")

    # Step 1: 讓 AI 生成搜尋關鍵字
    search_prompt = f"""使用者問了以下問題，請生成 2-3 個最佳的搜尋關鍵字（用於搜尋引擎）。
只回傳關鍵字，每行一個，不要其他文字。優先用日文或英文關鍵字搜尋日本相關資訊。

使用者問題: {user_question}"""

    try:
        keywords_raw = call_llm(
            model, "", search_prompt, temperature=0.3
        )
        keywords = [k.strip() for k in keywords_raw.strip().split("\n") if k.strip()][:3]
        log(f"🔑 搜尋關鍵字: {keywords}")
    except Exception:
        keywords = [user_question[:50]]

    # Step 2: 執行搜尋
    log("🔍 Step 2: 執行網路搜尋...")
    all_results = []
    for kw in keywords:
        result = web_search(kw)
        if "搜尋無結果" not in result and "搜尋失敗" not in result:
            all_results.append(f"### 搜尋「{kw}」\n{result}")

    search_context = "\n\n".join(all_results) if all_results else "（無搜尋結果，請用你的知識回答）"

    # Step 3: 用搜尋結果回答
    log("💬 Step 3: 根據搜尋結果生成回答...")
    answer_prompt = f"""使用者問題: {user_question}

以下是網路搜尋結果，請根據這些最新資訊回答使用者的問題。
如果搜尋結果不足，也可以補充你的知識，但要標明哪些是搜尋到的、哪些是你的建議。

--- 搜尋結果 ---
{search_context}
--- 搜尋結果結束 ---

請用繁體中文回答，提供具體、實用的資訊。如有引用來源請附上。"""

    return call_llm(model, system_prompt, answer_prompt)


# ============================================================
# Discord 訊息（透過 Webhook / REST，供同步函數使用）
# ============================================================

_discord_client = None  # 由 run_discord_bot() 設定


def dc_send(text: str):
    """傳送訊息到 Discord（同步，用 REST API）"""
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        print(f"[DC 未設定] {text[:100]}...")
        return
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    # Discord 限制 2000 字元，自動分段
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        try:
            requests.post(url, headers=headers, json={"content": chunk}, timeout=30)
        except Exception as e:
            print(f"[DC Error] {e}")


def dc_send_file(filepath: str, caption: str = ""):
    """傳送檔案到 Discord"""
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    try:
        with open(filepath, "rb") as f:
            payload = {"content": caption} if caption else {}
            requests.post(url, headers=headers, data=payload,
                          files={"files[0]": (Path(filepath).name, f)}, timeout=60)
    except Exception as e:
        print(f"[DC File Error] {e}")


# ============================================================
# Agent 定義
# ============================================================

TRIP_CONTEXT = """
## 旅行資訊
- 日期: 2026/5/17 (日) — 5/22 (五)，6天5夜
- 人數: 4人家庭（曾耀賢、劉曼莉、曾筠竹林、曾惠瑜）
- 去程: 星宇航空 JX314, 09:30 RMQ台中 → 14:00 NRT成田
- 回程: 星宇航空 JX315, 16:30 NRT成田 → 19:10 RMQ台中
- 訂位代號: AOQI83
- 實際遊玩: 5/17下午 + 5/18-21全天 + 5/22上午

一律使用繁體中文回應。
"""

AGENTS = {
    "itinerary-planner": {
        "name": "🗺️ 行程規劃師",
        "model": RESEARCH_MODEL,
        "output_file": "itinerary.md",
        "soul_path": "agents/itinerary-planner/SOUL.md",
        "prompt": f"""
你是東京行程規劃專家。請為以下旅行規劃完整的每日行程表。

{TRIP_CONTEXT}

請產出詳細的每日行程，每天包含：
1. 時間表（幾點到幾點在哪裡）
2. 景點簡介與推薦理由
3. 預估門票費用（日圓）
4. 各景點之間的交通方式
5. 適合拍照的地點標記

注意：
- Day 1 下午才抵達，Day 6 中午前要到機場
- 同區域景點排同一天
- 每天 3-4 個主要景點，不要太趕
- 穿插購物與休息時間
- 檢查景點是否週一/二公休
"""
    },
    "transport-expert": {
        "name": "🚃 交通專家",
        "model": RESEARCH_MODEL,
        "output_file": "transport-guide.md",
        "soul_path": "agents/transport-expert/SOUL.md",
        "prompt": f"""
你是日本交通系統專家。請為以下旅行規劃最佳交通方案。

{TRIP_CONTEXT}

請提供：

1. **機場往返方案比較**（4人費用）
   - N'EX 成田特快
   - Skyliner
   - Access Express
   - 利木津巴士
   推薦最佳方案

2. **市區交通票券比較**
   - Tokyo Subway Ticket (24/48/72hr)
   - Suica/PASMO
   - 都營+Metro 一日券
   計算哪個最划算

3. **每日交通路線**
   - 配合可能的景點區域規劃最佳路線
   - 標注轉乘站與步行時間

4. **近郊交通**（如果安排鎌倉/箱根）
   - 適合的 pass
   - 來回時間估算

5. **實用提醒**
   - 尖峰時間避開建議
   - 末班車時間
   - 手機 app 推薦（乘換案內等）

所有費用標注 ¥ 日圓。
"""
    },
    "food-culture-advisor": {
        "name": "🍣 美食文化顧問",
        "model": RESEARCH_MODEL,
        "output_file": "food-culture-guide.md",
        "soul_path": "agents/food-culture-advisor/SOUL.md",
        "prompt": f"""
你是東京美食與文化體驗專家。請為以下旅行推薦餐廳與文化體驗。

{TRIP_CONTEXT}

請提供：

1. **每日餐廳推薦**（配合主要景點區域）
   - 每餐 2-3 個選項（平價/中價/高價）
   - 標注：店名、地址、預算範圍、營業時間
   - 是否需要預約
   - 推薦菜色

2. **必吃清單 Top 10**
   - 壽司/拉麵/天婦羅/燒肉/甜點等
   - 性價比最高的選擇

3. **文化體驗推薦**
   - 茶道/和服/溫泉
   - 築地外市場/豐洲市場
   - 5月特有活動（三社祭 5/16-18？）

4. **省錢吃法**
   - 便利商店早餐推薦
   - 百貨地下街便當
   - 午間套餐（ランチ）比晚餐便宜

5. **飲食注意事項**
   - 過敏/素食如何溝通
   - 餐廳禮儀
   - 小費文化（不用給）

所有預算標注 ¥ 日圓。
"""
    },
    "budget-manager": {
        "name": "💰 預算管理師",
        "model": RESEARCH_MODEL,
        "output_file": "budget-summary.md",
        "soul_path": "agents/budget-manager/SOUL.md",
        "prompt": f"""
你是旅行財務專家。請為以下旅行做完整預算規劃。

{TRIP_CONTEXT}

請提供：

1. **預算總覽表**（4人合計）
   | 項目 | 日圓 ¥ | 新台幣 NT$ |
   使用最新匯率（約 0.21-0.22 TWD/JPY）

2. **分項明細**
   - 機票（已訂，估算參考價）
   - 住宿 5 晚（推薦 3 個方案：省錢/舒適/享受）
   - 交通（機場+市區+近郊）
   - 餐飲（每人每日預算）
   - 景點門票
   - 購物/伴手禮
   - Wi-Fi/SIM卡
   - 旅遊保險
   - 備用金 (10%)

3. **每日預算分配**

4. **省錢攻略**
   - 免稅購物（Tax Free）門檻與流程
   - 信用卡海外刷卡回饋推薦
   - 住宿省錢技巧
   - 交通票券最佳組合
   - 便利商店活用法

5. **三種預算方案**
   - 💰 省錢版：每人 NT$_____
   - 💎 舒適版：每人 NT$_____
   - 👑 享受版：每人 NT$_____

所有金額同時標注 ¥ 和 NT$。
"""
    }
}


# ============================================================
# Agent 執行
# ============================================================

def run_agent(agent_key: str) -> str:
    """執行單一 Agent"""
    agent = AGENTS[agent_key]
    log(f"🦞 {agent['name']} 開始工作... (模型: {agent['model']})")

    # 讀取 SOUL.md 作為 system prompt
    soul_path = BASE_DIR / agent["soul_path"]
    if soul_path.exists():
        system_prompt = soul_path.read_text()
    else:
        system_prompt = f"你是{agent['name']}。一律使用繁體中文回應。"

    # 呼叫 API（嘗試帶搜尋）
    dc_send(f"🦞 {agent['name']} 開始工作中...")

    # 實際搜尋 + 生成報告
    start_time = time.time()
    dc_send(f"⏳ {agent['name']} 開始搜尋與分析...")

    try:
        # 先做網路搜尋，把結果注入 prompt
        log(f"🔍 {agent['name']}: 搜尋相關資訊...")
        search_queries = {
            "itinerary-planner": ["東京 2026年5月 景點推薦", "Tokyo May 2026 events", "東京 家族旅行 行程"],
            "transport-expert": ["成田機場 東京 交通 2026", "Tokyo Subway Ticket 2026 price", "東京 交通IC卡"],
            "food-culture-advisor": ["東京 美食推薦 2026", "Tokyo best restaurants family", "淺草 新宿 拉麵 壽司"],
            "budget-manager": ["東京旅行 預算 4人 2026", "TWD JPY exchange rate", "東京 住宿 家庭房 價格"],
        }
        queries = search_queries.get(agent_key, [f"東京旅行 {agent['name']}"])

        search_results = []
        for q in queries:
            sr = web_search(q, max_results=3)
            if "搜尋無結果" not in sr and "搜尋失敗" not in sr:
                search_results.append(f"### 搜尋「{q}」\n{sr}")

        search_context = "\n\n".join(search_results) if search_results else ""

        # 把搜尋結果加到 prompt 中
        enhanced_prompt = agent["prompt"]
        if search_context:
            enhanced_prompt += f"\n\n--- 以下是最新的網路搜尋結果，請參考 ---\n{search_context}\n--- 搜尋結果結束 ---\n"
            dc_send(f"🔍 {agent['name']} 已搜尋 {len(search_results)} 組關鍵字，正在分析...")
        else:
            dc_send(f"⚠️ {agent['name']} 搜尋結果不足，將以知識庫回答...")

        result = call_llm(
            model=agent["model"],
            system_prompt=system_prompt,
            user_prompt=enhanced_prompt
        )
    except Exception as e:
        error_msg = f"❌ {agent['name']} 發生錯誤: {e}"
        log(error_msg)
        dc_send(error_msg)
        return error_msg

    elapsed = time.time() - start_time

    # 儲存結果
    output_file = OUTPUT_DIR / agent["output_file"]
    header = f"# {agent['name']} 報告\n"
    header += f"> 產出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    header += f"> 模型: {agent['model']}\n"
    header += f"> 搜尋來源: {len(search_results)} 組\n"
    header += f"> 耗時: {elapsed:.1f} 秒\n\n"
    output_file.write_text(header + result)

    log(f"✅ {agent['name']} 完成！耗時 {elapsed:.1f}秒，已存檔: {output_file}")

    # 傳送到 Discord（摘要 + 完整檔案）
    dc_send(f"✅ {agent['name']} 完成！(耗時 {elapsed:.0f}秒)\n\n{result[:1800]}")
    dc_send_file(str(output_file), f"{agent['name']} 完整報告")

    return result


def run_all_agents_parallel():
    """平行執行所有 Agent"""
    import concurrent.futures

    dc_send(
        "🦞🇯🇵 *OpenClaw Travel Agent 啟動！*\n\n"
        "正在平行啟動 4 位 Agent：\n"
        "🗺️ 行程規劃師\n"
        "🚃 交通專家\n"
        "🍣 美食文化顧問\n"
        "💰 預算管理師\n\n"
        "請稍候，各 Agent 正在研究中..."
    )

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_agent, key): key
            for key in AGENTS
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = f"Error: {e}"
                print(f"❌ {key} failed: {e}")

    return results


def integrate_reports(results: dict) -> str:
    """Team Lead 整合所有報告"""
    print(f"\n{'='*50}")
    print("🦞 領隊整合師 開始整合報告...")
    print(f"{'='*50}")

    dc_send("🦞 領隊整合師正在整合所有報告...")

    # 組合所有報告
    all_reports = ""
    for key, result in results.items():
        agent = AGENTS[key]
        all_reports += f"\n\n## {agent['name']} 報告\n{result}\n"

    system_prompt = (BASE_DIR / "SOUL.md").read_text() if (BASE_DIR / "SOUL.md").exists() else ""

    integration_prompt = f"""
請整合以下 4 位 Agent 的報告，產出一份完整的日本旅行計畫書。

{TRIP_CONTEXT}

--- 各 Agent 報告 ---
{all_reports}
--- 報告結束 ---

請整合成一份結構清晰的最終行程，包含：
1. 每日行程總覽（時間 + 景點 + 交通 + 餐廳 + 費用）
2. 交通票券建議（最終推薦方案）
3. 預算總表
4. 行前準備清單
5. 緊急資訊（大使館、急救電話等）

格式要清楚易讀，適合列印或在手機上查看。
"""

    final_report = call_llm(
        model=PRIMARY_MODEL,
        system_prompt=system_prompt,
        user_prompt=integration_prompt,
        temperature=0.5
    )

    # 儲存最終報告
    final_file = OUTPUT_DIR / "final-travel-plan.md"
    header = f"# 🇯🇵 東京旅行計畫書 2026/5/17-22\n"
    header += f"> 由 OpenClaw Travel Agent Team 產出\n"
    header += f"> 整合時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    final_file.write_text(header + final_report)

    print(f"✅ 最終報告已產出: {final_file}")

    # 傳送到 Discord
    dc_send("🇯🇵✅ *最終旅行計畫書已完成！*")
    dc_send(final_report[:1800])
    dc_send_file(str(final_file), "🇯🇵 東京旅行計畫書 — 完整版")

    return final_report


# ============================================================
# Discord Bot（互動模式）
# ============================================================

def run_discord_bot():
    """啟動 Discord Bot 互動模式"""
    try:
        import discord
    except ImportError:
        print("❌ 請安裝 discord.py:")
        print("   pip3 install discord.py")
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    PREFIX = "!"

    # 規劃類關鍵字
    PLAN_KEYWORDS = [
        "規劃", "行程", "安排", "plan", "計畫", "計劃",
        "幫我排", "排行程", "排一下", "全部", "完整",
        "啟動", "開始規劃", "Agent", "agent",
        "出發", "旅行", "五天", "六天", "5天", "6天",
    ]

    def is_plan_request(msg: str) -> bool:
        return any(kw in msg for kw in PLAN_KEYWORDS)

    async def send_long(channel, text: str):
        """分段傳送長訊息（Discord 限 2000 字元）"""
        for i in range(0, len(text), 1900):
            await channel.send(text[i:i+1900])

    @client.event
    async def on_ready():
        log(f"🦞 Discord Bot 已上線: {client.user}")
        log(f"   FAST_MODEL: {FAST_MODEL}")
        log(f"   RESEARCH_MODEL: {RESEARCH_MODEL}")
        log("   按 Ctrl+C 停止")

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return

        content = message.content.strip()
        channel = message.channel

        # --- 指令處理 ---
        if content == f"{PREFIX}start" or content == f"{PREFIX}help":
            await channel.send(
                "🦞🇯🇵 **OpenClaw Travel Agent**\n\n"
                "指令：\n"
                f"`{PREFIX}plan` — 啟動完整旅行規劃（4 Agent 平行）\n"
                f"`{PREFIX}itinerary` — 只跑行程規劃\n"
                f"`{PREFIX}transport` — 只跑交通方案\n"
                f"`{PREFIX}food` — 只跑美食推薦\n"
                f"`{PREFIX}budget` — 只跑預算規劃\n"
                f"`{PREFIX}search 關鍵字` — 搜尋網路資訊\n"
                f"`{PREFIX}status` — 查看狀態\n\n"
                "直接傳訊息 = 自動搜尋網路 + AI 回答！"
            )
            return

        if content.startswith(f"{PREFIX}search "):
            query = content[len(f"{PREFIX}search "):].strip()
            if not query:
                await channel.send(f"用法: `{PREFIX}search 東京拉麵推薦`")
                return
            await channel.send(f"🔍 搜尋中: {query}")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, web_search, query)
            await send_long(channel, result)
            return

        if content == f"{PREFIX}plan":
            await channel.send("🦞 啟動完整規劃，4 位 Agent 平行工作中...\n預計需要 3-5 分鐘。")
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, run_all_agents_parallel)
            await loop.run_in_executor(None, integrate_reports, results)
            return

        if content in (f"{PREFIX}itinerary", f"{PREFIX}transport", f"{PREFIX}food", f"{PREFIX}budget"):
            agent_map = {
                f"{PREFIX}itinerary": "itinerary-planner",
                f"{PREFIX}transport": "transport-expert",
                f"{PREFIX}food": "food-culture-advisor",
                f"{PREFIX}budget": "budget-manager",
            }
            agent_key = agent_map[content]
            name = AGENTS[agent_key]["name"]
            await channel.send(f"🦞 啟動 {name}...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_agent, agent_key)
            return

        if content == f"{PREFIX}status":
            files = list(OUTPUT_DIR.glob("*.md"))
            if files:
                status = "📄 已產出報告：\n" + "\n".join(f"  - {f.name}" for f in files)
            else:
                status = "📭 尚未產出任何報告"
            await channel.send(status)
            return

        # --- 非指令：自然語言處理 ---
        if content.startswith(PREFIX):
            return  # 未知指令，忽略

        user_msg = content
        log(f"💬 收到訊息: {user_msg[:80]}...")

        # === 判斷是否為規劃類請求 ===
        if is_plan_request(user_msg):
            log("🎯 偵測到規劃類請求，啟動 Agent Pipeline！")
            await channel.send(
                "🦞 偵測到旅行規劃需求！\n\n"
                "正在啟動 4 位 Agent 平行工作：\n"
                "  🗺️ 行程規劃師 — 景點路線\n"
                "  🚃 交通專家 — 票券比較\n"
                "  🍣 美食顧問 — 餐廳推薦\n"
                "  💰 預算管理師 — 費用估算\n\n"
                "預計 3-5 分鐘，每位完成會即時回報！"
            )
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, run_all_agents_parallel)
                await channel.send("✅ 4 位 Agent 全部完成！正在整合最終報告...")
                await loop.run_in_executor(None, integrate_reports, results)
                await channel.send("🎉 最終旅行計畫書已完成！請查看上方報告。")
            except Exception as e:
                log(f"❌ Agent Pipeline 錯誤: {e}")
                await channel.send(f"❌ 規劃過程發生錯誤: {e}")
            return

        # === 一般問題 → 搜尋 + AI 回答 ===
        await channel.send(
            "🔍 搜尋網路 + 🤖 AI 分析中...\n"
            "Step 1: 生成搜尋關鍵字\n"
            "Step 2: 搜尋網路\n"
            "Step 3: 整合回答"
        )

        try:
            loop = asyncio.get_event_loop()
            soul = (BASE_DIR / "SOUL.md").read_text() if (BASE_DIR / "SOUL.md").exists() else ""

            log(f"🚀 啟動 search_and_answer 流程...")

            reply = await loop.run_in_executor(
                None,
                lambda: search_and_answer(
                    FAST_MODEL,
                    soul + "\n你是旅行助手。根據搜尋結果回答使用者問題。繁體中文。具體實用。引用來源。",
                    user_msg
                )
            )
            log(f"✅ 回覆完成，長度: {len(reply)} 字元")
            await send_long(channel, reply)
        except Exception as e:
            log(f"❌ 錯誤: {e}")
            await channel.send(f"❌ 發生錯誤: {e}")

    log("🦞 Discord Bot 啟動中...")
    log(f"   Channel ID: {DISCORD_CHANNEL_ID}")
    client.run(DISCORD_BOT_TOKEN)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="🦞 OpenClaw Travel Agent")
    parser.add_argument("--agent", choices=list(AGENTS.keys()),
                        help="只執行指定 Agent")
    parser.add_argument("--dc-only", action="store_true",
                        help="只啟動 Discord Bot 互動模式")
    parser.add_argument("--no-dc", action="store_true",
                        help="不傳送 Discord 訊息")
    args = parser.parse_args()

    # 檢查 OpenClaw Gateway 是否運行中
    try:
        token = _load_gateway_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = requests.get(f"{OPENCLAW_GATEWAY_URL}/v1/models", headers=headers, timeout=5)
        resp.raise_for_status()
        log(f"✅ OpenClaw Gateway 連線成功 ({OPENCLAW_GATEWAY_URL})")
    except Exception:
        print(f"❌ OpenClaw Gateway 無法連線（{OPENCLAW_GATEWAY_URL}）")
        print("   請確認 Gateway 已啟動：")
        print("   launchctl start ai.openclaw.gateway")
        print("   或先完成 OAuth 登入：")
        print("   openclaw models auth login --provider openai-codex")
        sys.exit(1)

    if args.no_dc:
        global DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
        DISCORD_BOT_TOKEN = ""
        DISCORD_CHANNEL_ID = ""

    if args.dc_only:
        if not DISCORD_BOT_TOKEN:
            print("❌ 請設定 DISCORD_BOT_TOKEN！")
            sys.exit(1)
        run_discord_bot()
        return

    if args.agent:
        # 只跑單一 Agent
        run_agent(args.agent)
    else:
        # 跑全部 Agent + 整合
        print("🦞🇯🇵 OpenClaw Travel Agent — 完整規劃模式")
        print(f"   模型: {RESEARCH_MODEL}")
        print(f"   輸出: {OUTPUT_DIR}")
        print()
        results = run_all_agents_parallel()
        integrate_reports(results)
        print()
        print("🎉 全部完成！")
        print(f"   報告目錄: {OUTPUT_DIR}")
        for f in OUTPUT_DIR.glob("*.md"):
            print(f"   📄 {f.name}")


if __name__ == "__main__":
    main()
