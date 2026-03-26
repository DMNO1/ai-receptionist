"""
AI Receptionist — 本地服务AI接待员 Phase 1 MVP
FastAPI Web聊天 + 预约管理 + 数据看板 + 企业微信回调
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path


from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from dotenv import load_dotenv
from sqlalchemy import func

from engine import ConversationEngine
from models import Appointment, Conversation, DailyStats, get_engine, init_db, get_session
from wecom import wecom_handler

load_dotenv()

# --- Database Setup ---
# Vercel serverless: use /tmp for writable storage
if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
    _tmp_db = "/tmp/ai_receptionist.db"
    DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{_tmp_db}")
else:
    DB_URL = os.getenv("DATABASE_URL", "sqlite:///ai_receptionist.db")
DB_ENABLED = True
db_engine = None

try:
    db_engine = get_engine(DB_URL)
    init_db(db_engine)
except Exception as e:
    print(f"[WARN] Database initialization failed: {e}")
    print("[WARN] Running in memory-only mode (no persistence)")
    DB_ENABLED = False

app = FastAPI(title="AI Receptionist", version="1.0.0")

BASE_DIR = Path(__file__).parent

# Conditional template/static mounting
templates = None
if (BASE_DIR / "templates").exists():
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
if (BASE_DIR / "static").exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Initialize conversation engine
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
engine = ConversationEngine(llm_api_key=DEEPSEEK_API_KEY)
wecom_handler.engine = engine

# In-memory conversation store (per session)
conversations: dict[str, ConversationEngine] = {}


def get_engine_session(session_id: str) -> ConversationEngine:
    """Get or create conversation engine for a session."""
    if session_id not in conversations:
        conversations[session_id] = ConversationEngine(llm_api_key=DEEPSEEK_API_KEY)
    return conversations[session_id]


def persist_conversation(session_id: str, role: str, message: str, intent: str = "", source: str = "web"):
    """Save conversation turn to database."""
    if not DB_ENABLED or not db_engine:
        return  # Memory-only mode, skip persistence
    try:
        db = get_session(db_engine)
        record = Conversation(
            session_id=session_id,
            role=role,
            message=message,
            intent=intent,
            source=source,
        )
        db.add(record)
        db.commit()
        db.close()
    except Exception as e:
        print(f"[DB] Conversation persist error: {e}")


# ==================== Pages ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Chat interface"""
    shop_name = engine.shop_config.get("shop_name", "AI接待员")
    if templates:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "shop_name": shop_name,
        })
    # Fallback inline HTML
    return HTMLResponse(_inline_chat_html(shop_name))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Boss dashboard page"""
    if templates:
        return templates.TemplateResponse("dashboard.html", {"request": request})
    return HTMLResponse(_inline_dashboard_html())


# ==================== Chat API ====================

@app.post("/api/chat")
async def chat(request: Request):
    """Handle chat messages (web interface)."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not user_message:
        raise HTTPException(400, "消息不能为空")

    eng = get_engine_session(session_id)

    # Persist user message
    persist_conversation(session_id, "user", user_message, source="web")

    # Try LLM first, fall back to rule engine
    intent_info = eng.detect_intent(user_message)
    llm_response = await eng.generate_llm_response(user_message)

    if llm_response:
        result = {
            "response": llm_response,
            "intent": "llm",
            "quick_replies": ["查报价", "预约到店", "营业时间", "联系电话"],
            "timestamp": datetime.now().isoformat()
        }
    else:
        result = eng.generate_response(user_message)

    # Persist assistant response
    persist_conversation(session_id, "assistant", result["response"], result.get("intent", ""), "web")

    return JSONResponse(result)


# ==================== Appointment API ====================

