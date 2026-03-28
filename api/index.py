"""
AI Receptionist - Vercel Serverless Entry Point (v3 - Pure Flask)
Self-contained Flask app. No FastAPI/Jinja2/yaml/dotenv/SQLAlchemy deps.
Definitive fix for Vercel Python 500 errors.
"""
import os
import json
import sqlite3
import re
import hashlib
import uuid
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response

app = Flask(__name__)
DB_PATH = "/tmp/ai_receptionist.db"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# WeCom config
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_AES_KEY = os.getenv("WECOM_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")

# Shop config defaults
SHOP_CONFIG = {
    "shop_name": "AI智能接待",
    "services": [
        {"name": "常规检查", "price": "免费", "duration": "30分钟"},
        {"name": "深度服务", "price": "面议", "duration": "1-2小时"},
        {"name": "预约咨询", "price": "免费", "duration": "15分钟"},
    ],
    "business_hours": {"weekday": "09:00-18:00", "weekend": "10:00-16:00"},
    "contact": {"phone": "400-XXX-XXXX", "wechat": "shop_service"},
    "quick_replies": ["查报价", "预约到店", "营业时间", "联系电话"],
}

# Intent patterns
INTENT_PATTERNS = {
    "greeting": [r"你好|hello|hi|嗨|在吗|在不在"],
    "price": [r"价格|多少钱|收费|报价|费用|价目"],
    "appointment": [r"预约|约|到店|什么时候|时间"],
    "hours": [r"营业|几点|开门|关门|上班|工作时间"],
    "contact": [r"电话|联系|微信|地址|在哪"],
    "complaint": [r"投诉|不满意|差评|退款|态度"],
}

# ─── Database ───
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        service_type TEXT DEFAULT '',
        vehicle_info TEXT DEFAULT '',
        preferred_time TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        source TEXT DEFAULT 'web',
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        message TEXT NOT NULL,
        intent TEXT DEFAULT '',
        source TEXT DEFAULT 'web',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()
    conn.close()

init_db()

# ─── Intent Detection ───
def detect_intent(text: str) -> str:
    text_lower = text.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if re.search(p, text_lower):
                return intent
    return "unknown"

def generate_rule_response(text: str) -> dict:
    intent = detect_intent(text)
    if intent == "greeting":
        return {"response": f"您好！欢迎来到{SHOP_CONFIG['shop_name']}，请问有什么可以帮您？", "intent": intent, "quick_replies": SHOP_CONFIG["quick_replies"]}
    elif intent == "price":
        services = SHOP_CONFIG["services"]
        lines = [f"📋 {SHOP_CONFIG['shop_name']} 服务价目表："]
        for s in services:
            lines.append(f"  • {s['name']}：{s['price']}（约{s['duration']}）")
        lines.append("\n如需了解详情或预约，请告诉我~")
        return {"response": "\n".join(lines), "intent": intent, "quick_replies": ["预约到店", "联系电话"]}
    elif intent == "appointment":
        return {"response": "好的，请提供您的姓名和手机号，我帮您预约。您也可以告诉我希望到店的时间和服务类型。", "intent": intent, "quick_replies": []}
    elif intent == "hours":
        bh = SHOP_CONFIG["business_hours"]
        return {"response": f"🕐 营业时间：\n  工作日：{bh['weekday']}\n  周末：{bh['weekend']}", "intent": intent, "quick_replies": ["预约到店", "查报价"]}
    elif intent == "contact":
        c = SHOP_CONFIG["contact"]
        return {"response": f"📞 联系方式：\n  电话：{c['phone']}\n  微信：{c['wechat']}", "intent": intent, "quick_replies": ["预约到店", "查报价"]}
    elif intent == "complaint":
        return {"response": "非常抱歉给您带来了不好的体验！我已记录您的反馈，我们的负责人会尽快与您联系处理。如需紧急处理，请拨打我们的客服电话。", "intent": intent, "quick_replies": ["联系电话"]}
    else:
        return {"response": "感谢您的消息！请问您需要了解哪方面的信息？我可以帮您查报价、预约到店或解答疑问。", "intent": "unknown", "quick_replies": SHOP_CONFIG["quick_replies"]}

