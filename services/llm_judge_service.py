"""LLM 好感度判断服务 — 使用插件独立配置的 API。"""

from __future__ import annotations

import json
from typing import Any, Tuple

try:
    from aiohttp import ClientSession, ClientTimeout

    AIOHTTP_AVAILABLE = True
except ImportError:
    ClientSession = None  # type: ignore[assignment]
    ClientTimeout = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

from ..config import FavorabilityLLMConfig


class LLMJudgeService:
    """LLM 好感度判断服务。

    使用插件独立配置的 LLM API（不继承麦麦主配置），
    根据对话历史判断用户对麦麦的好感度变化。
    """

    SYSTEM_PROMPT = """你是一个好感度分析器。根据用户与 AI 助手麦麦的最近对话历史，判断用户对麦麦的好感度变化。

判断标准：
- 正面信号：感谢、赞美、关心、主动分享、使用友好语气、表达喜爱
- 负面信号：辱骂、冷漠、敷衍、表达不满、使用命令式语气、表达厌恶
- 中性信号：普通信息交换、问答、无明显情感倾向

请只输出一个 JSON 对象，格式如下：
{"delta": <变化值>, "reason": "<简要原因>"}

变化值范围：-10 到 +10 的整数。
- 正数表示好感度上升
- 负数表示好感度下降
- 0 表示无明显变化

原因用中文简要描述，不超过 50 字。"""

    SYSTEM_PROMPT_BATCH = """你是一个好感度分析器。根据多个用户与 AI 助手麦麦的最近对话历史，分别判断每个用户对麦麦的好感度变化。

判断标准：
- 正面信号：感谢、赞美、关心、主动分享、使用友好语气、表达喜爱
- 负面信号：辱骂、冷漠、敷衍、表达不满、使用命令式语气、表达厌恶
- 中性信号：普通信息交换、问答、无明显情感倾向

请为每个用户分别输出一个 JSON 对象，格式如下：
{"user_id": "用户ID", "delta": <变化值>, "reason": "<简要原因>"}

最终输出一个 JSON 数组，包含所有用户的结果，例如：
[{"user_id": "123", "delta": 3, "reason": "用户表达了感谢"}, {"user_id": "456", "delta": -1, "reason": "语气略显冷淡"}]

变化值范围：-10 到 +10 的整数。
- 正数表示好感度上升
- 负数表示好感度下降
- 0 表示无明显变化

原因用中文简要描述，不超过 50 字。"""

    def __init__(self, config: FavorabilityLLMConfig, logger: Any, llm_output_path: str = "") -> None:
        """初始化 LLM 判断服务。

        Args:
            config: LLM 配置（API URL、Key、模型等）。
            logger: 日志对象。
            llm_output_path: LLM 输出日志文件路径。
        """
        self._config = config
        self._logger = logger
        self._llm_output_path = llm_output_path

    def _write_llm_output(self, content: str) -> None:
        """将 LLM 输出写入单独文件。

        Args:
            content: LLM 输出的原始内容。
        """
        if not self._llm_output_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._llm_output_path), exist_ok=True)
            with open(self._llm_output_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
        except OSError:
            pass

    async def judge_favorability(self, history: list[str]) -> Tuple[int, str]:
        """调用 LLM 判断好感度变化。

        Args:
            history: 近期对话历史消息列表。

        Returns:
            tuple: (delta, reason) 变化值和原因。
        """
        if not history:
            print("[LLMJudgeService] 无对话历史，跳过判断", flush=True)
            self._logger.warning("[LLM] 无对话历史，跳过判断")
            return 0, "无对话历史"

        if not AIOHTTP_AVAILABLE or ClientSession is None or ClientTimeout is None:
            print("[LLMJudgeService] 缺少 aiohttp 依赖，无法调用 LLM API", flush=True)
            self._logger.warning("[LLM] 缺少 aiohttp 依赖，无法调用 LLM API")
            return 0, "缺少 aiohttp 依赖"

        # 检查 API Key 是否配置
        if not self._config.api_key:
            print("[LLMJudgeService] API Key 未配置，请在插件设置中填写", flush=True)
            self._logger.error("[LLM] API Key 未配置，请在插件设置中填写")
            return 0, "API Key 未配置"

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "以下是最近的对话历史：\n\n"
                + "\n".join(f"[{i + 1}] {msg}" for i, msg in enumerate(history)),
            },
        ]

        print(
            f"[LLMJudgeService] 发起 API 请求: model={self._config.model}, "
            f"history_len={len(history)}, api_url={self._config.api_url}",
            flush=True,
        )
        self._logger.info(
            f"[LLM] 发起 API 请求: model={self._config.model}, "
            f"history_len={len(history)}, api_url={self._config.api_url}"
        )

        try:
            timeout = ClientTimeout(total=30)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    self._config.api_url,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._config.model,
                        "messages": messages,
                        "temperature": self._config.temperature,
                        "max_tokens": self._config.max_tokens,
                    },
                ) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        msg = f"API 返回错误: status={resp.status}, body={error_body[:200]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return 0, f"LLM API 错误: {resp.status}"

                    result = await resp.json()

                    # 记录 finish_reason（便于调试 token 截断问题）
                    finish_reason = result.get("choices", [{}])[0].get("finish_reason", "unknown") if result.get("choices") else "unknown"

                    # 始终将原始 API 响应写入文件（即使出错也要记录）
                    self._write_llm_output(f"{'='*60}\n[单次判断] model={self._config.model}\n[对话历史]\n" + "\n".join(f"[{i+1}] {msg}" for i, msg in enumerate(history)) + f"\n[finish_reason]\n{finish_reason}\n[API 原始响应]\n{str(result)[:800]}\n")

                    # 调试：记录原始响应，方便排查 API 错误
                    if "choices" not in result:
                        msg = f"API 响应缺少 choices 字段: {str(result)[:300]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return 0, f"LLM API 响应异常: {str(result)[:100]}"

                    # 安全提取 content（兼容多种响应格式）
                    try:
                        content = result["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as e:
                        msg = f"提取 content 失败: {e}, 响应: {str(result)[:200]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return 0, f"LLM 响应格式异常: {e}"

                    self._write_llm_output(f"[LLM content]\n{content}\n")

                    # 检查 content 是否为空（finish_reason=length 时可能被截断）
                    if not content or not content.strip():
                        msg = f"LLM content 为空 (finish_reason={finish_reason})，可能是 reasoning 消耗了过多 token"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.warning(msg)
                        return 0, f"LLM 输出为空: {msg}"

                    # 解析 JSON 响应
                    delta, reason = self._parse_response(content)
                    self._write_llm_output(f"[解析结果] delta={delta:+d}, reason={reason}\n")
                    return delta, reason

        except Exception as e:
            msg = f"判断异常: {e}"
            print(f"[LLMJudgeService] {msg}", flush=True)
            self._logger.error(msg)
            return 0, f"判断异常: {e}"

    async def judge_favorability_batch(
        self, user_messages: Dict[str, List[str]]
    ) -> List[Tuple[str, int, str]]:
        """批量调用 LLM 判断多个用户的好感度变化（一次 API 调用）。

        Args:
            user_messages: user_id -> 消息列表 的字典。

        Returns:
            list: [(user_id, delta, reason), ...] 的结果列表。
        """
        if not user_messages:
            return []

        if not AIOHTTP_AVAILABLE or ClientSession is None or ClientTimeout is None:
            print("[LLMJudgeService] 缺少 aiohttp 依赖，无法调用 LLM API", flush=True)
            return [(uid, 0, "缺少 aiohttp 依赖") for uid in user_messages]

        if not self._config.api_key:
            print("[LLMJudgeService] API Key 未配置", flush=True)
            return [(uid, 0, "API Key 未配置") for uid in user_messages]

        # 构建批量提示词
        batch_prompt = self._build_batch_prompt(user_messages)

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT_BATCH},
            {"role": "user", "content": batch_prompt},
        ]

        print(
            f"[LLMJudgeService] 发起批量 API 请求: model={self._config.model}, "
            f"users={len(user_messages)}, api_url={self._config.api_url}",
        )
        self._logger.info(
            f"[LLM] 发起批量 API 请求: model={self._config.model}, users={len(user_messages)}"
        )

        try:
            timeout = ClientTimeout(total=60)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    self._config.api_url,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._config.model,
                        "messages": messages,
                        "temperature": self._config.temperature,
                        "max_tokens": self._config.max_tokens,
                    },
                ) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        msg = f"API 返回错误: status={resp.status}, body={error_body[:200]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return [(uid, 0, f"LLM API 错误: {resp.status}") for uid in user_messages]

                    result = await resp.json()

                    # 记录 finish_reason（便于调试 token 截断问题）
                    finish_reason = result.get("choices", [{}])[0].get("finish_reason", "unknown") if result.get("choices") else "unknown"

                    # 始终将原始 API 响应写入文件（即使出错也要记录）
                    self._write_llm_output(f"{'='*60}\n[批量判断] model={self._config.model}, users={len(user_messages)}\n[批量提示词]\n{batch_prompt}\n[finish_reason]\n{finish_reason}\n[API 原始响应]\n{str(result)[:800]}\n")

                    if "choices" not in result:
                        msg = f"API 响应缺少 choices 字段: {str(result)[:300]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return [(uid, 0, "LLM API 响应异常") for uid in user_messages]

                    # 安全提取 content（兼容多种响应格式）
                    try:
                        content = result["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as e:
                        msg = f"提取 content 失败: {e}, 响应: {str(result)[:200]}"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.error(msg)
                        return [(uid, 0, f"LLM 响应格式异常: {e}") for uid in user_messages]

                    self._write_llm_output(f"[LLM content]\n{content}\n")

                    # 检查 content 是否为空（finish_reason=length 时可能被截断）
                    if not content or not content.strip():
                        msg = f"LLM content 为空 (finish_reason={finish_reason})，可能是 reasoning 消耗了过多 token"
                        print(f"[LLMJudgeService] {msg}", flush=True)
                        self._logger.warning(msg)
                        return [(uid, 0, f"LLM 输出为空: {msg}") for uid in user_messages]

                    return self._parse_batch_response(content, list(user_messages.keys()))

        except Exception as e:
            msg = f"批量判断异常: {e}"
            print(f"[LLMJudgeService] {msg}", flush=True)
            self._logger.error(msg)
            return [(uid, 0, f"判断异常: {e}") for uid in user_messages]

    def _build_batch_prompt(self, user_messages: Dict[str, List[str]]) -> str:
        """构建批量判断的提示词。"""
        parts = ["以下是多个用户与 AI 助手麦麦的最近对话历史，请分别判断每个用户对麦麦的好感度变化。\n"]

        for user_id, messages in user_messages.items():
            parts.append(f"【用户 {user_id}】")
            for i, msg in enumerate(messages, 1):
                parts.append(f"  [{i}] {msg}")
            parts.append("")

        parts.append("请为每个用户输出一个 JSON 对象，格式如下：")
        parts.append('{"user_id": "用户ID", "delta": <变化值>, "reason": "<简要原因>"}')
        parts.append("\n请只输出一个 JSON 数组，包含所有用户的结果，不要输出其他内容。")

        return "\n".join(parts)

    @staticmethod
    def _parse_batch_response(content: str, user_ids: List[str]) -> List[Tuple[str, int, str]]:
        """解析 LLM 返回的批量 JSON 响应。

        Args:
            content: LLM 返回的文本内容。
            user_ids: 预期的用户 ID 列表。

        Returns:
            list: [(user_id, delta, reason), ...] 的结果列表。
        """
        import re

        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        results = []

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        uid = str(item.get("user_id", ""))
                        delta = max(-10, min(10, int(item.get("delta", 0))))
                        reason = str(item.get("reason", "无原因"))
                        results.append((uid, delta, reason))
            elif isinstance(parsed, dict):
                # 单个对象也兼容
                uid = str(parsed.get("user_id", ""))
                delta = max(-10, min(10, int(parsed.get("delta", 0))))
                reason = str(parsed.get("reason", "无原因"))
                results.append((uid, delta, reason))
        except (json.JSONDecodeError, ValueError):
            # JSON 解析失败时尝试正则提取每个用户的结果
            for uid in user_ids:
                # 查找该用户对应的 JSON 对象
                pattern = rf'"user_id"\s*:\s*"{re.escape(uid)}".*?"delta"\s*:\s*(-?\d+).*?"reason"\s*:\s*"([^"]*)"'
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    delta = max(-10, min(10, int(match.group(1))))
                    reason = match.group(2)
                    results.append((uid, delta, reason))

        # 补全未解析到的用户
        found_uids = {r[0] for r in results}
        for uid in user_ids:
            if uid not in found_uids:
                results.append((uid, 0, "无法解析 LLM 响应"))

        return results

    @staticmethod
    def _parse_response(content: str) -> Tuple[int, str]:
        """解析 LLM 返回的 JSON 响应。

        Args:
            content: LLM 返回的文本内容。

        Returns:
            tuple: (delta, reason)。
        """
        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        text = content.strip()
        if text.startswith("```"):
            # 去除 ```json 和 ```
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            parsed = json.loads(text)
            delta = max(-10, min(10, int(parsed.get("delta", 0))))
            reason = str(parsed.get("reason", "无原因"))
            return delta, reason
        except (json.JSONDecodeError, ValueError):
            # JSON 解析失败时尝试正则提取
            import re

            delta_match = re.search(r'"delta"\s*:\s*(-?\d+)', text)
            reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
            if delta_match:
                delta = max(-10, min(10, int(delta_match.group(1))))
                reason = reason_match.group(1) if reason_match else "解析原因失败"
                return delta, reason

            return 0, f"无法解析 LLM 响应: {text[:100]}"