@app.post("/api/appointments")
async def create_appointment(request: Request):
    """Create a new appointment."""
    body = await request.json()

    required = ["customer_name", "customer_phone"]
    for field in required:
        if not body.get(field):
            raise HTTPException(400, f"缺少必填字段: {field}")

    # Memory-only mode fallback
    if not DB_ENABLED or not db_engine:
        import uuid
        result = {
            "id": str(uuid.uuid4())[:8],
            "customer_name": body["customer_name"],
            "customer_phone": body["customer_phone"],
            "service_type": body.get("service_type", ""),
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "message": "预约已记录（内存模式，重启后数据丢失）"
        }
        await wecom_handler.notify_boss_new_appointment(body)
        return JSONResponse(result, status_code=201)

    db = get_session(db_engine)
    try:
        appointment = Appointment(
            customer_name=body["customer_name"],
            customer_phone=body["customer_phone"],
            service_type=body.get("service_type", ""),
            vehicle_info=body.get("vehicle_info", ""),
            preferred_time=body.get("preferred_time", ""),
            notes=body.get("notes", ""),
            source=body.get("source", "web"),
            status="pending",
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)

        result = {
            "id": appointment.id,
            "customer_name": appointment.customer_name,
            "customer_phone": appointment.customer_phone,
            "service_type": appointment.service_type,
            "status": appointment.status,
            "created_at": appointment.created_at.isoformat(),
            "message": "预约成功！我们会尽快联系您确认。"
        }

        # Notify boss via WeCom
        await wecom_handler.notify_boss_new_appointment(body)

        return JSONResponse(result, status_code=201)
    finally:
        db.close()


@app.get("/api/appointments")
async def list_appointments(
    status: str = None,
    limit: int = 50,
    offset: int = 0
):
    """List appointments with optional status filter."""
    if not DB_ENABLED or not db_engine:
        return {"total": 0, "appointments": [], "note": "内存模式，无持久化数据"}

    db = get_session(db_engine)
    try:
        query = db.query(Appointment)
        if status:
            query = query.filter(Appointment.status == status)
        total = query.count()
        appointments = query.order_by(Appointment.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "appointments": [
                {
                    "id": a.id,
                    "customer_name": a.customer_name,
                    "customer_phone": a.customer_phone,
                    "service_type": a.service_type,
                    "vehicle_info": a.vehicle_info,
                    "preferred_time": a.preferred_time,
                    "status": a.status,
                    "source": a.source,
                    "notes": a.notes,
                    "created_at": a.created_at.isoformat(),
                }
                for a in appointments
            ]
        }
    finally:
        db.close()


@app.put("/api/appointments/{appointment_id}")
async def update_appointment(appointment_id: int, request: Request):
    """Update appointment status."""
    body = await request.json()
    db = get_session(db_engine)
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            raise HTTPException(404, "预约不存在")

        if "status" in body:
            valid_statuses = ["pending", "confirmed", "completed", "cancelled"]
            if body["status"] not in valid_statuses:
                raise HTTPException(400, f"无效状态，可选: {valid_statuses}")
            appointment.status = body["status"]

        if "notes" in body:
            appointment.notes = body["notes"]

        appointment.updated_at = datetime.now()
        db.commit()

        return {"id": appointment.id, "status": appointment.status, "updated_at": appointment.updated_at.isoformat()}
    finally:
        db.close()


# ==================== Dashboard API ====================

