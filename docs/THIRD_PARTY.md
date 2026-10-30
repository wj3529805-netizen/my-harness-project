# 第三方依赖与许可证清单

## A. 运行时 / 测试依赖（Python，装在项目内 `.venv`，通过本地已有包安装；未使用付费服务）
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
| deepseek-ai/deepseek-harness | `ce7073d51254c26cd63b22a60835b8f948deb447` | MIT | 作为可选 AI 前端，通过 stdio MCP 接入；不 vendoring；未在盒子上运行（Node 版本不足） |
| hktkzyx/ingest | `9706bd2ff1cffacbde21c419bf3fba37a973be7a` | MIT | 只审查，未复用代码（其快速跳过逻辑与 xxHash64 不符合要求） |
| noar-justedit/ingesto | `286b6ed179aa6ca78791d508b6251dc642052311` | **GPL-3.0** | 只审查，**未复用、未拷贝、未链接** |
`third_party-review/` 下的克隆被 git 忽略，从未构建或执行。
