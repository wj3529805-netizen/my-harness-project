# CETACEA × deepseek-harness（Phase 2，实验性）

用 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（固定提交 `ce7073d51254c26cd63b22a60835b8f948deb447`，MIT）作为 CETACEA stdio MCP 服务的**客户端前端**。

## 它如何对接
Harness 的插件 `@deepseek-ai/dsh-mcp-client`（依赖 `@modelcontextprotocol/client` 2.2.0）按 YAML 条目启动 stdio 子进程：
`$CETACEA_PYTHON -m cetacea.cli --home $CETACEA_HOME mcp-serve`，经 JSON-RPC `tools/list` / `tools/call`，把 14 个工具注册为
`mcp__cetacea__<tool>`。`isError` 结果在 Harness 里表现为失败的工具调用（文本形如 `Error: {"code":"NOT_APPROVED",...}`）。
子进程环境会被清除含 KEY/PASSWORD/SECRET/TOKEN 的变量和 `DSH_*`；配置里只传 `CETACEA_HOME`。

## 文件
| 文件 | 作用 |
|---|---|
| `cetacea-mcp.cordis.yml` | 要加进 dsh profile patch（`insert:`）的 MCP 条目；仅环境变量占位，无密钥 |
| `cetacea-restricted.patch.yml` | **安全必需**：关闭 Harness 自带的 bash/pwsh/文件读写编辑/web/子代理/workflow/skill 工具，否则模型可绕过 CETACEA 的“AI 无 shell/路径/删除”契约 |
| `overlay/cetacea-headless.patch.yml` + `overlay/cetacea-mock-llm.ts` | **仅测试用**：无密钥的脚本化 MOCK 模型 + MCP 条目，叠在 Harness 的 `headless` profile 上 |
| `run_headless.sh` | 在 Harness 的真实 agent 循环里跑一轮（需 Node ≥ 24.9；当前 node 太旧时只在本脚本内 `nvm use 24`，不改系统默认） |
| `../tests/test_harness_integration.py` | 4 个自动化测试（Harness 未安装/Node 24 缺失时带原因跳过） |

## 准备（一次性，不用 curl|bash，不装系统软件）
```bash
cd third_party-review && git clone https://github.com/deepseek-ai/deepseek-harness && cd deepseek-harness && git checkout ce7073d51254c26cd63b22a60835b8f948deb447
export NVM_DIR=$HOME/.nvm; unset NPM_CONFIG_PREFIX; . $NVM_DIR/nvm.sh; nvm use 24
COREPACK_HOME=$HOME/.cache/corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm@11.28.5 install --frozen-lockfile --ignore-scripts --filter "@deepseek-ai/dsh..."
node_modules/.bin/tsx native/system/scripts/build.ts --host-addon-only   # 本地 gcc 编译 flock 插件 system.node（已审阅 C 源码）
```
然后 `.venv/bin/python -m pytest tests/test_harness_integration.py`。

## 真实模型使用（**未测试**）
把 `cetacea-restricted.patch.yml` 与 `cetacea-mcp.cordis.yml`（置于 `insert:` 下）合并进你的 dsh profile，设置 `CETACEA_PYTHON`、`CETACEA_HOME`，并自行提供模型密钥（环境变量，勿提交）。