@app.get("/api/dashboard/stats")
async def dashboard_stats():
    """Get dashboard statistics."""
    if not DB_ENABLED or not db_engine:
        return {
            "summary": {
                "total_appointments": 0,
                "pending_appointments": 0,
                "confirmed_appointments": 0,
                "completed_appointments": 0,
                "today_appointments": 0,
                "week_appointments": 0,
                "total_conversations": 0,
                "today_conversations": 0,
                "conversion_rate": 0,
            },
            "service_breakdown": {},
            "source_breakdown": {},
            "recent_appointments": [],
            "note": "内存模式运行，数据不持久化"
        }

    db = get_session(db_engine)
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # Appointment stats
        total_appointments = db.query(Appointment).count()
        pending_appointments = db.query(Appointment).filter(Appointment.status == "pending").count()
        confirmed_appointments = db.query(Appointment).filter(Appointment.status == "confirmed").count()
        completed_appointments = db.query(Appointment).filter(Appointment.status == "completed").count()

        today_appointments = db.query(Appointment).filter(
            Appointment.created_at >= today
        ).count()

        week_appointments = db.query(Appointment).filter(
            Appointment.created_at >= week_ago
        ).count()

        # Conversation stats
        total_conversations = db.query(Conversation).filter(
            Conversation.role == "user"
        ).count()

        today_conversations = db.query(Conversation).filter(
            Conversation.role == "user",
            Conversation.created_at >= today
        ).count()

        # Conversion rate (appointments / conversations)
        conversion_rate = (
            round(total_appointments / total_conversations * 100, 1)
            if total_conversations > 0 else 0
        )

        # Service breakdown
        service_stats = db.query(
            Appointment.service_type,
            func.count(Appointment.id)
        ).group_by(Appointment.service_type).all()

        # Source breakdown
        source_stats = db.query(
            Appointment.source,
            func.count(Appointment.id)
        ).group_by(Appointment.source).all()

        # Recent appointments (last 5)
        recent = db.query(Appointment).order_by(
            Appointment.created_at.desc()
        ).limit(5).all()

        return {
            "summary": {
                "total_appointments": total_appointments,
                "pending_appointments": pending_appointments,
                "confirmed_appointments": confirmed_appointments,
                "completed_appointments": completed_appointments,
                "today_appointments": today_appointments,
                "week_appointments": week_appointments,
                "total_conversations": total_conversations,
                "today_conversations": today_conversations,
                "conversion_rate": conversion_rate,
            },
            "service_breakdown": {s[0] or "未指定": s[1] for s in service_stats},
            "source_breakdown": {s[0] or "未知": s[1] for s in source_stats},
            "recent_appointments": [
                {
                    "id": a.id,
                    "customer_name": a.customer_name,
                    "service_type": a.service_type,
                    "status": a.status,
                    "created_at": a.created_at.isoformat(),
                }
                for a in recent
            ]
        }
    finally:
        db.close()


@app.get("/api/dashboard/daily")
async def daily_stats(days: int = 7):
    """Get daily stats for the past N days."""
    if not DB_ENABLED or not db_engine:
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            results.append({"date": date, "conversations": 0, "appointments": 0})
        return {"daily_stats": list(reversed(results)), "note": "内存模式运行"}

    db = get_session(db_engine)
    try:
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            next_date = (datetime.now() - timedelta(days=i-1)).strftime("%Y-%m-%d")

            conv_count = db.query(Conversation).filter(
                Conversation.role == "user",
                Conversation.created_at >= date,
                Conversation.created_at < next_date
            ).count()

            appt_count = db.query(Appointment).filter(
                Appointment.created_at >= date,
                Appointment.created_at < next_date
            ).count()

            results.append({
                "date": date,
                "conversations": conv_count,
                "appointments": appt_count,
            })

        return {"daily_stats": list(reversed(results))}
    finally:
        db.close()


# ==================== WeCom Webhook ====================

@app.get("/wecom/callback")
async def wecom_verify(msg_signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = ""):
    """企业微信回调URL验证（GET）"""
    result = wecom_handler.verify_url(msg_signature, timestamp, nonce, echostr)
    if result.startswith("ERROR"):
        raise HTTPException(403, result)
    return Response(content=result, media_type="text/plain")


@app.post("/wecom/callback")
async def wecom_message(request: Request):
    """企业微信消息回调（POST）"""
    body = await request.body()
    xml_str = body.decode("utf-8")

    reply = await wecom_handler.handle_message(xml_str)
    if reply:
        return Response(content=reply, media_type="application/xml")
    return Response(content="success", media_type="text/plain")


# ==================== Health & Config ====================

@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "shop_name": engine.shop_config.get("shop_name", ""),
        "llm_configured": bool(DEEPSEEK_API_KEY),
        "services_count": len(engine.shop_config.get("services", [])),
        "database": "connected" if DB_ENABLED else "memory-only",
    }


@app.get("/api/services")
async def services():
    """List available services."""
    return {
        "shop_name": engine.shop_config.get("shop_name", ""),
        "services": engine.shop_config.get("services", []),
        "business_hours": engine.shop_config.get("business_hours", {}),
        "contact": engine.shop_config.get("contact", {}),
    }


# ==================== Inline HTML Fallbacks ====================

