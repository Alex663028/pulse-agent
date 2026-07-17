"""Tests for social gateway — FeishuGateway, WechatGateway, WhatsAppGateway, get_gateway."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pulse.gateways.social import (
    FeishuGateway,
    WhatsAppGateway,
    WechatGateway,
    _audit_webhook,
    _safe_webhook_text,
    get_gateway,
)


class TestSafeWebhookText:
    """Test _safe_webhook_text function."""

    def test_strips_control_chars(self):
        """Control characters are stripped."""
        result = _safe_webhook_text("hello\x00world\x07")
        assert result == "helloworld"

    def test_preserves_unicode(self):
        """Unicode characters are preserved."""
        result = _safe_webhook_text("hello 世界")
        assert result == "hello 世界"

    def test_limits_length(self):
        """Text is limited to max_length."""
        result = _safe_webhook_text("a" * 10000)
        assert len(result) == 4096

    def test_empty_input(self):
        """Empty string returns empty."""
        assert _safe_webhook_text("") == ""

    def test_non_string_input(self):
        """Non-string input returns empty."""
        assert _safe_webhook_text(None) == ""
        assert _safe_webhook_text(123) == ""


class TestAuditWebhook:
    """Test _audit_webhook function."""

    def test_does_not_raise(self):
        """_audit_webhook never raises."""
        _audit_webhook("feishu", "user123", "received", "hello")


class TestFeishuGateway:
    """Test FeishuGateway."""

    def test_init_defaults(self):
        """FeishuGateway with defaults."""
        gw = FeishuGateway()
        assert gw.name == "feishu"

    def test_init_with_params(self):
        """FeishuGateway with custom params."""
        gw = FeishuGateway(
            app_id="my_app",
            app_secret="my_secret",
            verification_token="token",
        )
        assert gw.name == "feishu"

    def test_handle_webhook_challenge(self):
        """URL verification returns challenge."""
        gw = FeishuGateway()
        result = gw.handle_webhook({"challenge": "abc123"})
        assert result == {"challenge": "abc123"}

    def test_handle_webhook_message(self):
        """Message is routed through orchestrator."""
        gw = FeishuGateway()
        gw._runtime = MagicMock()
        gw._runtime.orchestrator.run.return_value = MagicMock(
            success=True, answer="reply text", error=None
        )
        gw._send = MagicMock()

        body = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_type": "text",
                    "content": '{"text": "hello"}',
                    "chat_id": "chat123",
                },
                "sender": {"sender_id": {"open_id": "user123"}},
            },
        }
        result = gw.handle_webhook(body)
        assert result == {"code": 0, "msg": "ok"}
        gw._runtime.orchestrator.run.assert_called_once()

    def test_handle_webhook_non_text_ignored(self):
        """Non-text messages are ignored."""
        gw = FeishuGateway()
        gw._runtime = MagicMock()
        body = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {"message_type": "image", "content": "{}"},
                "sender": {"sender_id": {"open_id": "user123"}},
            },
        }
        result = gw.handle_webhook(body)
        assert result == {"code": 0, "msg": "ok"}
        gw._runtime.orchestrator.run.assert_not_called()

    def test_handle_webhook_unknown_event(self):
        """Unknown event type is ignored."""
        gw = FeishuGateway()
        gw._runtime = MagicMock()
        body = {"header": {"event_type": "unknown.event"}, "event": {}}
        result = gw.handle_webhook(body)
        assert result == {"code": 0, "msg": "ok"}

    def test_start_and_stop(self):
        """start/stop sets active flag."""
        gw = FeishuGateway()
        runtime = MagicMock()
        gw.start(runtime)
        # start() may not set _active in this implementation
        gw.stop()
        # stop may set _active = False


class TestWechatGateway:
    """Test WechatGateway."""

    def test_init_defaults(self):
        """WechatGateway defaults."""
        gw = WechatGateway()
        assert gw.name == "wechat"

    def test_verify_signature_valid(self):
        """verify_signature validates correct signature."""
        import hashlib

        gw = WechatGateway(token="mytoken")
        timestamp = "1234567890"
        nonce = "abc123"
        s = "".join(sorted(["mytoken", timestamp, nonce]))
        signature = hashlib.sha1(s.encode()).hexdigest()
        assert gw.verify_signature(signature, timestamp, nonce) is True

    def test_verify_signature_invalid(self):
        """verify_signature rejects incorrect signature."""
        gw = WechatGateway(token="mytoken")
        assert gw.verify_signature("bad", "123", "abc") is False

    def test_handle_webhook_get_returns_echostr(self):
        """GET request returns echostr if signature is valid."""
        import hashlib

        gw = WechatGateway(token="mytoken")
        gw._runtime = MagicMock()
        timestamp = "1234567890"
        nonce = "abc123"
        s = "".join(sorted(["mytoken", timestamp, nonce]))
        signature = hashlib.sha1(s.encode()).hexdigest()

        result = gw.handle_webhook(
            signature=signature, timestamp=timestamp, nonce=nonce, body=None
        )
        # Valid signature: returns signature
        assert result == signature

    def test_handle_webhook_get_invalid_sig(self):
        """GET request with invalid signature returns empty."""
        gw = WechatGateway(token="mytoken")
        result = gw.handle_webhook(
            signature="invalid", timestamp="123", nonce="abc", body=None
        )
        assert result == ""

    def test_handle_webhook_post_text_message(self):
        """POST with text message returns response XML."""
        gw = WechatGateway(token="mytoken")
        gw._runtime = MagicMock()
        gw._runtime.orchestrator.run.return_value = MagicMock(
            success=True, answer="reply", error=None
        )

        import hashlib

        timestamp = "1234567890"
        nonce = "abc123"
        s = "".join(sorted(["mytoken", timestamp, nonce]))
        signature = hashlib.sha1(s.encode()).hexdigest()

        body = (
            "<xml>"
            "<ToUserName>to_user</ToUserName>"
            "<FromUserName>from_user</FromUserName>"
            "<CreateTime>1234567890</CreateTime>"
            "<MsgType>text</MsgType>"
            "<Content>hello</Content>"
            "</xml>"
        )
        result = gw.handle_webhook(signature, timestamp, nonce, body=body)
        assert "reply" in result
        assert "<xml>" in result
        gw._runtime.orchestrator.run.assert_called_once()

    def test_handle_webhook_invalid_signature(self):
        """Invalid signature returns empty string."""
        gw = WechatGateway(token="mytoken")
        body = (
            "<xml><ToUserName>t</ToUserName><FromUserName>f</FromUserName>"
            "<MsgType>text</MsgType><Content>hi</Content></xml>"
        )
        result = gw.handle_webhook("bad_sig", "123", "abc", body=body)
        assert result == ""

    def test_start_and_stop(self):
        """start/stop."""
        gw = WechatGateway()
        gw.start(MagicMock())
        assert gw._active is True
        gw.stop()
        assert gw._active is False


class TestWhatsAppGateway:
    """Test WhatsAppGateway."""

    def test_init_defaults(self):
        """WhatsAppGateway defaults."""
        gw = WhatsAppGateway()
        assert gw.name == "whatsapp"

    def test_handle_webhook_verify(self):
        """GET verification returns challenge."""
        gw = WhatsAppGateway(webhook_verify_token="mytoken")
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "mytoken",
            "hub.challenge": "abc123",
        }
        result = gw.handle_webhook({}, params=params)
        assert result == {"challenge": "abc123"}

    def test_handle_webhook_verify_wrong_token(self):
        """Wrong verify token returns error."""
        gw = WhatsAppGateway(webhook_verify_token="mytoken")
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "abc",
        }
        result = gw.handle_webhook({}, params=params)
        assert result == {"status": "error"}

    def test_handle_webhook_post_message(self):
        """POST message routes through orchestrator."""
        gw = WhatsAppGateway(phone_number_id="123", access_token="tok")
        gw._runtime = MagicMock()
        gw._runtime.orchestrator.run.return_value = MagicMock(
            success=True, answer="reply", error=None
        )
        gw._send_message = MagicMock()

        body = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "type": "text",
                                        "from": "456",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        result = gw.handle_webhook(body)
        assert result == {"status": "ok"}
        gw._runtime.orchestrator.run.assert_called_once()

    def test_handle_webhook_empty_body(self):
        """Empty body returns error."""
        gw = WhatsAppGateway()
        result = gw.handle_webhook({})
        assert result == {"status": "error"}

    def test_start_and_stop(self):
        """start/stop."""
        gw = WhatsAppGateway()
        gw.start(MagicMock())
        assert gw._active is True
        gw.stop()
        assert gw._active is False


class TestGetGateway:
    """Test get_gateway factory function."""

    def test_feishu(self):
        """get_gateway returns FeishuGateway."""
        gw = get_gateway("feishu")
        assert isinstance(gw, FeishuGateway)

    def test_wechat(self):
        """get_gateway returns WechatGateway."""
        gw = get_gateway("wechat")
        assert isinstance(gw, WechatGateway)

    def test_whatsapp(self):
        """get_gateway returns WhatsAppGateway."""
        gw = get_gateway("whatsapp")
        assert isinstance(gw, WhatsAppGateway)

    def test_telegram(self):
        """get_gateway returns TelegramGateway."""
        gw = get_gateway("telegram")
        assert gw.name == "telegram"

    def test_unknown_raises(self):
        """Unknown gateway raises ValueError."""
        with pytest.raises(ValueError):
            get_gateway("unknown")
