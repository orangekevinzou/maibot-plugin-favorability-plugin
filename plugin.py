"""好感度插件主类。

提供好感度追踪系统：
- 每 n 次对话通过 LLM 自动判断好感度变化
- 支持自然语言与命令两种查询方式
- 管理员可手动调整好感度
- 好感度范围 -100~100，10 个等级
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from typing import Any, ClassVar, Dict, List, Optional

from maibot_sdk import Action, Command, HookHandler, MaiBotPlugin, Tool
from maibot_sdk.types import ActivationType, HookMode, HookOrder, ToolParameterInfo, ToolParamType

from .config import FavorabilityPluginConfig, SUPPORTED_CONFIG_VERSION
from .services import FavorabilityService, LLMJudgeService


class FavorabilityPlugin(MaiBotPlugin):
    """好感度插件主类。"""

    config_model: ClassVar[type] = FavorabilityPluginConfig

    def __init__(self) -> None:
        """初始化好感度插件。"""
        super().__init__()
        self._favorability_service: Optional[FavorabilityService] = None
        self._llm_service: Optional[LLMJudgeService] = None
        self._data_path: str = ""
        self._cache_path: str = ""
        self._logger: Optional[logging.Logger] = None
        self._debug_file = None
        self._pending_tasks: set = set()

    def _log(self, message: str) -> None:
        """统一日志输出：同时写入文件和使用 SDK logger。"""
        # 写入调试日志文件（确保无论如何都能看到输出）
        if self._debug_file:
            try:
                self._debug_file.write(message + "\n")
                self._debug_file.flush()
            except Exception:
                pass

        # 使用 SDK 提供的 logger
        if self._logger:
            self._logger.info(message)

        # 同时尝试使用 ctx.logger（主机日志系统）
        try:
            if hasattr(self, "ctx") and self.ctx and self.ctx.logger:
                self.ctx.logger.info(message)
        except Exception:
            pass

        # 直接 print 作为后备（确保输出可见）
        print(f"[FavorabilityPlugin] {message}", flush=True)

    async def on_load(self) -> None:
        """插件加载时初始化服务。"""
        self._logger = logging.getLogger("favorability_plugin")

        # 打开调试日志文件
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        debug_log_path = os.path.join(plugin_dir, "data", "debug.log")
        try:
            self._debug_file = open(debug_log_path, "w", encoding="utf-8")
        except Exception:
            pass

        self._log("=" * 60)
        self._log("好感度插件开始加载")

        if not self.config.plugin.enabled:
            self._log("好感度插件未启用，保持空闲状态")
            self._log("=" * 60)
            return

        # 确定数据文件路径
        self._data_path = os.path.join(plugin_dir, "data", "favorability.json")
        self._cache_path = os.path.join(plugin_dir, "data", "message_cache.json")
        self._log(f"数据文件路径: {self._data_path}")

        # 初始化好感度服务
        self._favorability_service = FavorabilityService(
            data_path=self._data_path,
            config=self.config.judge,
            logger=self._logger,
        )

        # 初始化 LLM 判断服务
        self._llm_service = LLMJudgeService(
            config=self.config.llm,
            logger=self._logger,
            llm_output_path=os.path.join(plugin_dir, "data", "llm_output.log"),
        )

        # 打印配置摘要
        self._log(
            f"判断间隔: 每 {self.config.judge.judge_interval} 条消息, "
            f"历史窗口: {self.config.judge.history_window}, "
            f"初始好感度: {self.config.judge.initial_score}, "
            f"LLM: {self.config.llm.model}, "
            f"管理员: {len(self.config.admin.admin_users)} 人, "
            f"已有用户: {len(self._favorability_service.get_all_scores())} 人"
        )
        self._log("好感度插件加载完成")
        self._log("=" * 60)

    async def on_unload(self) -> None:
        """插件卸载时清理。"""
        self._log("好感度插件已卸载")
        if self._debug_file:
            try:
                self._debug_file.close()
            except Exception:
                pass

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置更新后重新加载服务。

        Args:
            scope: 配置变更范围。
            config_data: 最新配置数据。
            version: 配置版本号。
        """
        if scope != "self":
            return

        self._log("收到配置更新通知")

        self.set_plugin_config(config_data)

        # 检查配置版本
        config_version = self.config.plugin.config_version
        if config_version != SUPPORTED_CONFIG_VERSION:
            self._log(f"配置版本不兼容: 当前为 {config_version}，要求 {SUPPORTED_CONFIG_VERSION}")
            return

        # 根据启用状态决定初始化或清理
        if self.config.plugin.enabled:
            if self._favorability_service is None:
                self._log("插件已启用，初始化服务")
                await self.on_load()
            else:
                self._favorability_service._config = self.config.judge
                self._llm_service._config = self.config.llm
                self._log("配置已热重载，服务参数已更新")
        else:
            self._favorability_service = None
            self._llm_service = None
            self._log("插件已禁用，服务已清理")

    # ===== 内部方法 =====

    def _require_services(self) -> bool:
        """检查服务是否已初始化。

        Returns:
            bool: 服务是否可用。
        """
        if not self.config.plugin.enabled:
            return False
        if self._favorability_service is None or self._llm_service is None:
            return False
        return True

    def _extract_message_text(self, message: Any) -> str:
        """从消息对象中提取纯文本内容。

        Args:
            message: 消息对象（dict 或对象）。

        Returns:
            str: 纯文本内容。
        """
        if isinstance(message, dict):
            # 按优先级尝试多种键名
            for key in ("processed_plain_text", "raw_message", "plain_text", "text"):
                value = message.get(key, "")
                if value and isinstance(value, str):
                    return value
            return ""
        elif hasattr(message, "processed_plain_text"):
            return message.processed_plain_text or ""
        elif hasattr(message, "raw_message"):
            return message.raw_message or ""
        elif hasattr(message, "plain_text"):
            return message.plain_text or ""
        return str(message) if message else ""

    def _extract_sender_id(self, message: Any, kwargs: Dict[str, Any]) -> str:
        """从消息对象和 kwargs 中提取发送者 ID。

        Args:
            message: 消息对象。
            kwargs: 处理器传入的关键字参数。

        Returns:
            str: 发送者 ID。
        """
        # 优先从 kwargs 获取（user_id 是 SDK 直接传入的）
        user_id = kwargs.get("user_id", "")
        if user_id:
            return str(user_id)

        # 尝试其他可能的键名
        for key in ("sender_id", "sender", "from_id", "from_user_id", "uid"):
            value = kwargs.get(key, "")
            if value:
                return str(value)

        # 从消息对象获取
        if isinstance(message, dict):
            # 尝试直接获取
            for key in ("user_id", "sender_id", "uid", "from_id"):
                value = message.get(key, "")
                if value:
                    return str(value)
            # 尝试从 sender 子对象获取
            sender = message.get("sender", {})
            if isinstance(sender, dict):
                for key in ("user_id", "uin", "id", "uid"):
                    value = sender.get(key, "")
                    if value:
                        return str(value)
            # 尝试从 message_info 获取
            message_info = message.get("message_info", {})
            if isinstance(message_info, dict):
                for key in ("user_id", "sender_id", "uid"):
                    value = message_info.get(key, "")
                    if value:
                        return str(value)
            return ""

        if hasattr(message, "sender"):
            sender = message.sender
            if hasattr(sender, "user_id"):
                return str(sender.user_id)
            if isinstance(sender, dict):
                return str(sender.get("user_id", "") or "")

        return ""

    # ===== Tool 组件 =====

    @Tool(
        "get_favorability",
        description="查询指定用户的好感度信息，包括分数、等级和描述。当用户询问'好感度'、'喜欢'、'讨厌'、'关系'等相关问题时调用此工具。",
        parameters=[
            ToolParameterInfo(
                name="user_id",
                param_type=ToolParamType.STRING,
                description="要查询的用户 ID，如果不提供则查询当前对话用户",
                required=False,
            ),
        ],
    )
    async def handle_get_favorability(self, user_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """查询好感度工具 — 结果注入 LLM 上下文。"""
        if not self._require_services():
            return {"success": False, "content": "好感度插件未启用"}

        target_id = user_id or kwargs.get("sender_id", "")
        if not target_id:
            return {"success": False, "content": "无法确定要查询的用户"}

        info = self._favorability_service.get_level(target_id)
        display_name = self._favorability_service.get_display_name(target_id)
        nickname = self._favorability_service.get_nickname(target_id)
        self._logger.info(f"[Tool] 查询好感度: user={target_id}, score={info['score']}, level={info['level_name']}")
        return {
            "success": True,
            "user_id": target_id,
            "nickname": nickname,
            "display_name": display_name,
            "score": info["score"],
            "level_name": info["level_name"],
            "level_emoji": info["level_emoji"],
            "content": f"用户 {display_name} 的好感度为 {info['score']} 分，等级：{info['level_name']} {info['level_emoji']}",
        }

    @Tool(
        "get_all_favorability",
        description="查询所有用户的好感度排行榜。当用户询问'谁最喜欢我'、'好感度排名'、'最喜欢我的人'等问题时调用此工具。",
        parameters=[],
    )
    async def handle_get_all_favorability(self, **kwargs: Any) -> Dict[str, Any]:
        """查询所有用户好感度排行。"""
        if not self._require_services():
            return {"success": False, "content": "好感度插件未启用", "ranking": []}

        scores = self._favorability_service.get_all_scores()
        if not scores:
            return {"success": False, "content": "暂无好感度数据", "ranking": []}

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        ranking_lines = []
        for i, (uid, score) in enumerate(sorted_scores[:10]):
            level_name = FavorabilityService._score_to_level(score)
            display_name = self._favorability_service.get_display_name(uid)
            ranking_lines.append(f"{i + 1}. {display_name}: {score} 分 ({level_name})")

        self._logger.info(f"[Tool] 查询排行榜: 共 {len(scores)} 名用户")
        return {
            "success": True,
            "content": "好感度排行榜（前10名）：\n" + "\n".join(ranking_lines),
            "ranking": [{"user_id": uid, "nickname": self._favorability_service.get_nickname(uid), "display_name": self._favorability_service.get_display_name(uid), "score": score} for uid, score in sorted_scores[:10]],
        }

    # ===== Command 组件 =====

    @Command("favorability", description="查询自己的好感度", pattern=r"^/好感度$")
    async def handle_favorability_cmd(self, stream_id: str = "", **kwargs: Any):
        """查询自己的好感度命令。"""
        self._log(f"/好感度 命令被触发, stream_id={stream_id}, kwargs_keys={list(kwargs.keys())}")

        if not self._require_services():
            await self.ctx.send.text("好感度插件未启用", stream_id)
            return False, "插件未启用", False

        # 尝试从 kwargs 中提取消息对象
        message_obj = kwargs.get("_message", kwargs.get("message", kwargs.get("raw_message", {})))
        sender_id = self._extract_sender_id(message_obj, kwargs)
        self._log(f"/好感度: sender_id={sender_id}, message_obj_type={type(message_obj).__name__}")

        if not sender_id:
            self._log(f"/好感度: 无法确定用户身份, kwargs_keys={list(kwargs.keys())}")
            await self.ctx.send.text("无法确定你的用户身份", stream_id)
            return False, "无法确定用户身份", False

        info = self._favorability_service.get_level(sender_id)
        display_name = self._favorability_service.get_display_name(sender_id)
        message = (
            f"{info['level_emoji']} {display_name} 的好感度信息\n"
            f"━━━━━━━━━━━━━━\n"
            f"分数：{info['score']} / 100\n"
            f"等级：{info['level_name']}\n"
            f"━━━━━━━━━━━━━━"
        )
        await self.ctx.send.text(message, stream_id)
        self._log(f"/好感度: user={sender_id}, score={info['score']}")
        return True, "查询成功", True

    @Command("favorability_rank", description="查询好感度排行榜", pattern=r"^/好感度排行$")
    async def handle_favorability_rank_cmd(self, stream_id: str = "", **kwargs: Any):
        """查询好感度排行榜命令。"""
        if not self._require_services():
            await self.ctx.send.text("好感度插件未启用", stream_id)
            return False, "插件未启用", False

        scores = self._favorability_service.get_all_scores()
        if not scores:
            await self.ctx.send.text("暂无好感度数据", stream_id)
            return False, "暂无数据", False

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        lines = ["🏆 好感度排行榜", "━━━━━━━━━━━━━━"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, score) in enumerate(sorted_scores[:10]):
            medal = medals[i] if i < 3 else f"{i + 1}."
            level_name = FavorabilityService._score_to_level(score)
            display_name = self._favorability_service.get_display_name(uid)
            lines.append(f"{medal} {display_name}: {score} 分 ({level_name})")
        lines.append("━━━━━━━━━━━━━━")

        await self.ctx.send.text("\n".join(lines), stream_id)
        self._logger.info(f"[Command] /好感度排行: 共 {len(scores)} 名用户")
        return True, "查询成功", True

    @Command(
        "set_favorability",
        description="管理员手动设置用户好感度",
        pattern=r"^/设置好感度\s+(\S+)\s+(-?\d+)$",
    )
    async def handle_set_favorability_cmd(self, stream_id: str = "", **kwargs: Any):
        """管理员手动设置好感度命令。"""
        # 直接 print 确保输出可见
        print(f"[FavorabilityPlugin] /设置好感度 被触发, kwargs_keys={list(kwargs.keys())}", flush=True)
        self._log(f"/设置好感度 命令被触发, stream_id={stream_id}, kwargs_keys={list(kwargs.keys())}")

        if not self._require_services():
            await self.ctx.send.text("好感度插件未启用", stream_id)
            return False, "插件未启用", False

        # 尝试从 kwargs 中提取消息对象
        message_obj = kwargs.get("_message", kwargs.get("message", kwargs.get("raw_message", {})))
        self._log(f"/设置好感度: message_obj_type={type(message_obj).__name__}")
        if isinstance(message_obj, dict):
            self._log(f"/设置好感度: message_obj_keys={list(message_obj.keys())}")
        sender_id = self._extract_sender_id(message_obj, kwargs)
        self._log(f"/设置好感度: sender_id={sender_id}, admins={self.config.admin.admin_users}")

        # 权限检查
        if sender_id not in self.config.admin.admin_users:
            self._log(f"/设置好感度: 非管理员尝试操作, user={sender_id}, admins={self.config.admin.admin_users}")
            await self.ctx.send.text("⛔ 你没有权限执行此命令", stream_id)
            return False, "权限不足", False

        # 解析命令参数的多种方式
        target_id = ""
        score_str = ""

        # 方式1: 从 matched_groups 获取（SDK 传入的正则捕获组）
        matched_groups = kwargs.get("matched_groups", ())
        if matched_groups and len(matched_groups) >= 2:
            target_id = str(matched_groups[0])
            score_str = str(matched_groups[1])
            self._log(f"/设置好感度: 从 matched_groups 解析: target={target_id}, score={score_str}")

        # 方式2: 从 message.raw_message 中正则解析
        if not target_id or not score_str:
            raw_message = ""
            msg_obj = kwargs.get("message", {})
            if isinstance(msg_obj, dict):
                raw_message = msg_obj.get("raw_message", "") or msg_obj.get("processed_plain_text", "") or ""
            if raw_message and isinstance(raw_message, str):
                match = re.search(r"^/设置好感度\s+(\S+)\s+(-?\d+)$", raw_message)
                if match:
                    target_id = match.group(1)
                    score_str = match.group(2)
                    self._log(f"/设置好感度: 从 raw_message 解析: target={target_id}, score={score_str}")

        # 方式3: 从 text 参数解析
        if not target_id or not score_str:
            text = kwargs.get("text", "")
            if text and isinstance(text, str):
                match = re.search(r"^/设置好感度\s+(\S+)\s+(-?\d+)$", text)
                if match:
                    target_id = match.group(1)
                    score_str = match.group(2)
                    self._log(f"/设置好感度: 从 text 解析: target={target_id}, score={score_str}")

        if not target_id or not score_str:
            self._log(f"/设置好感度: 参数解析失败, kwargs={list(kwargs.keys())}")
            await self.ctx.send.text(
                "格式错误！用法：/设置好感度 <用户ID> <分数(-100~100)>", stream_id
            )
            return False, "格式错误", False

        new_score = int(score_str)
        old_score = self._favorability_service.get_score(target_id)
        self._favorability_service.set_score(target_id, new_score)
        new_level = FavorabilityService._score_to_level(new_score)
        display_name = self._favorability_service.get_display_name(target_id)

        result_message = (
            f"✅ 已设置用户 {display_name} 的好感度\n"
            f"━━━━━━━━━━━━━━\n"
            f"原分数：{old_score} → 新分数：{new_score}\n"
            f"等级：{new_level}\n"
            f"━━━━━━━━━━━━━━"
        )
        await self.ctx.send.text(result_message, stream_id)
        self._log(f"/设置好感度: admin={sender_id}, target={target_id}, old={old_score}, new={new_score}")
        return True, "设置成功", True

    # ===== Action 组件 =====

    @Action(
        "query_favorability",
        description="当用户用自然语言询问好感度相关问题时触发",
        activation_type=ActivationType.KEYWORD,
        activation_keywords=[
            "好感度", "喜欢我吗", "讨厌我", "关系如何",
            "对我印象", "对我感觉", "我在你心里", "你对我",
            "喜欢我", "爱我吗", "恨我",
        ],
        action_parameters={"query_message": "用户的好感度查询消息"},
        action_require=[
            "当用户询问与好感度相关的问题时使用",
            "当用户问'你喜欢我吗'或类似问题时使用",
            "当用户想了解自己与麦麦的关系时使用",
        ],
        associated_types=["text"],
    )
    async def handle_query_favorability(
        self, stream_id: str = "", query_message: str = "", **kwargs: Any
    ):
        """自然语言好感度查询。"""
        if not self._require_services():
            return True, "好感度插件未启用", True

        # 尝试从 kwargs 中提取消息对象
        message_obj = kwargs.get("_message", kwargs.get("message", kwargs.get("raw_message", {})))
        sender_id = self._extract_sender_id(message_obj, kwargs)
        if not sender_id:
            self._log(f"自然语言查询: 无法确定用户身份, kwargs_keys={list(kwargs.keys())}")
            return True, "无法确定用户身份", True

        info = self._favorability_service.get_level(sender_id)
        display_name = self._favorability_service.get_display_name(sender_id)

        # 根据等级生成不同的回复
        responses = {
            0: f"{info['level_emoji']} {display_name}，说实话...我们的关系不太好呢。当前好感度 {info['score']} 分。",
            1: f"{info['level_emoji']} {display_name}，你似乎对我有些反感...当前好感度 {info['score']} 分。",
            2: f"{info['level_emoji']} {display_name}，感觉你对我态度有点冷淡。当前好感度 {info['score']} 分。",
            3: f"{info['level_emoji']} {display_name}，好像有点不太开心？当前好感度 {info['score']} 分。",
            4: f"{info['level_emoji']} {display_name}，我们还需要多了解彼此~当前好感度 {info['score']} 分。",
            5: f"{info['level_emoji']} {display_name}，我们相处得还不错！当前好感度 {info['score']} 分。",
            6: f"{info['level_emoji']} {display_name}，你对我印象还不错嘛~当前好感度 {info['score']} 分。",
            7: f"{info['level_emoji']} {display_name}，我们是好朋友呢！当前好感度 {info['score']} 分。",
            8: f"{info['level_emoji']} {display_name}，你真的很喜欢我！好开心~当前好感度 {info['score']} 分。",
            9: f"{info['level_emoji']} {display_name}，哇！你超级喜欢我的！好感度 {info['score']} 分，太感动了！",
        }

        reply = responses.get(info["level_index"], f"{info['level_emoji']} {display_name}，当前好感度 {info['score']} 分。")
        await self.ctx.send.text(reply, stream_id)
        self._log(f"自然语言查询: user={sender_id}, score={info['score']}, level={info['level_name']}")
        return True, "已回复好感度查询", True

    # ===== 消息缓存组件 =====
    # 说明: 当前 MaiCore 宿主已注释掉 ON_MESSAGE 事件分发（src/chat/message_receive/bot.py），
    # 插件的 EventHandler(ON_MESSAGE) 不会被触发。宿主现通过「命名 Hook」向插件分发入站消息，
    # 因此这里改用 HookHandler 订阅 chat.receive.after_process（每条入站消息处理完成后触发，
    # 消息已包含 processed_plain_text 与 message_info）。

    def _read_cache(self) -> list:
        """读取缓存文件中的消息列表。"""
        import json

        if not self._cache_path or not os.path.exists(self._cache_path):
            return []
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"读取缓存文件失败: {e}")
            return []

    def _write_cache(self, messages: list) -> None:
        """将消息列表写入缓存文件。"""
        import json

        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self._log(f"写入缓存文件失败: {e}")

    def _cache_message(self, sender_id: str, plain_text: str) -> None:
        """将一条消息追加缓存到文件，达到阈值时触发 LLM 判断并清空。"""
        messages = self._read_cache()
        messages.append({"sender_id": sender_id, "text": plain_text})
        self._write_cache(messages)

        count = len(messages)
        interval = self.config.judge.judge_interval
        self._log(
            f"消息缓存: user={sender_id}, text={plain_text[:30]}, "
            f"缓存数={count}/{interval}"
        )

        if count >= interval:
            self._log(f"已达判断阈值 {interval} 条，开始处理并清空缓存")
            self._write_cache([])  # 先清空，避免并发重复触发
            self._spawn_llm_judge(messages)

    def _spawn_llm_judge(self, messages: list) -> None:
        """在后台任务中执行 LLM 判断（保持强引用，防止被 GC）。"""
        task = asyncio.create_task(self._trigger_llm_judge_from_cache(messages))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _trigger_llm_judge_from_cache(self, messages: list) -> None:
        """从缓存消息触发 LLM 判断（批量模式：一次 API 调用处理所有用户）。"""
        try:
            # 按用户分组消息
            user_messages = {}
            for msg in messages:
                sender_id = msg.get("sender_id", "")
                text = msg.get("text", "")
                if not sender_id or not text:
                    continue
                user_messages.setdefault(sender_id, []).append(text)

            if not user_messages:
                return

            # 批量调用 LLM 判断（一次 API 调用处理所有用户）
            self._log(f"LLM: 批量判断开始: {len(user_messages)} 个用户")

            results = await self._llm_service.judge_favorability_batch(user_messages)

            # 应用结果
            for sender_id, delta, reason in results:
                old_score = self._favorability_service.get_score(sender_id)
                new_score = self._favorability_service.modify_score(sender_id, delta)

                self._log(
                    f"LLM: 判断完成: user={sender_id}, delta={delta:+d}, "
                    f"old={old_score} → new={new_score}, reason={reason}"
                )
        except Exception as e:
            self._log(f"LLM: 判断异常: {e}")

    # ===== HookHandler 组件（接收入站消息）=====

    @HookHandler(
        "chat.receive.after_process",
        name="favorability_message_cache",
        description="缓存入站消息到文件，满 n 条触发 LLM 好感度判断",
        mode=HookMode.OBSERVE,
        order=HookOrder.LATE,
    )
    async def handle_message_after_process(self, **kwargs: Any):
        """消息处理完成后缓存消息并触发好感度判断（observe 模式，不阻塞主链路）。"""
        try:
            if not self.config.plugin.enabled:
                return None
            if self._favorability_service is None or self._llm_service is None:
                return None

            message = kwargs.get("message", {})
            if not isinstance(message, dict):
                return None

            # 提取文本：processed_plain_text 优先，raw_message 为段列表需要转换
            plain_text = message.get("processed_plain_text", "")
            if not plain_text or not isinstance(plain_text, str):
                return None
            plain_text = plain_text.strip()
            if not plain_text:
                return None
            # 跳过命令类消息，避免把 /好感度 等命令计入对话
            if plain_text.startswith("/"):
                return None

            # 提取发送者 ID：message_info.user_info.user_id
            sender_id = ""
            message_info = message.get("message_info", {})
            if isinstance(message_info, dict):
                user_info = message_info.get("user_info", {})
                if isinstance(user_info, dict):
                    sender_id = str(user_info.get("user_id", "") or "")
            if not sender_id:
                sender_id = str(message.get("sender_id", "") or message.get("user_id", "") or "")
            if not sender_id:
                return None

            # 提取昵称：message_info.user_info.user_nickname
            nickname = ""
            message_info = message.get("message_info", {})
            if isinstance(message_info, dict):
                user_info = message_info.get("user_info", {})
                if isinstance(user_info, dict):
                    nickname = str(user_info.get("user_nickname", "") or "")

            # 新用户自动初始化好感度（带昵称）
            if sender_id not in self._favorability_service.get_all_scores():
                self._favorability_service.initialize_user(sender_id, nickname=nickname)
                self._log(f"新用户初始化: user={sender_id}, nickname={nickname}, initial_score={self.config.judge.initial_score}")
            elif nickname:
                # 已有用户更新昵称
                self._favorability_service.update_user(sender_id, nickname)

            # 缓存消息到文件（内部会判断是否触发 LLM）
            self._cache_message(sender_id, plain_text)
        except Exception as e:
            self._log(f"HookHandler 处理异常: {e}")
        return None

def create_plugin() -> FavorabilityPlugin:
    """创建好感度插件实例。

    Returns:
        FavorabilityPlugin: 新的好感度插件实例。
    """
    return FavorabilityPlugin()
