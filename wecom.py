"""
AI Receptionist — 企业微信 (WeCom) 集成模块
处理企业微信回调消息、自动回复、消息加解密
"""
import os
import json
import hashlib
import time
import xml.etree.ElementTree as ET
from typing import Optional
from datetime import datetime
from pathlib import Path

# WeCom config (from env vars)
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")


class WeComHandler:
    """企业微信消息处理器"""

    def __init__(self, conversation_engine=None):
        self.engine = conversation_engine
        self._access_token = None
        self._token_expires = 0

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """验证企业微信回调URL（GET请求）"""
        if not WECOM_TOKEN:
            return "ERROR: WECOM_TOKEN not configured"

        # Simple signature verification
        sort_list = sorted([WECOM_TOKEN, timestamp, nonce, echostr])
        hash_str = "".join(sort_list)
        signature = hashlib.sha1(hash_str.encode("utf-8")).hexdigest()

        if signature == msg_signature:
            return echostr
        return "ERROR: Signature verification failed"

    async def handle_message(self, request_xml: str) -> Optional[str]:
        """处理企业微信消息（POST请求），返回XML回复"""
        try:
            root = ET.fromstring(request_xml)
            msg_type = root.find("MsgType").text
            from_user = root.find("FromUserName").text
            to_user = root.find("ToUserName").text

            if msg_type == "text":
                content = root.find("Content").text
                return await self._reply_text(from_user, to_user, content)

            elif msg_type == "event":
                event = root.find("Event").text
                if event == "subscribe":
                    return self._reply_text_sync(from_user, to_user,
                        "欢迎关注！我是AI智能客服，可以帮您：\n"
                        "1️⃣ 查询服务报价\n"
                        "2️⃣ 预约到店服务\n"
                        "3️⃣ 了解营业时间\n"
                        "4️⃣ 获取店铺地址\n\n"
                        "请直接输入您的问题，或回复对应数字。")
                elif event == "enter_agent":
                    return self._reply_text_sync(from_user, to_user,
                        "您好！欢迎来到我们的服务号。\n"
                        "请告诉我您需要什么帮助？")

            elif msg_type == "voice":
                # Voice messages - just acknowledge for now
                return self._reply_text_sync(from_user, to_user,
                    "抱歉，我暂时无法识别语音消息，请发送文字。")

            return None

        except Exception as e:
            print(f"[WeCom] Parse error: {e}")
            return None

    async def _reply_text(self, to_user: str, from_user: str, content: str) -> str:
        """异步回复文本消息"""
        if self.engine:
            result = self.engine.generate_response(content)
            reply_content = result.get("response", "抱歉，我暂时无法回答这个问题。")
        else:
            reply_content = f"收到：{content}"

        return self._build_xml_reply(to_user, from_user, reply_content)

    def _reply_text_sync(self, to_user: str, from_user: str, content: str) -> str:
        """同步回复文本消息"""
        return self._build_xml_reply(to_user, from_user, content)

    def _build_xml_reply(self, to_user: str, from_user: str, content: str) -> str:
        """构建XML回复"""
        timestamp = str(int(time.time()))
        return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""

    async def get_access_token(self) -> Optional[str]:
        """获取企业微信access_token（缓存机制）"""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        if not WECOM_CORP_ID or not WECOM_SECRET:
            return None

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": WECOM_CORP_ID, "corpsecret": WECOM_SECRET}
                )
                data = resp.json()
                if data.get("errcode") == 0:
                    self._access_token = data["access_token"]
                    self._token_expires = time.time() + data.get("expires_in", 7200) - 300
                    return self._access_token
        except Exception as e:
            print(f"[WeCom] Token error: {e}")
        return None

    async def send_message_to_user(self, user_id: str, content: str) -> bool:
        """主动发送消息给用户（需要access_token）"""
        token = await self.get_access_token()
        if not token:
            return False

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
                    json={
                        "touser": user_id,
                        "msgtype": "text",
                        "agentid": WECOM_AGENT_ID,
                        "text": {"content": content}
                    }
                )
                data = resp.json()
                return data.get("errcode") == 0
        except Exception as e:
            print(f"[WeCom] Send error: {e}")
            return False

    async def notify_boss_new_appointment(self, appointment: dict) -> bool:
        """通知老板有新预约"""
        msg = (
            f"📅 新预约通知\n\n"
            f"👤 客户：{appointment.get('customer_name', '未知')}\n"
            f"📞 电话：{appointment.get('customer_phone', '未知')}\n"
            f"🔧 服务：{appointment.get('service_type', '未指定')}\n"
            f"🚗 车型：{appointment.get('vehicle_info', '未提供')}\n"
            f"⏰ 时间：{appointment.get('preferred_time', '未指定')}\n"
            f"📝 备注：{appointment.get('notes', '无')}\n"
            f"📱 来源：{appointment.get('source', 'web')}"
        )
        # Send to configured boss user ID
        boss_id = os.getenv("WECOM_BOSS_USER_ID", "")
        if boss_id:
            return await self.send_message_to_user(boss_id, msg)
        return False


# Global instance
wecom_handler = WeComHandler()
