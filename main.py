"""
AI Receptionist — 本地服务AI接待员 PoC
基于FastAPI的Web聊天界面 + 对话引擎
"""
import os
import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from engine import ConversationEngine

load_dotenv()

app = FastAPI(title="AI Receptionist", version="0.1.0")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Initialize conversation engine
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
engine = ConversationEngine(llm_api_key=DEEPSEEK_API_KEY)

# In-memory conversation store (per session)
conversations: dict[str, ConversationEngine] = {}


def get_engine(session_id: str) -> ConversationEngine:
    """Get or create conversation engine for a session."""
    if session_id not in conversations:
        conversations[session_id] = ConversationEngine(llm_api_key=DEEPSEEK_API_KEY)
    return conversations[session_id]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Chat interface"""
    shop_name = engine.shop_config.get("shop_name", "AI接待员")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "shop_name": shop_name,
    })


@app.post("/api/chat")
async def chat(request: Request):
    """Handle chat messages."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not user_message:
        raise HTTPException(400, "消息不能为空")

    eng = get_engine(session_id)

    # Try LLM first, fall back to rule engine
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

    return JSONResponse(result)


@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "shop_name": engine.shop_config.get("shop_name", ""),
        "llm_configured": bool(DEEPSEEK_API_KEY),
        "services_count": len(engine.shop_config.get("services", [])),
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


@app.get("/api/conversation/{session_id}")
async def get_conversation(session_id: str):
    """Get conversation history for a session."""
    eng = get_engine(session_id)
    return {"session_id": session_id, "history": eng.get_conversation_log()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
