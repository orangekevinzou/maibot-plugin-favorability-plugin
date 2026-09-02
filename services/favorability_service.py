"""好感度核心服务 — 数据读写、增减、分级、持久化。"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Optional

from ..config import FavorabilityJudgeConfig


class FavorabilityService:
    """好感度核心服务。

    负责好感度数据的读写、增减、分级、持久化。
    数据存储在 JSON 文件中，运行时维护内存缓存。
    """

    # 好感度等级定义 (上限, 名称, emoji)
    LEVELS: List[tuple[int, str, str]] = [
        (-80, "极度厌恶", "😡"),
        (-60, "非常反感", "😠"),
        (-40, "反感", "😒"),
        (-20, "轻微反感", "😕"),
        (0, "中性偏冷", "😐"),
        (20, "中性偏暖", "🙂"),
        (40, "轻微好感", "😊"),
        (60, "友好", "😄"),
        (80, "非常友好", "🥰"),
        (101, "极度喜爱", "❤️"),
    ]

    def __init__(self, data_path: str, config: FavorabilityJudgeConfig, logger: Any) -> None:
        """初始化好感度服务。

        Args:
            data_path: 数据文件路径。
            config: 判断触发配置。
            logger: 日志对象。
        """
        self._data_path = data_path
        self._config = config
        self._logger = logger
        self._scores: Dict[str, int] = {}
        self._users: Dict[str, Dict[str, str]] = {}  # user_id -> {nickname, ...}
        self._history: Dict[str, List[str]] = {}
        self._counters: Dict[str, int] = {}
        self._load_data()

    def _load_data(self) -> None:
        """从 JSON 文件加载好感度数据。"""
        if os.path.exists(self._data_path):
            try:
                with open(self._data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._scores = data.get("scores", {})
                    self._users = data.get("users", {})
                msg = f"已加载 {len(self._scores)} 条好感度数据, {len(self._users)} 个用户"
                print(f"[FavorabilityService] {msg}", flush=True)
                self._logger.info(msg)
            except (json.JSONDecodeError, OSError) as e:
                msg = f"好感度数据文件损坏，初始化为空: {e}"
                print(f"[FavorabilityService] {msg}", flush=True)
                self._logger.warning(msg)
                self._scores = {}
                self._users = {}
        else:
            self._scores = {}
            self._users = {}
            print(f"[FavorabilityService] 数据文件不存在，初始化为空", flush=True)

    def _save_data(self) -> None:
        """持久化好感度数据到 JSON 文件（写时复制）。"""
        try:
            dir_name = os.path.dirname(self._data_path)
            os.makedirs(dir_name, exist_ok=True)

            # 写时复制：先写临时文件，再重命名
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"scores": self._scores, "users": self._users}, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self._data_path)
            except Exception:
                # 清理临时文件
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except OSError as e:
            self._logger.error(f"好感度数据保存失败: {e}")

    def get_score(self, user_id: str) -> int:
        """获取用户好感度，不存在则返回初始值。

        Args:
            user_id: 用户 ID。

        Returns:
            int: 好感度分数。
        """
        return self._scores.get(user_id, self._config.initial_score)

    def initialize_user(self, user_id: str, nickname: str = "") -> int:
        """初始化新用户的好感度（如果尚未初始化）。

        Args:
            user_id: 用户 ID。
            nickname: 用户昵称（可选）。

        Returns:
            int: 初始化后的好感度分数。
        """
        if user_id not in self._scores:
            self._scores[user_id] = self._config.initial_score
            if nickname:
                self._users[user_id] = {"nickname": nickname}
            self._save_data()
            msg = f"新用户初始化: user={user_id}, score={self._config.initial_score}"
            if nickname:
                msg += f", nickname={nickname}"
            print(f"[FavorabilityService] {msg}", flush=True)
            self._logger.info(msg)
            return self._config.initial_score
        # 已有用户但昵称缺失时补上
        if nickname and (user_id not in self._users or not self._users[user_id].get("nickname")):
            if user_id not in self._users:
                self._users[user_id] = {}
            self._users[user_id]["nickname"] = nickname
            self._save_data()
        return self._scores[user_id]

    def update_user(self, user_id: str, nickname: str = "") -> None:
        """更新用户信息（昵称等）。

        Args:
            user_id: 用户 ID。
            nickname: 用户昵称。
        """
        if not nickname:
            return
        if user_id not in self._users:
            self._users[user_id] = {}
        if self._users[user_id].get("nickname") != nickname:
            self._users[user_id]["nickname"] = nickname
            self._save_data()

    def get_nickname(self, user_id: str) -> str:
        """获取用户昵称。

        Args:
            user_id: 用户 ID。

        Returns:
            str: 用户昵称，未找到则返回空字符串。
        """
        return self._users.get(user_id, {}).get("nickname", "")

    def get_display_name(self, user_id: str) -> str:
        """获取用户显示名（昵称+ID）。

        Args:
            user_id: 用户 ID。

        Returns:
            str: 格式为 "昵称(ID)"，无昵称则只返回 ID。
        """
        nickname = self.get_nickname(user_id)
        if nickname:
            return f"{nickname}({user_id})"
        return user_id

    def get_all_users(self) -> Dict[str, Dict[str, str]]:
        """获取所有用户信息。

        Returns:
            dict: user_id -> {nickname, ...} 的字典。
        """
        return dict(self._users)

    def get_level(self, user_id: str) -> Dict[str, Any]:
        """获取用户好感度等级信息。

        Args:
            user_id: 用户 ID。

        Returns:
            dict: 包含 score, level_name, level_emoji, level_index 的字典。
        """
        score = self.get_score(user_id)
        level_name, level_emoji, level_index = self._score_to_level_info(score)
        return {
            "score": score,
            "level_name": level_name,
            "level_emoji": level_emoji,
            "level_index": level_index,
        }

    def modify_score(self, user_id: str, delta: int) -> int:
        """修改用户好感度，返回修改后的值。

        Args:
            user_id: 用户 ID。
            delta: 变化值（可正可负）。

        Returns:
            int: 修改后的好感度分数。
        """
        current = self.get_score(user_id)
        new_score = max(-100, min(100, current + delta))
        self._scores[user_id] = new_score
        self._save_data()
        return new_score

    def set_score(self, user_id: str, score: int) -> int:
        """直接设置用户好感度。

        Args:
            user_id: 用户 ID。
            score: 目标分数。

        Returns:
            int: 设置后的好感度分数。
        """
        new_score = max(-100, min(100, score))
        self._scores[user_id] = new_score
        self._save_data()
        return new_score

    def record_message(self, user_id: str, message: str) -> bool:
        """记录用户消息，返回是否触发 LLM 判断。

        Args:
            user_id: 用户 ID。
            message: 消息内容。

        Returns:
            bool: 是否到达判断间隔。
        """
        if user_id not in self._counters:
            self._counters[user_id] = 0
        self._counters[user_id] += 1

        if user_id not in self._history:
            self._history[user_id] = []
        self._history[user_id].append(message)

        # 保持历史窗口
        if len(self._history[user_id]) > self._config.history_window:
            self._history[user_id] = self._history[user_id][-self._config.history_window :]

        # 判断是否到达判断间隔
        return self._counters[user_id] % self._config.judge_interval == 0

    def get_history(self, user_id: str) -> List[str]:
        """获取用户近期对话历史。

        Args:
            user_id: 用户 ID。

        Returns:
            list[str]: 近期消息列表。
        """
        return list(self._history.get(user_id, []))

    def reset_counter(self, user_id: str) -> None:
        """重置计数器（LLM 判断后调用）。

        Args:
            user_id: 用户 ID。
        """
        self._counters[user_id] = 0

    def get_counter(self, user_id: str) -> int:
        """获取用户当前计数器值。

        Args:
            user_id: 用户 ID。

        Returns:
            int: 当前计数器值。
        """
        return self._counters.get(user_id, 0)

    def get_all_scores(self) -> Dict[str, int]:
        """获取所有用户好感度。

        Returns:
            dict: user_id -> score 的字典。
        """
        return dict(self._scores)

    @classmethod
    def _score_to_level_info(cls, score: int) -> tuple[str, str, int]:
        """分数转等级信息。

        Args:
            score: 好感度分数。

        Returns:
            tuple: (等级名称, emoji, 等级索引)
        """
        for idx, (threshold, name, emoji) in enumerate(cls.LEVELS):
            if score < threshold:
                return name, emoji, idx
        return "极度喜爱", "❤️", 9

    @classmethod
    def _score_to_level(cls, score: int) -> str:
        """分数转等级名称。"""
        name, _, _ = cls._score_to_level_info(score)
        return name

    @classmethod
    def _score_to_emoji(cls, score: int) -> str:
        """分数转 emoji。"""
        _, emoji, _ = cls._score_to_level_info(score)
        return emoji
