"""Tests for pulse/net.py - HTTP utilities."""

from __future__ import annotations


from pulse.net import safe_parse_json


class TestSafeParseJson:
    def test_parse_valid_json(self):
        assert safe_parse_json('{"key": "value"}') == {"key": "value"}

    def test_parse_invalid_json(self):
        assert safe_parse_json("not json") == {}

    def test_parse_dict_passthrough(self):
        assert safe_parse_json({"key": "value"}) == {"key": "value"}

    def test_parse_list(self):
        assert safe_parse_json([1, 2, 3]) == {}

    def test_parse_empty_string(self):
        assert safe_parse_json("") == {}