def call_deepseek(user_message: str) -> str:
    """Call DeepSeek for LLM response. Returns None on failure."""
    if not DEEPSEEK_API_KEY:
        return None
    try:
        import httpx
        system_prompt = f"""你是{SHOP_CONFIG['shop_name']}的AI接待员。友好、专业地回答客户问题。
服务项目：{json.dumps(SHOP_CONFIG['services'], ensure_ascii=False)}
营业时间：{json.dumps(SHOP_CONFIG['business_hours'], ensure_ascii=False)}
联系方式：{json.dumps(SHOP_CONFIG['contact'], ensure_ascii=False)}
请用简洁的中文回复，控制在100字以内。"""
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ], "temperature": 0.7, "max_tokens": 512},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None

def persist_conversation(session_id: str, role: str, message: str, intent: str = "", source: str = "web"):
    try:
        conn = get_db()
        conn.execute("INSERT INTO conversations (session_id,role,message,intent,source) VALUES (?,?,?,?,?)",
                     (session_id, role, message, intent, source))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ─── HTML ───
CHAT_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SHOP_NAME</title>
<style>body{font-family:system-ui;max-width:600px;margin:0 auto;padding:20px;background:#f5f5f5}
.chat{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.msg{margin:8px 0;padding:10px 14px;border-radius:8px;max-width:80%}
.bot{background:#e3f2fd;margin-right:auto}.user{background:#4caf50;color:#fff;margin-left:auto;text-align:right}
input{width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box}
button{margin-top:8px;padding:10px 20px;background:#4caf50;color:#fff;border:none;border-radius:8px;cursor:pointer;width:100%}
.quick{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.quick button{width:auto;padding:6px 12px;font-size:13px;background:#e3f2fd;color:#1976d2}
nav{display:flex;gap:12px;margin-bottom:16px}nav a{color:#1976d2;text-decoration:none}</style>
</head><body>
<nav><a href="/">💬 聊天</a> | <a href="/dashboard">📊 看板</a></nav>
<div class="chat"><h2>🤖 SHOP_NAME</h2>
<div id="msgs"></div>
<div class="quick" id="quick"></div>
<input id="inp" placeholder="输入消息..." onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">发送</button></div>
<script>const M=document.getElementById('msgs'),I=document.getElementById('inp'),Q=document.getElementById('quick');
function add(t,c){const d=document.createElement('div');d.className='msg '+c;d.textContent=t;M.appendChild(d);M.scrollTop=M.scrollHeight}
function qr(r){Q.innerHTML='';r.forEach(t=>{const b=document.createElement('button');b.textContent=t;b.onclick=()=>{I.value=t;send()};Q.appendChild(b)})}
async function send(){const m=I.value.trim();if(!m)return;add(m,'user');I.value='';const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,session_id:'demo'})});const d=await r.json();add(d.response,'bot');if(d.quick_replies)qr(d.quick_replies)}
add('您好！欢迎来到SHOP_NAME，请问有什么可以帮您？','bot');
qr(['查报价','预约到店','营业时间','联系电话']);</script></body></html>""".replace("SHOP_NAME", SHOP_CONFIG["shop_name"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>老板看板 - AI接待员</title>
<style>
body{font-family:system-ui;max-width:900px;margin:0 auto;padding:20px;background:#f5f5f5}
h1{color:#333}h2{color:#555;margin-top:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:16px 0}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1);text-align:center}
.card .num{font-size:32px;font-weight:700;color:#4caf50}.card .label{color:#888;font-size:14px;margin-top:4px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid #eee}th{background:#f8f8f8;font-weight:600}
.status-pending{color:#ff9800}.status-confirmed{color:#2196f3}.status-completed{color:#4caf50}.status-cancelled{color:#999}
nav{display:flex;gap:12px;margin-bottom:16px}nav a{color:#1976d2;text-decoration:none}
</style></head><body>
<nav><a href="/">💬 聊天</a> | <a href="/dashboard">📊 看板</a></nav>
<h1>📊 老板看板</h1>
<div class="cards" id="cards"></div>
<h2>📋 最近预约</h2>
<table><thead><tr><th>ID</th><th>客户</th><th>电话</th><th>服务</th><th>状态</th><th>时间</th></tr></thead>
<tbody id="recent"></tbody></table>
<script>
async function load(){
const r=await fetch('/api/dashboard/stats');const d=await r.json();const s=d.summary||{};
document.getElementById('cards').innerHTML=
'<div class="card"><div class="num">'+(s.total_conversations||0)+'</div><div class="label">总对话数</div></div>'+
'<div class="card"><div class="num">'+(s.today_conversations||0)+'</div><div class="label">今日对话</div></div>'+
'<div class="card"><div class="num">'+(s.total_appointments||0)+'</div><div class="label">总预约</div></div>'+
'<div class="card"><div class="num">'+(s.pending_appointments||0)+'</div><div class="label">待确认</div></div>'+
'<div class="card"><div class="num">'+(s.completed_appointments||0)+'</div><div class="label">已完成</div></div>'+
'<div class="card"><div class="num">'+(s.conversion_rate||0)+'%</div><div class="label">转化率</div></div>';
const rows=(d.recent_appointments||[]).map(a=>'<tr><td>'+a.id+'</td><td>'+a.customer_name+'</td><td>'+(a.customer_phone||'')+'</td><td>'+(a.service_type||'未指定')+'</td><td class="status-'+a.status+'">'+a.status+'</td><td>'+new Date(a.created_at).toLocaleString('zh-CN')+'</td></tr>').join('');
document.getElementById('recent').innerHTML=rows||'<tr><td colspan="6">暂无预约</td></tr>';}
load();setInterval(load,30000);
</script></body></html>"""


# ─── Routes ───
@app.get("/")
def index():
    return CHAT_HTML

@app.get("/dashboard")
def dashboard():
    return DASHBOARD_HTML

@app.post("/api/chat")
def chat():
    body = request.get_json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")
    if not user_message:
        return jsonify({"error": "消息不能为空"}), 400

    persist_conversation(session_id, "user", user_message, source="web")

    # Try LLM first
    llm_response = call_deepseek(user_message)
    if llm_response:
        result = {"response": llm_response, "intent": "llm", "quick_replies": SHOP_CONFIG["quick_replies"], "timestamp": datetime.now().isoformat()}
    else:
        result = generate_rule_response(user_message)
        result["timestamp"] = datetime.now().isoformat()

    persist_conversation(session_id, "assistant", result["response"], result.get("intent", ""), "web")
    return jsonify(result)

@app.post("/api/appointments")
def create_appointment():
    body = request.get_json()
    required = ["customer_name", "customer_phone"]
    for f in required:
        if not body.get(f):
            return jsonify({"error": f"缺少必填字段: {f}"}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO appointments (customer_name,customer_phone,service_type,vehicle_info,preferred_time,notes,source) VALUES (?,?,?,?,?,?,?)",
            (body["customer_name"], body["customer_phone"], body.get("service_type", ""),
             body.get("vehicle_info", ""), body.get("preferred_time", ""), body.get("notes", ""), body.get("source", "web"))
        )
        conn.commit()
        appt_id = cur.lastrowid
        return jsonify({
            "id": appt_id, "customer_name": body["customer_name"],
            "customer_phone": body["customer_phone"],
            "service_type": body.get("service_type", ""), "status": "pending",
            "created_at": datetime.now().isoformat(),
            "message": "预约成功！我们会尽快联系您确认。"
        }), 201
    finally:
        conn.close()

@app.get("/api/appointments")
def list_appointments():
    status = request.args.get("status")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    conn = get_db()
    try:
        if status:
            rows = conn.execute("SELECT * FROM appointments WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                (status, limit, offset)).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM appointments WHERE status=?", (status,)).fetchone()[0]
        else:
            rows = conn.execute("SELECT * FROM appointments ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                (limit, offset)).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
        return jsonify({"total": total, "appointments": [dict(r) for r in rows]})
    finally:
        conn.close()

@app.put("/api/appointments/<int:appointment_id>")
def update_appointment(appointment_id):
    body = request.get_json()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not row:
            return jsonify({"error": "预约不存在"}), 404
        if "status" in body:
            valid = ["pending", "confirmed", "completed", "cancelled"]
            if body["status"] not in valid:
                return jsonify({"error": f"无效状态，可选: {valid}"}), 400
            conn.execute("UPDATE appointments SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (body["status"], appointment_id))
        if "notes" in body:
            conn.execute("UPDATE appointments SET notes=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (body["notes"], appointment_id))
        conn.commit()
        return jsonify({"id": appointment_id, "status": body.get("status", row["status"]), "updated_at": datetime.now().isoformat()})
    finally:
        conn.close()

@app.get("/api/dashboard/stats")
def dashboard_stats():
    conn = get_db()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        total_appt = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM appointments WHERE status='pending'").fetchone()[0]
        confirmed = conn.execute("SELECT COUNT(*) FROM appointments WHERE status='confirmed'").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM appointments WHERE status='completed'").fetchone()[0]
        today_appt = conn.execute("SELECT COUNT(*) FROM appointments WHERE created_at>=?", (today,)).fetchone()[0]
        total_conv = conn.execute("SELECT COUNT(*) FROM conversations WHERE role='user'").fetchone()[0]
        today_conv = conn.execute("SELECT COUNT(*) FROM conversations WHERE role='user' AND created_at>=?", (today,)).fetchone()[0]
        conv_rate = round(total_appt / total_conv * 100, 1) if total_conv > 0 else 0
        recent = conn.execute("SELECT * FROM appointments ORDER BY created_at DESC LIMIT 5").fetchall()
        return jsonify({
            "summary": {
                "total_appointments": total_appt, "pending_appointments": pending,
                "confirmed_appointments": confirmed, "completed_appointments": completed,
                "today_appointments": today_appt, "total_conversations": total_conv,
                "today_conversations": today_conv, "conversion_rate": conv_rate,
            },
            "recent_appointments": [dict(r) for r in recent],
        })
    finally:
        conn.close()

@app.get("/api/dashboard/daily")
def daily_stats(days: int = 7):
    conn = get_db()
    try:
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            next_date = (datetime.now() - timedelta(days=i-1)).strftime("%Y-%m-%d")
            conv = conn.execute("SELECT COUNT(*) FROM conversations WHERE role='user' AND created_at>=? AND created_at<?", (date, next_date)).fetchone()[0]
            appt = conn.execute("SELECT COUNT(*) FROM appointments WHERE created_at>=? AND created_at<?", (date, next_date)).fetchone()[0]
            results.append({"date": date, "conversations": conv, "appointments": appt})
        return jsonify({"daily_stats": list(reversed(results))})
    finally:
        conn.close()

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok", "version": "1.0.0-v3flask",
        "shop_name": SHOP_CONFIG["shop_name"],
        "llm_configured": bool(DEEPSEEK_API_KEY),
        "services_count": len(SHOP_CONFIG["services"]),
    })

@app.get("/api/services")
def services():
    return jsonify({
        "shop_name": SHOP_CONFIG["shop_name"],
        "services": SHOP_CONFIG["services"],
        "business_hours": SHOP_CONFIG["business_hours"],
        "contact": SHOP_CONFIG["contact"],
    })

# WeCom webhook (simplified)
@app.get("/wecom/callback")
def wecom_verify():
    msg_signature = request.args.get("msg_signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")
    echostr = request.args.get("echostr", "")
    if WECOM_TOKEN and echostr:
        # Simple verification
        return Response(echostr, content_type="text/plain")
    return Response("ERROR: not configured", status=403)

@app.post("/wecom/callback")
def wecom_message():
    # Simplified WeCom message handling
    return Response(content="success", content_type="text/plain")

# Vercel entry point
handler = app
