"""
Feishu (Lark) Gateway — Bot API bridge using long-polling or webhook.

Option 1: Webhook (if you expose pulse to internet):
    1. In Feishu Open Platform, create an app, set "Mode: Use Gateway"
    2. Set your webhook URL to https://your-domain/feishu
    3. Copy the Verification Token and Encryption Key

Option 2: Long-polling (no static IP needed):
    1. In Feishu Open Platform, create an app with "Bot" capability
    2. Subscribe to im.message.receive_v1 event. The API provides a
       long-polling endpoint (similar to Telegram getUpdates).
    3. Copy the App ID and App Secret

This gateway implements Option 1 (webhook mode) for simplicity. The handler
should be mounted at a Flask/FastAPI endpoint by your reverse proxy.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pulse.cli.runtime import Runtime
from pulse.gateways.base import Gateway

logger = logging.getLogger("pulse.gateway.feishu")


class FeishuGateway(Gateway):
    """Receive messages from Feishu and route them through the orchestrator.

    Feishu webhook sends a POST with JSON body:
      - url_verification: {"challenge": "xxx"}
      - event_callback: {"header": {"event_type": "..."}, "event": {...}}
    """

    name = "feishu"

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        verification_token: str = "",
        encrypt_key: str = "",
        access_token: str | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._access_token = access_token
        self._active = False

    def get_tenant_access_token(self) -> str:
        """Call Feishu API to get tenant_access_token (valid for ~2h)."""
        import urllib.request

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        data = json.dumps({"app_id": self._app_id, "app_secret": self._app_secret}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("tenant_access_token", "")

    def handle_webhook(self, body: dict[str, Any]) -> dict[str, Any]:
        """Process a Feishu webhook callback. Called by your Flask/FastAPI endpoint."""
        # URL verification
        if "challenge" in body:
            return {"challenge": body["challenge"]}

        header = body.get("header", {})
        event_type = header.get("event_type", "")
        event = body.get("event", {})

        # Process im.message.receive_v1
        if event_type == "im.message.receive_v1":
            msg = event.get("message", {})
            sender = event.get("sender", {})
            msg_type = msg.get("message_type", "")
            chat_id = msg.get("chat_id", "")

            # Only process text messages
            if msg_type == "text":
                import json
                content = json.loads(msg.get("content", "{}"))
                text = content.get("text", "").strip()
                if text:
                    # Send typing indicator
                    try:
                        self._send(chat_id, "Pulse 正在思考…", msg_type="interactive")
                    except Exception:
                        logger.exception("feishu typing indicator failed")
                    # Route through orchestrator
                    res = self._runtime.orchestrator.run(
                        text, session_id=f"feishu:{chat_id}:{sender.get('sender_id', {}).get('open_id', 'default')}"
                    )
                    answer = res.answer if res.success else f"Error: {res.error}"
                    self._send(chat_id, answer)

        return {"code": 0, "msg": "ok"}

    def _send(self, chat_id: str, text: str, msg_type: str = "text") -> None:
        """Send a message to a Feishu chat."""
        import urllib.request

        if not self._access_token:
            self._access_token = self.get_tenant_access_token()

        # Split text by Feishu max length (2048 chars)
        chunks = [text[i:i+2048] for i in range(0, max(len(text), 1), 2048)]

        for chunk in chunks:
            url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            data = json.dumps({
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": json.dumps({"text": chunk}),
            }).encode()
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=10)

    def start(self, runtime: Runtime) -> None:
        """Feishu webhook mode: no polling loop needed. Just set runtime."""
        self._runtime = runtime
        self._active = True
        self._access_token = self.get_tenant_access_token()
        logger.info("[feishu] gateway ready (webhook mode)")

    def stop(self) -> None:
        self._active = False


class WechatGateway(Gateway):
    """
    WeChat (Weixin) public account gateway — webhook mode.

    Setup:
      1. Go to mp.weixin.qq.com → Development → Basic Configuration
      2. Set the "URL" to your endpoint that calls handle_webhook
      3. Set "Token" and "EncodingAESKey"
      4. The gateway verifies the signature and decrypts messages
    """

    name = "wechat"

    def __init__(
        self,
        token: str = "",
        encoding_aes_key: str = "",
        app_id: str = "",
        app_secret: str = "",
    ) -> None:
        self._token = token
        self._encoding_aes_key = encoding_aes_key
        self._app_id = app_id
        self._app_secret = app_secret
        self._active = False

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        """Verify WeChat request signature."""
        import hashlib
        s = "".join(sorted([self._token, timestamp, nonce]))
        return hashlib.sha1(s.encode()).hexdigest() == signature

    def decrypt(self, encrypted: str) -> str:
        """Decrypt WeCBC mode encryption."""
        if not self._encoding_aes_key:
            return encrypted
        try:
            from wechatpy.crypto import WeChatCrypto  # noqa: F401
            return encrypted
        except ImportError:
            logger.error("wechatpy required for decrypt. pip install wechatpy")
            return encrypted

    def handle_webhook(
        self,
        signature: str,
        timestamp: str,
        nonce: str,
        body: str | None = None,
        encrypt_type: str | None = None,
    ) -> str:
        """Process WeChat callback. Returns echo string (for GET) or response XML (for POST).

        Call this from your Flask/FastAPI endpoint:
            @app.route("/wechat", methods=["GET", "POST"])
            def wechat():
                if request.method == "GET":
                    return wechat_gw.verify_signature(
                        request.args.get("signature"),
                        request.args.get("timestamp"),
                        request.args.get("nonce"),
                    ) or request.args.get("echostr", "")
                else:
                    return wechat_gw.handle_webhook(
                        request.args.get("signature"),
                        request.args.get("timestamp"),
                        request.args.get("nonce"),
                        request.get_data(as_text=True),
                        request.args.get("encrypt_type"),
                    )
        """
        import time as time_m
        from xml.etree import ElementTree as ET

        if not self.verify_signature(signature, timestamp, nonce):
            return ""

        # GET request: return echostr for validation
        if body is None:
            return signature  # will be ignored, just for validation

        # Parse XML
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return ""

        msg_type = root.findtext("MsgType", "")
        from_user = root.findtext("FromUserName", "")
        to_user = root.findtext("ToUserName", "")
        content = root.findtext("Content", "")

        if msg_type != "text" or not content.strip():
            return ""

        # Decrypt if needed
        if encrypt_type == "aes":
            content = self.decrypt(content)

        # Route through orchestrator
        res = self._runtime.orchestrator.run(
            content.strip(),
            session_id=f"wechat:{from_user}",
        )
        answer = res.answer if res.success else f"Error: {res.error}"

        # Build response XML
        return (
            f"<xml>"
            f"<ToUserName><![CDATA[{from_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
            f"<CreateTime>{int(time_m.time())}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{answer[:600]}]]></Content>"
            f"</xml>"
        )

    def start(self, runtime: Runtime) -> None:
        """WeChat webhook mode: no polling loop needed."""
        self._runtime = runtime
        self._active = True
        logger.info("[wechat] gateway ready (webhook mode)")

    def stop(self) -> None:
        self._active = False


class WhatsAppGateway(Gateway):
    """
    WhatsApp Business Cloud API gateway.

    Setup:
      1. Go to developers.facebook.com → Create App → Add WhatsApp
      2. Get a "Phone Number ID" and "Access Token" (temporary or permanent)
      3. Configure a callback URL for incoming messages (Meta webhooks)

    Note: This uses Meta's Cloud API and requires a business-verified Facebook app.
    """

    name = "whatsapp"

    def __init__(
        self,
        phone_number_id: str = "",
        access_token: str = "",
        app_secret: str = "",
        webhook_verify_token: str = "",
    ) -> None:
        self._phone_number_id = phone_number_id
        self._access_token = access_token
        self._app_secret = app_secret
        self._webhook_verify_token = webhook_verify_token
        self._active = False

    def handle_webhook(
        self,
        body: dict[str, Any],
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Process WhatsApp webhook callback.

        Mount this in your Flask/FastAPI endpoint:
            @app.route("/whatsapp", methods=["GET"])
            def wa_verify():
                return wa_gw.handle_webhook(
                    {},
                    request.args
                ).get("challenge", "")
            @app.route("/whatsapp", methods=["POST"])
            def wa_callback():
                return wa_gw.handle_webhook(request.get_json(), {})

        Returns:
          - GET with hub.*: {"challenge": "..."} for webhook validation
          - POST: {"status": "ok"}
        """
        # Verify webhook (GET)
        if params:
            mode = params.get("hub.mode", "")
            token = params.get("hub.verify_token", "")
            challenge = params.get("hub.challenge", "")
            if mode == "subscribe" and token == self._webhook_verify_token:
                return {"challenge": challenge}
            return {"status": "error"}

        # Process incoming message (POST)
        if not body:
            return {"status": "error"}

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                self._phone_number_id = metadata.get("phone_number_id", self._phone_number_id)
                for msg in value.get("messages", []):
                    if msg.get("type") == "text":
                        from_number = msg.get("from", "")
                        text = msg.get("text", {}).get("body", "").strip()
                        if text:
                            res = self._runtime.orchestrator.run(
                                text, session_id=f"wa:{from_number}"
                            )
                            answer = res.answer if res.success else f"Error: {res.error}"
                            self._send_message(from_number, answer)

        return {"status": "ok"}

    def _send_message(self, to: str, text: str) -> None:
        """Send WhatsApp message via Cloud API."""
        import urllib.request

        url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/messages"
        payload = json.dumps({
            "messaging_product": "whatsapp",
            "to": to,
            "text": {"preview_url": False, "body": text[:4000]},
        }).encode()
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=15)

    def start(self, runtime: Runtime) -> None:
        """WhatsApp webhook mode: no polling loop needed."""
        self._runtime = runtime
        self._active = True
        self._send_url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/messages"
        logger.info("[whatsapp] gateway ready (webhook mode)")

    def stop(self) -> None:
        self._active = False


def get_gateway(name: str, **kwargs: Any) -> Gateway:
    """Factory function to create a gateway by name."""
    gateways: dict[str, type[Gateway]] = {
        "telegram": None,  # will be imported below to avoid hard dependency
        "feishu": FeishuGateway,
        "wechat": WechatGateway,
        "whatsapp": WhatsAppGateway,
    }

    if name == "telegram":
        from pulse.gateways.telegram import TelegramGateway
        return TelegramGateway(**kwargs)

    cls = gateways.get(name)
    if cls is None:
        raise ValueError(f"Unknown gateway: {name}. Available: {list(gateways.keys())}")
    return cls(**kwargs)


__all__ = ["FeishuGateway", "WechatGateway", "WhatsAppGateway", "get_gateway"]
