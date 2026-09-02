# 好感度插件 (Favorability Plugin) v1.3.0

麦麦的好感度追踪系统，让麦麦能够感知每位用户与她的亲密度变化。

## ✨ 功能特性

- **自动判断**: 每 n 条消息后，自动调用 LLM 分析好感度变化
- **批量处理**: 一次 LLM 调用可同时判断多个用户的好感度，节省 API 成本
- **文件缓存**: 消息实时缓存到文件，达到阈值后批量处理，重启不丢失
- **LLM 输出导出**: 每次 LLM 的原始输出保存到独立文件，便于审计与调试
- **10 级分级**: 从 "极度厌恶" 到 "极度喜爱"，共 10 个等级
- **用户名识别**: 自动识别并存储用户昵称，输出格式为 `昵称(ID)`
- **自然语言查询**: 直接问 "你喜欢我吗"、"我的好感度是多少"
- **命令查询**: `/好感度`、`/好感度排行`
- **管理员命令**: `/设置好感度 <用户ID> <分数>` 手动调整
- **独立 LLM 配置**: 插件自带 API/Key/模型配置，不依赖麦麦主配置
- **持久化存储**: 好感度数据保存为 JSON 文件，重启不丢失

## 📊 好感度等级

| 等级 | 范围 | emoji |
|------|------|-------|
| 极度厌恶 | -100 ~ -80 | 😡 |
| 非常反感 | -80 ~ -60 | 😠 |
| 反感 | -60 ~ -40 | 😒 |
| 轻微反感 | -40 ~ -20 | 😕 |
| 中性偏冷 | -20 ~ 0 | 😐 |
| 中性偏暖 | 0 ~ 20 | 🙂 |
| 轻微好感 | 20 ~ 40 | 😊 |
| 友好 | 40 ~ 60 | 😄 |
| 非常友好 | 60 ~ 80 | 🥰 |
| 极度喜爱 | 80 ~ 100 | ❤️ |

## 🔧 配置说明

编辑 `config.toml`：

```toml
[plugin]
enabled = true
config_version = "1.0.0"

[llm]
api_url = "https://api.deepseek.com/v1/chat/completions"
api_key = "sk-你的Key"
model = "deepseek-v4-flash"
temperature = 0.3
max_tokens = 200

[judge]
judge_interval = 5
max_change_per_judge = 10
initial_score = 0
history_window = 20

[admin]
admin_users = ["用户ID1", "用户ID2"]
```

### LLM 判断服务

| 字段 | 说明 | 示例 |
|------|------|------|
| `api_url` | API 地址（需含完整路径） | `https://api.deepseek.com/v1/chat/completions` |
| `api_key` | API Key | `sk-xxx` |
| `model` | 模型名称 | `deepseek-v4-flash`、`LongCat-2.0`、`gpt-4o-mini` |
| `temperature` | 温度（0~1，越低越确定） | `0.3` |
| `max_tokens` | 最大输出 token 数（LongCat-2.0 建议 ≥1024） | `1024` |

> ⚠️ **注意**: `api_url` 必须包含完整路径（如 `/v1/chat/completions`），否则会报 404。
>
> ⚠️ **LongCat-2.0 注意**: 该模型有 `reasoning_content`（思维链），会消耗大量 token。`max_tokens` 建议设置为 `1024` 以上，否则可能导致 `finish_reason: 'length'`，`content` 被截断为空。

### 判断触发

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `judge_interval` | 每多少条消息触发一次 LLM 判断 | `10` |
| `max_change_per_judge` | 单次判断最大变化值 | `10` |
| `initial_score` | 新用户初始好感度 | `0` |
| `history_window` | 内存中保留的历史消息条数 | `20` |

### 管理员

| 字段 | 说明 |
|------|------|
| `admin_users` | 拥有手动设置好感度权限的用户 ID 列表 |

## 📝 使用方式

### 自然语言查询
```
你: 你喜欢我吗？
麦麦: 😊 橙子KevinZou(1446172846)，你对我印象还不错嘛~当前好感度 35 分。
```

### 命令查询
```
/好感度                     → 查看自己的好感度（含昵称）
/好感度排行                 → 查看好感度排行榜（格式：昵称(ID): 好感度）
/设置好感度 123456789 50    → 管理员设置用户好感度为 50
```

