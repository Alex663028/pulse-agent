"""Tests for telegram and tui gateways."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pulse.gateways.base import Gateway, GatewayManager


class TestGatewayManager:
    """Test GatewayManager."""

    def test_init(self):
        """GatewayManager initialization."""
        mgr = GatewayManager()
        assert mgr.gateways == []

    def test_add_gateway(self):
        """adding a gateway."""
        mgr = GatewayManager()
        gw = MagicMock(spec=Gateway)
        mgr.add(gw)
        assert len(mgr.gateways) == 1

    def test_stop_all(self):
        """stop_all calls stop on each gateway."""
        mgr = GatewayManager()
        gw1 = MagicMock()
        gw2 = MagicMock()
        mgr.add(gw1)
        mgr.add(gw2)
        with patch("pulse.gateways.base.logger"):
            mgr.stop_all()
        gw1.stop.assert_called_once()
        gw2.stop.assert_called_once()


class TestTelegramGateway:
    """Test TelegramGateway interface."""

    def test_init(self):
        """TelegramGateway initialization."""
        from pulse.gateways.telegram import TelegramGateway

        gw = TelegramGateway(token="test:token")
        assert gw.name == "telegram"
        assert gw._token == "test:token"

    def test_init_no_token(self):
        """TelegramGateway with no token."""
        from pulse.gateways.telegram import TelegramGateway

        gw = TelegramGateway()
        assert gw._token == ""


class TestTuiGateway:
    """Test TuiGateway."""

    def test_init(self):
        """TuiGateway initialization."""
        from pulse.gateways.tui import TuiGateway

        gw = TuiGateway()
        assert gw.name == "tui"


class TestGatewayBase:
    """Test Gateway base class."""

    def test_gateway_abstract(self):
        """Gateway is abstract (cannot instantiate directly)."""
        with pytest.raises(TypeError):
            Gateway()
