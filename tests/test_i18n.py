"""Tests for i18n (internationalization)."""

from __future__ import annotations


from pulse.i18n import I18n


class TestI18n:
    def test_english(self):
        i18n = I18n("en")
        assert i18n.t("welcome") == "Welcome to Pulse Agent"
        assert i18n.t("skill_list") == "Skills"

    def test_chinese(self):
        i18n = I18n("zh")
        assert i18n.t("welcome") == "欢迎使用 Pulse Agent"
        assert i18n.t("skill_list") == "技能列表"

    def test_fallback_to_english(self):
        i18n = I18n("zh")
        assert i18n.t("nonexistent_key", "Default") == "Default"

    def test_unsupported_lang_defaults_to_english(self):
        i18n = I18n("fr")
        assert i18n.t("welcome") == "Welcome to Pulse Agent"

    def test_supported_languages(self):
        assert "en" in I18n.supported_languages()
        assert "zh" in I18n.supported_languages()
