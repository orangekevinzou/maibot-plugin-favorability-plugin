"""好感度插件配置模型。"""

from __future__ import annotations

from typing import ClassVar, List

from maibot_sdk import Field, PluginConfigBase


SUPPORTED_CONFIG_VERSION = "1.3.0"


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__: ClassVar[str] = "插件"
    __ui_icon__: ClassVar[str] = "package"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=False,
        description="是否启用插件",
        json_schema_extra={
            "hint": "关闭后插件会保持空闲",
            "label": "启用插件",
            "order": 0,
        },
    )
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="当前配置结构版本",
        json_schema_extra={
            "disabled": True,
            "hidden": True,
            "label": "配置版本",
            "order": 99,
        },
    )


class FavorabilityLLMConfig(PluginConfigBase):
    """LLM 判断服务配置 — 独立于麦麦主配置。"""

    __ui_label__: ClassVar[str] = "LLM 判断服务"
    __ui_icon__: ClassVar[str] = "brain"
    __ui_order__: ClassVar[int] = 0

    api_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        description="LLM API 地址",
        json_schema_extra={
            "hint": "支持兼容 OpenAI 格式的 API 端点",
            "label": "API 地址",
            "order": 0,
            "placeholder": "https://api.openai.com/v1/chat/completions",
        },
    )
    api_key: str = Field(
        default="",
        description="LLM API Key",
        json_schema_extra={
            "hint": "调用 LLM 所需的 API Key",
            "input_type": "password",
            "label": "API Key",
            "order": 1,
        },
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="模型名称",
        json_schema_extra={
            "hint": "用于好感度判断的 LLM 模型名称",
            "label": "模型名称",
            "order": 2,
            "placeholder": "gpt-4o-mini",
        },
    )
    temperature: float = Field(
        default=0.3,
        description="温度 (0~1)",
        json_schema_extra={
            "hint": "越低越确定，推荐 0.3 左右",
            "label": "温度",
            "order": 3,
            "step": 0.1,
        },
    )
    max_tokens: int = Field(
        default=200,
        description="最大输出 token 数",
        json_schema_extra={
            "hint": "单次 LLM 判断的最大输出长度",
            "label": "最大 Token",
            "order": 4,
        },
    )


class FavorabilityJudgeConfig(PluginConfigBase):
    """判断触发配置。"""

    __ui_label__: ClassVar[str] = "判断触发"
    __ui_icon__: ClassVar[str] = "sliders"
    __ui_order__: ClassVar[int] = 1

    judge_interval: int = Field(
        default=10,
        description="每 n 次对话触发 LLM 判断",
        json_schema_extra={
            "hint": "用户每发送多少条消息后自动触发一次好感度判断",
            "label": "判断间隔（条）",
            "order": 0,
        },
    )
    max_change_per_judge: int = Field(
        default=10,
        description="单次判断最大变化值",
        json_schema_extra={
            "hint": "单次 LLM 判断允许的最大好感度变化幅度",
            "label": "最大变化值",
            "order": 1,
        },
    )
    initial_score: int = Field(
        default=0,
        description="新用户初始好感度",
        json_schema_extra={
            "hint": "新用户首次出现时的好感度初始值",
            "label": "初始好感度",
            "order": 2,
        },
    )
    history_window: int = Field(
        default=20,
        description="发送给 LLM 的历史消息条数",
        json_schema_extra={
            "hint": "每次判断时取最近多少条消息作为上下文",
            "label": "历史窗口",
            "order": 3,
        },
    )


class FavorabilityAdminConfig(PluginConfigBase):
    """管理员配置。"""

    __ui_label__: ClassVar[str] = "管理员"
    __ui_icon__: ClassVar[str] = "shield"
    __ui_order__: ClassVar[int] = 2

    admin_users: List[str] = Field(
        default_factory=list,
        description="管理员用户 ID 列表",
        json_schema_extra={
            "hint": "拥有手动设置好感度权限的用户 ID",
            "label": "管理员列表",
            "order": 0,
            "placeholder": "请输入用户 ID",
        },
    )


class FavorabilityPluginConfig(PluginConfigBase):
    """好感度插件完整配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    llm: FavorabilityLLMConfig = Field(default_factory=FavorabilityLLMConfig)
    judge: FavorabilityJudgeConfig = Field(default_factory=FavorabilityJudgeConfig)
    admin: FavorabilityAdminConfig = Field(default_factory=FavorabilityAdminConfig)
