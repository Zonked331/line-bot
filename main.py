# -*- coding: utf-8 -*-
"""
LINE 服事排班機器人 – 主程式（main.py）
升級支援 line-bot-sdk v3（2024+）
"""

import os
import json
import schedule
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, abort

# ✅ v3 模組引入
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, TextMessage, PushMessageRequest, ReplyMessageRequest
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.exceptions import InvalidSignatureError

# ============================================================
# 1. LINE Credentials
# ============================================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "YOUR_CHANNEL_SECRET")
TARGET_ID = os.getenv("TARGET_ID", "YOUR_USER_OR_GROUP_ID")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ============================================================
# 2. 路徑與名單設定
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LIST_CONFIG = {
    "hymn":      {"file": "hymn.csv",      "count": 2},
    "bread_bro": {"file": "bread_bro.csv", "count": 2},
    "bread_sis": {"file": "bread_sis.csv", "count": 2},
    "baking":    {"file": "baking.csv",    "count": 1},
    "sharing":   {"file": "sharing.csv",   "count": 1},
    "pianist":   {"file": "pianist.csv",   "count": 2},
    "topic":     {"file": "topic.csv",     "count": 1},
    "url":       {"file": "url.csv",       "count": 1},
}

STATE_FILE = DATA_DIR / "state.json"
THIS_WEEK_FILE = DATA_DIR / "this_week.json"
DEFAULT_STATE = {
    "indexes": {k: 0 for k in LIST_CONFIG},
    "override": None
}

# ============================================================
# 3. 公用函式
# ============================================================

def load_csv_list(key: str):
    fp = DATA_DIR / LIST_CONFIG[key]["file"]
    if not fp.exists():
        return []
    with fp.open(encoding="utf-8") as f:
        row = f.read().strip()
    return [x.strip() for x in row.split(",") if x.strip()]

def load_state():
    if not STATE_FILE.exists():
        save_state(DEFAULT_STATE)
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def load_this_week():
    if THIS_WEEK_FILE.exists():
        return json.loads(THIS_WEEK_FILE.read_text(encoding="utf-8"))
    return {}

def save_this_week(data):
    THIS_WEEK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def next_items(lst, start_idx, n):
    length = len(lst)
    return [lst[(start_idx + i) % length] for i in range(n)]

def advance_index(current, step, length):
    return (current + step) % length

# ============================================================
# 4. 名單輪替與重複處理
# ============================================================

def get_list_with_advance(key, state, advance=True):
    names = load_csv_list(key)
    if not names:
        return [], state
    idx = state["indexes"][key]
    count = LIST_CONFIG[key]["count"]
    picked = next_items(names, idx, count)
    if advance:
        state["indexes"][key] = advance_index(idx, count, len(names))
    return picked, state

def bump_one(name_list, names_pool, avoid_set):
    if not names_pool:
        return None
    cur = names_pool.index(name_list[0])
    for step in range(1, len(names_pool)):
        candidate = names_pool[(cur + step) % len(names_pool)]
        if candidate not in avoid_set and candidate not in name_list:
            return candidate
    return name_list[0]

def resolve_duplicates(hymn, bread_bro, sharing, topic, pianist, state):
    pool_bro = load_csv_list("bread_bro")
    for i, person in enumerate(bread_bro):
        if person in hymn:
            bread_bro[i] = bump_one([person], pool_bro, set(hymn + bread_bro))

    pool_sharing = load_csv_list("sharing")
    if sharing and topic and sharing[0] == topic[0]:
        sharing[0] = bump_one(sharing, pool_sharing, set(topic))

    pool_pianist = load_csv_list("pianist")
    if len(pianist) == 2 and pianist[0] == pianist[1]:
        pianist[1] = bump_one([pianist[1]], pool_pianist, set(pianist[:1]))

    return hymn, bread_bro, sharing, topic, pianist

# ============================================================
# 5. 特殊週判斷
# ============================================================

def is_first_monday_odd_month():
    today = datetime.now()
    return today.month % 2 == 1 and 1 <= today.day <= 7 and today.weekday() == 0

def is_special_week(state):
    if state["override"] == "special":
        return True
    if state["override"] == "normal":
        return False
    return is_first_monday_odd_month()

# ============================================================
# 6. 組合訊息
# ============================================================

def compose_message(state, advance=True):
    hymn, state = get_list_with_advance("hymn", state, advance)
    bread_bro, state = get_list_with_advance("bread_bro", state, advance)
    bread_sis, state = get_list_with_advance("bread_sis", state, advance)
    baking, state   = get_list_with_advance("baking",   state, advance)
    sharing, state  = get_list_with_advance("sharing",  state, advance)
    pianist, state  = get_list_with_advance("pianist",  state, advance)
    topic, state    = get_list_with_advance("topic",    state, advance)
    url, state      = get_list_with_advance("url",      state, advance)

    hymn, bread_bro, sharing, topic, pianist = resolve_duplicates(hymn, bread_bro, sharing, topic, pianist, state)

    if is_special_week(state):
        msg = f"分享：{sharing[0] if sharing else ''}\n司琴：（六）{pianist[0] if pianist else ''}"
    else:
        pianist_text = f"（六）{pianist[0]}　（日）{pianist[1]}" if len(pianist) == 2 else ""
        msg = (
            f"帶詩歌：{'　'.join(hymn)}\n"
            f"餅杯（弟兄）：{'　'.join(bread_bro)}\n"
            f"餅杯（姊妹）：{'　'.join(bread_sis)}\n"
            f"做餅：{baking[0] if baking else ''}\n"
            f"分享：{sharing[0] if sharing else ''}\n"
            f"司琴：{pianist_text}\n"
            f"專題分享：{topic[0] if topic else ''}\n"
            f"題目：{url[0] if url else ''}"
        )
    return msg, state

# ============================================================
# 7. 每週排班主程式
# ============================================================

def weekly_job():
    state = load_state()
    message, new_state = compose_message(state, advance=True)
    save_state(new_state)
    save_this_week({"text": message})
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(PushMessageRequest(to=TARGET_ID, messages=[TextMessage(text=message)]))
    except Exception as e:
        print(f"[ERROR] push_message failed: {e}\nMessage:\n{message}")
    else:
        print("[INFO] Weekly message sent.")


def start_scheduler():
    schedule.every().monday.at("09:00").do(weekly_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=start_scheduler, daemon=True).start()

# ============================================================
# 8. Webhook v3 handler
# ============================================================
app = Flask(__name__)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token

    def reply(msg):
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=msg)]))

    def push(msg):
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(PushMessageRequest(to=TARGET_ID, messages=[TextMessage(text=msg)]))

    if text.startswith("!status"):
        mode = "Special" if is_special_week(load_state()) else "Normal"
        reply(f"Current mode: {mode}")
    elif text.startswith("!resend"):
        week = load_this_week()
        msg = week.get("text", "No schedule")
        push(msg)
        reply("Resent.")
    else:
        reply("未來支援更多指令")

if __name__ == "__main__":
    if not THIS_WEEK_FILE.exists():
        weekly_job()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