def _inline_chat_html(shop_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{shop_name}</title>
<style>body{{font-family:system-ui;max-width:600px;margin:0 auto;padding:20px;background:#f5f5f5}}
.chat{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
.msg{{margin:8px 0;padding:10px 14px;border-radius:8px;max-width:80%}}
.bot{{background:#e3f2fd;margin-right:auto}}.user{{background:#4caf50;color:#fff;margin-left:auto;text-align:right}}
input{{width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box}}
button{{margin-top:8px;padding:10px 20px;background:#4caf50;color:#fff;border:none;border-radius:8px;cursor:pointer;width:100%}}
.quick{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}}
.quick button{{width:auto;padding:6px 12px;font-size:13px;background:#e3f2fd;color:#1976d2}}
nav{{display:flex;gap:12px;margin-bottom:16px}}
nav a{{color:#1976d2;text-decoration:none}}</style>
</head><body>
<nav><a href="/">💬 聊天</a> | <a href="/dashboard">📊 看板</a></nav>
<div class="chat"><h2>🤖 {shop_name}</h2>
<div id="msgs"></div>
<div class="quick" id="quick"></div>
<input id="inp" placeholder="输入消息..." onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">发送</button></div>
<script>const M=document.getElementById('msgs'),I=document.getElementById('inp'),Q=document.getElementById('quick');
function add(t,c){{const d=document.createElement('div');d.className='msg '+c;d.textContent=t;M.appendChild(d);M.scrollTop=M.scrollHeight}}
function qr(r){{Q.innerHTML='';r.forEach(t=>{{const b=document.createElement('button');b.textContent=t;b.onclick=()=>{{I.value=t;send()}};Q.appendChild(b)}})}}
async function send(){{const m=I.value.trim();if(!m)return;add(m,'user');I.value='';const r=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:m,session_id:'demo'}})}});const d=await r.json();add(d.response,'bot');if(d.quick_replies)qr(d.quick_replies)}}
add('您好！欢迎来到{shop_name}，请问有什么可以帮您？','bot');
qr(['查报价','预约到店','营业时间','联系电话']);</script></body></html>"""


def _inline_dashboard_html() -> str:
    return """<!DOCTYPE html>
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
.loading{color:#999;padding:20px;text-align:center}
</style></head><body>
<nav><a href="/">💬 聊天</a> | <a href="/dashboard">📊 看板</a></nav>
<h1>📊 老板看板</h1>
<div class="cards" id="cards"><div class="loading">加载中...</div></div>
<h2>📋 最近预约</h2>
<table><thead><tr><th>ID</th><th>客户</th><th>服务</th><th>状态</th><th>时间</th></tr></thead>
<tbody id="recent"><tr><td colspan="5" class="loading">加载中...</td></tr></tbody></table>
<script>
async function load(){
try{
const r=await fetch('/api/dashboard/stats');const d=await r.json();const s=d.summary;
document.getElementById('cards').innerHTML=`
<div class="card"><div class="num">${s.total_conversations}</div><div class="label">总对话数</div></div>
<div class="card"><div class="num">${s.today_conversations}</div><div class="label">今日对话</div></div>
<div class="card"><div class="num">${s.total_appointments}</div><div class="label">总预约</div></div>
<div class="card"><div class="num">${s.pending_appointments}</div><div class="label">待确认</div></div>
<div class="card"><div class="num">${s.completed_appointments}</div><div class="label">已完成</div></div>
<div class="card"><div class="num">${s.conversion_rate}%</div><div class="label">转化率</div></div>`;
const rows=d.recent_appointments.map(a=>`<tr><td>${a.id}</td><td>${a.customer_name}</td><td>${a.service_type||'未指定'}</td><td class="status-${a.status}">${a.status}</td><td>${new Date(a.created_at).toLocaleString('zh-CN')}</td></tr>`).join('');
document.getElementById('recent').innerHTML=rows||'<tr><td colspan="5">暂无预约</td></tr>';
}catch(e){document.getElementById('cards').innerHTML='<div class="loading">加载失败: '+e.message+'</div>'}}
load();setInterval(load,30000);
</script></body></html>"""


# Vercel serverless handler
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
