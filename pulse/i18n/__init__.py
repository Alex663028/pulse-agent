"""Internationalization (i18n) support for Pulse Agent.

Supports English (en) and Chinese (zh). Add more languages by adding entries to MESSAGES.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # Common
        "app_name": "Pulse Agent",
        "version": "Version",
        "welcome": "Welcome to Pulse Agent",
        "error": "Error",
        "success": "Success",
        "failed": "Failed",
        "cancel": "Cancel",
        "confirm": "Confirm",
        "loading": "Loading...",
        "no_data": "No data available",
        # Chat
        "chat_placeholder": "Type a message...",
        "chat_send": "Send",
        "chat_thinking": "Thinking...",
        "chat_error": "An error occurred while processing your request.",
        # Skills
        "skill_list": "Skills",
        "skill_install": "Install Skill",
        "skill_eval": "Evaluate Skill",
        "skill_promote": "Promote Skill",
        "skill_rollback": "Rollback Skill",
        "skill_candidate": "Candidate",
        "skill_promoted": "Promoted",
        "skill_quarantined": "Quarantined",
        "skill_deprecated": "Deprecated",
        # Memory
        "memory_recall": "Recall Memory",
        "memory_add": "Add Note",
        "memory_profile": "User Profile",
        # Settings
        "settings_title": "Settings",
        "settings_provider": "Provider",
        "settings_model": "Model",
        "settings_save": "Save Settings",
        # Auth
        "auth_login": "Log In",
        "auth_logout": "Log Out",
        "auth_username": "Username",
        "auth_password": "Password",
        "auth_permission_denied": "Permission Denied",
        # Audit
        "audit_log": "Audit Log",
        "audit_user": "User",
        "audit_action": "Action",
        "audit_resource": "Resource",
        "audit_result": "Result",
        "audit_time": "Time",
        # Self-evolution
        "evolve_title": "Self-Evolution",
        "evolve_analyze": "Analyze Patterns",
        "evolve_status": "Evolution Status",
        "evolve_proposal": "Proposal",
        "evolve_apply": "Apply",
    },
    "zh": {
        # Common
        "app_name": "Pulse Agent",
        "version": "版本",
        "welcome": "欢迎使用 Pulse Agent",
        "error": "错误",
        "success": "成功",
        "failed": "失败",
        "cancel": "取消",
        "confirm": "确认",
        "loading": "加载中...",
        "no_data": "暂无数据",
        # Chat
        "chat_placeholder": "输入消息...",
        "chat_send": "发送",
        "chat_thinking": "思考中...",
        "chat_error": "处理请求时发生错误。",
        # Skills
        "skill_list": "技能列表",
        "skill_install": "安装技能",
        "skill_eval": "评估技能",
        "skill_promote": "晋升技能",
        "skill_rollback": "回滚技能",
        "skill_candidate": "候选",
        "skill_promoted": "已晋升",
        "skill_quarantined": "已隔离",
        "skill_deprecated": "已废弃",
        # Memory
        "memory_recall": "回忆记忆",
        "memory_add": "添加笔记",
        "memory_profile": "用户画像",
        # Settings
        "settings_title": "设置",
        "settings_provider": "服务商",
        "settings_model": "模型",
        "settings_save": "保存设置",
        # Auth
        "auth_login": "登录",
        "auth_logout": "注销",
        "auth_username": "用户名",
        "auth_password": "密码",
        "auth_permission_denied": "权限不足",
        # Audit
        "audit_log": "审计日志",
        "audit_user": "用户",
        "audit_action": "操作",
        "audit_resource": "资源",
        "audit_result": "结果",
        "audit_time": "时间",
        # Self-evolution
        "evolve_title": "自我进化",
        "evolve_analyze": "分析模式",
        "evolve_status": "进化状态",
        "evolve_proposal": "提案",
        "evolve_apply": "应用",
    },
}


class I18n:
    """Simple i18n translator."""

    def __init__(self, lang: str = "en") -> None:
        self._lang = lang if lang in MESSAGES else "en"

    def t(self, key: str, default: Optional[str] = None) -> str:
        """Translate a key."""
        msg = MESSAGES.get(self._lang, {}).get(key)
        if msg:
            return msg
        # Fallback to English
        msg = MESSAGES.get("en", {}).get(key)
        return msg if msg is not None else (default or key)

    @property
    def lang(self) -> str:
        return self._lang

    @classmethod
    def supported_languages(cls) -> list[str]:
        return list(MESSAGES.keys())


__all__ = ["I18n", "MESSAGES"]