## 🏗️ 架构

```
用户消息 → HookHandler(chat.receive.after_process)
         → 提取 user_id + nickname + processed_plain_text
         → 新用户自动初始化好感度（含昵称）
         → 追加缓存到 data/message_cache.json
         → 达到 judge_interval 条
         → 清空缓存文件
         → 后台批量调用 LLM 判断（一次 API 调用处理所有用户）
         → LLM 原始输出保存到 data/llm_output.log
         → 更新 data/favorability.json
```

### 组件说明

| 组件 | 类型 | 触发方式 | 功能 |
|------|------|---------|------|
| `get_favorability` | Tool | LLM 自动调用 | 查询好感度并注入上下文 |
| `get_all_favorability` | Tool | LLM 自动调用 | 查询好感度排行 |
| `/好感度` | Command | 用户命令 | 查询自己的好感度 |
| `/好感度排行` | Command | 用户命令 | 查询排行榜 |
| `/设置好感度` | Command | 管理员命令 | 手动设置好感度 |
| `query_favorability` | Action | 自然语言触发 | 关键词匹配好感度查询 |
| `favorability_message_cache` | HookHandler | 消息处理完成后 | 缓存消息并触发 LLM 判断 |

## 📁 项目结构

```
favorability-plugin/
├── _manifest.json              # 插件清单
├── plugin.py                   # 主插件类 (HookHandler/Command/Action/Tool)
├── config.py                   # 配置模型 (Pydantic)
├── config.toml                 # 默认配置
├── services/
│   ├── __init__.py
│   ├── favorability_service.py # 好感度核心服务 (读写/分级/持久化)
│   └── llm_judge_service.py    # LLM 判断服务 (独立 API 调用)
├── data/
│   ├── favorability.json       # 用户好感度数据 (运行时生成)
│   ├── message_cache.json      # 消息缓存 (运行时生成)
│   ├── llm_output.log          # LLM 原始输出 (运行时生成)
│   └── debug.log               # 调试日志 (运行时生成)
└── docs/
    ├── README.md               # 本文档
    └── IMPLEMENTATION.md       # 完整实现方案
```

## 📊 数据存储

### favorability.json
```json
{
  "scores": {
    "1446172846": 45,
    "987654321": -12
  },
  "users": {
    "1446172846": {"nickname": "橙子KevinZou"},
    "987654321": {"nickname": "测试用户"}
  }
}
```

### message_cache.json
```json
[
  {"sender_id": "123456789", "text": "今天天气真好"},
  {"sender_id": "987654321", "text": "你好"}
]
```

## 🔍 调试

插件运行日志以 `[plugin.maibot-team.favorability-plugin]` 为前缀，可在 MaiBot 控制台查看。

常见日志：
```
好感度插件开始加载
判断间隔: 每 5 条消息, 初始好感度: 0, LLM: deepseek-v4-flash
新用户初始化: user=123456789, initial_score=0
消息缓存: user=123456789, text=你好, 缓存数=1/5
已达判断阈值 5 条，开始处理并清空缓存
LLM: 开始判断: user=123456789, history_len=5
LLM: 判断完成: user=123456789, delta=+3, old=0 → new=3, reason=用户表达了友好
```

## ⚠️ 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 404 错误 | API URL 缺少路径 | 确保 URL 包含 `/v1/chat/completions` |
| 401 错误 | API Key 无效 | 检查 `api_key` 是否正确 |
| 好感度不变化 | LLM 返回 delta=0 | 正常现象，LLM 判断无明显变化 |
| 命令无法使用 | 用户非管理员 | 在 `admin_users` 中添加用户 ID |

## 📦 依赖

- `maibot_sdk` — MaiBot 插件 SDK
- `aiohttp` — 异步 HTTP 客户端（调用 LLM API）

## 🤖 AI 开发声明

本插件使用 AI 辅助工具开发，主要使用了以下大模型：

- **LongCat 2.0** — 代码架构设计与实现
- **DeepSeek V4 Flash** — 代码调试与问题修复

## 📄 许可证

GPL-3.0-or-later
