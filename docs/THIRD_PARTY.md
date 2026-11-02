# 第三方依赖与许可证清单

## A. 运行时 / 测试依赖（Python，装在项目内 `.venv`，通过本地已有包安装；Python 依赖本身不含付费服务）
| 包 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| mcp (Model Context Protocol SDK) | 2.3.0 | MIT | stdio MCP 服务端与（测试/真实适配器）客户端 |
| pillow | 13.0.0 | MIT-CMU（HPND 类宽松许可） | Mock JPEG 生成、预览解码校验 |
| pytest | 9.2.0 | MIT | 测试（开发依赖） |
| mcp 的传递依赖：pydantic 2.14.2 (MIT)、anyio 4.15.1 (MIT)、starlette 1.10.0 (BSD-3)、uvicorn 0.54.0 (BSD-3)、sse-starlette 3.6.0 (BSD-3)、jsonschema 4.26.0 (MIT)、PyJWT 2.15.1 (MIT)、python-multipart 0.0.32 (Apache-2.0)、cryptography 50.0.2 (Apache-2.0 OR BSD-3) | | 宽松 | 仅为 mcp 所需，本项目不直接使用 |
| setuptools | 78.1.1 | MIT | 构建（editable 安装） |

核心 Photo Core / Ingest / 任务引擎仅使用 Python 标准库（hashlib、sqlite3、os、pathlib …）。**无 GPL/AGPL 依赖。**

## B. 外部项目（固定提交，详见 docs/REUSE_DECISION.md）
| 项目 | 固定提交 | 许可证 | 使用方式 |
|---|---|---|---|
| Automaat/lightroom-mcp（npm: @mskalski/lightroom-mcp 0.26.0） | `55cd17f9cc9942468bac438b965908ab76b62a9d` | MIT | 运行时外部进程（Mac 上，用户确认后安装）；本仓库**不包含其代码**；Linux 只用假服务器做接口测试 |
| deepseek-ai/deepseek-harness | `ce7073d51254c26cd63b22a60835b8f948deb447` | MIT | AI 前端（Phase 2 已接入，见 §C）；不 vendoring，克隆在 git 忽略的 `third_party-review/deepseek-harness` |
| hktkzyx/ingest | `9706bd2ff1cffacbde21c419bf3fba37a973be7a` | MIT | 只审查，未复用代码（其快速跳过逻辑与 xxHash64 不符合要求） |
| noar-justedit/ingesto | `286b6ed179aa6ca78791d508b6251dc642052311` | **GPL-3.0** | 只审查，**未复用、未拷贝、未链接** |
`third_party-review/` 下的克隆被 git 忽略，不入库；除 deepseek-harness（§C）外从未构建或执行。

## C. deepseek-harness（Phase 2，仅作测试/可选前端，不随本仓库分发）
- 许可证：MIT（仓库 LICENSE）；固定提交 `ce7073d51254c26cd63b22a60835b8f948deb447`；README/SAFETY.md 自述 **实验性、未审计**。
- 运行要求：Node ≥ 24.9（盒子用 nvm 的 24.22.2，系统默认 Node 20 未改动）、pnpm 11.28.5（经 corepack，`COREPACK_HOME=$HOME/.cache/corepack`）。
- 安装方式：`pnpm install --frozen-lockfile --ignore-scripts --filter "@deepseek-ai/dsh..."`（1152 个包，全部按其 pnpm-lock.yaml 锁定；**跳过生命周期脚本**——已审阅：lefthook git-hook postinstall 与 node-pty 的 chmod，均与本集成无关）。另用本机 gcc 编译其 `native/system/packages/entry/src/flock.c`（Node-API 文件锁插件，已审阅源码）。
- 直接相关依赖：`@deepseek-ai/dsh-mcp-client`（工作区包）→ `@modelcontextprotocol/client` 2.2.0；agent 循环用其工作区包（cordis、dsh-llm、dsh-tools…）；运行 TS 用 tsx 4.23.13。完整版本以其 `pnpm-lock.yaml` 为准（我们不复制、不改动）。
- 我们的代码（harness/ 下的 yml/ts/sh）以本项目许可证提供，仅在运行时复制到被忽略的 Harness 检出里。

真实模型 opt-in 运行使用付费 DeepSeek API（`deepseek-official` / `deepseek-flash`，经 Harness 的 `dsh-llm-deepseek-api-key`）；数据处理和密钥风险见 `docs/KNOWN_RISKS.md`。
