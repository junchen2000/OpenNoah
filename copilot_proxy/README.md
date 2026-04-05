# GitHub Copilot LLM Proxy

将 GitHub Copilot 的模型能力通过 OpenAI 兼容的 API 暴露出来，可以供 Claude Code、OpenAI SDK 等工具使用。

## 原理

1. 使用你的 GitHub Token（通过 `gh` CLI、环境变量或 VS Code 配置自动获取）
2. 交换为 GitHub Copilot 的短期 API Token
3. 在本地启动一个 OpenAI 兼容的 API 代理服务器
4. 将请求转发到 `api.githubcopilot.com`

## 支持的模型

- **OpenAI**: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, `o1`, `o3`, `o3-mini`, `o4-mini`
- **Anthropic**: `claude-3.5-sonnet`, `claude-3.7-sonnet`, `claude-3.7-sonnet-thought`, `claude-sonnet-4`, `claude-opus-4`
- **Google**: `gemini-2.0-flash-001`, `gemini-2.5-pro`
- **xAI**: `grok-3`

> 实际可用模型取决于你的 GitHub Copilot 订阅级别。

## 前置条件

- Python 3.10+
- 有效的 GitHub Copilot 订阅
- `aiohttp` 库（项目已包含）
- GitHub CLI (`gh`) 已登录，或设置 `GITHUB_TOKEN` 环境变量

## 快速启动

```bash
# 安装依赖
pip install aiohttp

# 启动代理（自动检测 GitHub Token）
python -m copilot_proxy

# 或指定端口和Token
python -m copilot_proxy --port 8787 --token ghp_xxxxx

# 开启调试日志
python -m copilot_proxy --debug
```

## API 接口

### 列出模型
```bash
curl http://127.0.0.1:8787/v1/models
```

### Chat Completions（非流式）
```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Chat Completions（流式）
```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3.7-sonnet",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

## 配合其他工具使用

### OpenAI Python SDK
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="copilot-proxy"  # 任意值即可，认证由代理处理
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### Claude Code
```bash
# 设置环境变量指向代理
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
export OPENAI_API_KEY=copilot-proxy
```

### 通用 LLM 客户端
任何支持 OpenAI API 格式的客户端都可以使用，只需将 `base_url` 指向 `http://127.0.0.1:8787/v1`。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--host` | 绑定地址 | `127.0.0.1` |
| `--port`, `-p` | 端口号 | `8787` |
| `--token` | GitHub Token | 自动检测 |
| `--debug` | 调试日志 | 关闭 |

## 注意事项

- 代理仅绑定到 `127.0.0.1`（本地），不要暴露到公网
- Copilot Token 会自动刷新，无需手动管理
- 请遵守 GitHub Copilot 的使用条款
