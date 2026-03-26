"""
AI Receptionist — 对话引擎
意图识别 + 回复生成，支持规则引擎和LLM双模式
"""
import json
import re
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge_base"


class ConversationEngine:
    def __init__(self, llm_api_key: str = ""):
        self.llm_api_key = llm_api_key
        self.shop_config = self._load_shop_config()
        self.conversation_history: list[dict] = []

    def _load_shop_config(self) -> dict:
        """Load shop config with fallback to default."""
        try:
            config_path = KNOWLEDGE_DIR / "shop_config.json"
            if config_path.exists():
                return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Engine] Config load error: {e}")
        
        # Fallback default config
        return {
            "shop_name": "AI智能客服",
            "greeting": "您好！欢迎来到我们的店铺，请问有什么可以帮您？",
            "fallback": "抱歉，这个问题我暂时无法回答，请拨打我们的电话咨询。",
            "contact": {
                "phone": "400-123-4567",
                "wechat": "shop_wechat",
                "address": "请到店咨询具体地址"
            },
            "business_hours": {
                "weekday": "08:00-18:00",
                "weekend": "09:00-17:00",
                "holiday": "10:00-16:00"
            },
            "services": [
                {"id": "svc1", "name": "常规保养", "price_range": "200-500", "duration": "1-2小时", "description": "机油更换、滤芯更换等"},
                {"id": "svc2", "name": "故障检修", "price_range": "100-1000", "duration": "视情况而定", "description": "故障诊断与维修"},
            ],
            "highlights": ["专业技师", "原厂配件", "质保服务"],
            "appointment_questions": ["您的姓名", "联系电话", "需要什么服务", "车型信息"]
        }

    def detect_intent(self, user_message: str) -> dict:
        """Detect user intent from message using keyword matching."""
        msg = user_message.lower().strip()

        # Appointment intent
        appointment_keywords = ["预约", "约", "什么时候", "能来", "到店", "排队", "挂号", "订"]
        if any(kw in msg for kw in appointment_keywords):
            return {"intent": "appointment", "confidence": 0.85}

        # Price inquiry
        price_keywords = ["多少钱", "价格", "费用", "收费", "报价", "价", "便宜", "贵"]
        if any(kw in msg for kw in price_keywords):
            # Check if asking about specific service
            for svc in self.shop_config.get("services", []):
                if svc["name"][:2] in msg or svc["id"] in msg:
                    return {"intent": "price_specific", "confidence": 0.9, "service": svc}
            return {"intent": "price_general", "confidence": 0.8}

        # Business hours
        hours_keywords = ["几点", "营业", "开门", "关门", "上班", "下班", "时间", "几点到几点"]
        if any(kw in msg for kw in hours_keywords):
            return {"intent": "business_hours", "confidence": 0.9}

        # Address / Location
        address_keywords = ["在哪", "地址", "怎么走", "位置", "导航", "地图", "地图"]
        if any(kw in msg for kw in address_keywords):
            return {"intent": "address", "confidence": 0.9}

        # Phone / Contact
        contact_keywords = ["电话", "联系", "号码", "手机", "微信"]
        if any(kw in msg for kw in contact_keywords):
            return {"intent": "contact", "confidence": 0.9}

        # Services list
        services_keywords = ["什么服务", "能修", "业务", "项目", "服务"]
        if any(kw in msg for kw in services_keywords):
            return {"intent": "services_list", "confidence": 0.85}

        # Greeting
        greeting_keywords = ["你好", "hi", "hello", "嗨", "在吗", "在不在"]
        if any(kw in msg for kw in greeting_keywords):
            return {"intent": "greeting", "confidence": 0.95}

        # Roadside assistance
        roadside_keywords = ["救援", "抛锚", "打不着", "没电", "拖车", "路上"]
        if any(kw in msg for kw in roadside_keywords):
            return {"intent": "roadside", "confidence": 0.85}

        return {"intent": "unknown", "confidence": 0.3}

    def generate_response(self, user_message: str) -> dict:
        """Generate response based on detected intent."""
        intent_info = self.detect_intent(user_message)
        intent = intent_info["intent"]

        # Log conversation
        self.conversation_history.append({
            "role": "user",
            "message": user_message,
            "intent": intent,
            "timestamp": datetime.now().isoformat()
        })

        response_text = self._build_response(intent, intent_info)
        quick_replies = self._get_quick_replies(intent)

        self.conversation_history.append({
            "role": "assistant",
            "message": response_text,
            "timestamp": datetime.now().isoformat()
        })

        return {
            "response": response_text,
            "intent": intent,
            "quick_replies": quick_replies,
            "timestamp": datetime.now().isoformat()
        }

    def _build_response(self, intent: str, intent_info: dict) -> str:
        """Build response text for a given intent."""
        shop = self.shop_config
        contact = shop.get("contact", {})
        hours = shop.get("business_hours", {})
        services = shop.get("services", [])

        if intent == "greeting":
            return shop.get("greeting", "您好！请问有什么可以帮您？")

        elif intent == "business_hours":
            return (
                f"🕐 营业时间：\n"
                f"• 工作日：{hours.get('weekday', '08:00-18:00')}\n"
                f"• 周末：{hours.get('weekend', '09:00-17:00')}\n"
                f"• 节假日：{hours.get('holiday', '10:00-16:00')}\n\n"
                f"📍 地址：{contact.get('address', '')}\n"
                f"📞 电话：{contact.get('phone', '')}"
            )

        elif intent == "address":
            addr = contact.get("address", "暂无地址信息")
            phone = contact.get("phone", "")
            map_link = contact.get("map_link", "")
            resp = f"📍 我们的地址：{addr}\n📞 预约电话：{phone}"
            if map_link:
                resp += f"\n🗺️ 导航链接：{map_link}"
            return resp

        elif intent == "contact":
            return (
                f"📞 联系方式：\n"
                f"• 电话：{contact.get('phone', '')}\n"
                f"• 微信：{contact.get('wechat', '')}\n"
                f"• 地址：{contact.get('address', '')}\n\n"
                f"随时欢迎来电咨询！"
            )

        elif intent == "price_general":
            lines = ["💰 我们的主要服务报价：\n"]
            for svc in services[:6]:
                lines.append(f"• {svc['name']}：¥{svc['price_range']}（{svc['duration']}）")
            lines.append(f"\n具体价格需要到店检测后确定，我们坚持先报价后维修！")
            return "\n".join(lines)

        elif intent == "price_specific":
            svc = intent_info.get("service", {})
            if svc:
                return (
                    f"💰 {svc['name']}报价：\n"
                    f"• 价格范围：¥{svc['price_range']}\n"
                    f"• 预计工时：{svc['duration']}\n"
                    f"• 服务内容：{svc['description']}\n\n"
                    f"具体价格需要到店检测后确定，您可以预约到店免费检测！"
                )
            return self._build_response("price_general", intent_info)

        elif intent == "services_list":
            lines = ["🔧 我们提供的服务：\n"]
            for svc in services:
                lines.append(f"• {svc['name']}：{svc['description']}")
            highlights = shop.get("highlights", [])
            if highlights:
                lines.append(f"\n✨ 我们的优势：")
                for h in highlights:
                    lines.append(f"  ✓ {h}")
            return "\n".join(lines)

        elif intent == "appointment":
            questions = shop.get("appointment_questions", ["您的姓名", "联系电话", "需要什么服务"])
            q_text = "\n".join([f"  {i+1}. {q}" for i, q in enumerate(questions)])
            return (
                f"📅 预约到店非常方便！请提供以下信息：\n\n{q_text}\n\n"
                f"您也可以直接拨打 {contact.get('phone', '')} 电话预约。"
            )

        elif intent == "roadside":
            return (
                f"🚨 道路救援服务：\n"
                f"• 服务范围：市区内\n"
                f"• 响应时间：30-60分钟\n"
                f"• 服务内容：搭电、换胎、拖车\n"
                f"• 价格：¥100-500（视距离和服务内容）\n\n"
                f"请立即拨打救援电话：{contact.get('phone', '')}\n"
                f"请告知您的位置和车型，我们马上安排！"
            )

        else:
            return shop.get("fallback", "抱歉，这个问题我暂时无法回答，请拨打我们的电话咨询。")

    def _get_quick_replies(self, intent: str) -> list[str]:
        """Get contextual quick reply suggestions."""
        replies = {
            "greeting": ["查报价", "预约到店", "营业时间", "地址在哪"],
            "price_general": ["预约到店", "其他服务", "营业时间"],
            "price_specific": ["预约到店", "其他报价", "营业时间"],
            "business_hours": ["预约到店", "查报价", "地址在哪"],
            "address": ["预约到店", "营业时间", "联系电话"],
            "contact": ["预约到店", "查报价", "地址在哪"],
            "services_list": ["查报价", "预约到店", "营业时间"],
            "appointment": ["查报价", "营业时间", "地址在哪"],
            "roadside": ["营业时间", "联系电话", "地址在哪"],
            "unknown": ["查报价", "预约到店", "营业时间", "联系电话"],
        }
        return replies.get(intent, replies["unknown"])

    async def generate_llm_response(self, user_message: str) -> Optional[str]:
        """Use LLM for more natural responses (optional enhancement)."""
        if not self.llm_api_key:
            return None

        shop_info = json.dumps(self.shop_config, ensure_ascii=False, indent=2)
        history_text = "\n".join(
            [f"{'用户' if h['role']=='user' else '客服'}: {h['message']}" 
             for h in self.conversation_history[-6:]]
        )

        system_prompt = f"""你是{self.shop_config.get('shop_name', '本店')}的AI智能客服。
请根据以下店铺信息回答客户问题，语气亲切专业。

店铺信息：
{shop_info}

对话历史：
{history_text}

注意：
1. 报价时说明是参考价格，实际以到店检测为准
2. 如果客户要预约，收集姓名、电话、车型、服务需求、到店时间
3. 如果问题超出范围，引导客户拨打电话
4. 回复简洁，不要超过200字"""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.5,
                        "max_tokens": 512,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    def get_conversation_log(self) -> list[dict]:
        """Return full conversation history."""
        return self.conversation_history
