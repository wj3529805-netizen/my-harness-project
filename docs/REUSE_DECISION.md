# Gate 0：复用决策（REUSE_DECISION）

日期：2026-10-30（Asia/Shanghai）。Gate 0 全程只读：候选项目仅 `git clone`（浅克隆）到 `third_party-review/`（已 git-ignore），**从未安装依赖、构建或执行其中任何脚本**。

## 1. 已有的 CETACEA / 鲸目 / Photo Core 代码

| 位置 | 结论 |
|---|---|
| 盒子 `/workspace/cetacea/`（非 git） | 是 AI 打标签流水线草稿（analyze_one.py、schema、taxonomy、pipeline-design.md）。**没有**导入引擎、Photo Core、任务状态机、Lightroom 适配。不作为底座；未改动。仅借鉴设计思想（幂等 job key、冲突即拒绝、不覆盖），未拷贝代码。 |
| GitHub（Cursor GitHub App 可见范围） | 已认证账号 wj3529805-netizen，可见公开仓库 0 个；搜 "cetacea" 返回的都是无关仓库。**私有仓库查询返回 422（App 未被授权访问私有仓库）**，因此“用户私有仓库里是否已有 CETACEA 代码”**无法核实**。如需核查，需要用户在 https://github.com/apps/cursor/installations/new 授权。 |
| 结论 | 未发现可复用的现有 Photo Core。新建隔离仓库 `/workspace/cetacea-workbench`（分支 `phase1`，仅本地）。 |

## 2. 候选项目审查（固定 SHA）

| 项目 | SHA | 许可证 | 发现 | 决策 |
|---|---|---|---|---|
| deepseek-ai/deepseek-harness | `ce7073d51254c26cd63b22a60835b8f948deb447` | MIT | TypeScript agent harness；要求 Node ≥ 24.9 + pnpm；盒子只有 Node 20.19.2，且禁止系统级安装，**无法在盒子上运行**。自带 `dsh-mcp-client`（支持 stdio / streamable-http MCP，stdio 子进程环境变量被清洗）和 OpenAI-completions 等多种模型路由；SAFETY 文档自述为实验性、未经审计。 | **作为 AI 前端复用（不 vendoring）**：通过本项目的 stdio MCP 服务接入；docs 中给出 mcp-client 配置片段，标注“未实测”。 |
| Automaat/lightroom-mcp | `55cd17f9cc9942468bac438b965908ab76b62a9d`（npm 0.26.0） | MIT | 通过 Lightroom Classic 的 Lua 插件 + 本地服务器暴露 MCP 工具；不碰 .lrcat；`import_photos` 不返回 photo id、`export_photos` 不返回文件名。仅 macOS/Windows 有 Lightroom。 | **复用为真实 Lightroom 适配的下游**：`RealLightroomMcpAdapter` 严格白名单（import_photos、get_photo_metadata、apply_develop_preset、export_photos、list_develop_presets、search_photos），toolset 只开 `develop`；以库内文件路径映射照片；每次导出一张到全新空目录。仅用假 MCP stdio 服务器在 Linux 上做接口级测试 → **待 Mac 实机验证**。 |
| hktkzyx/ingest | `9706bd2ff1cffacbde21c419bf3fba37a973be7a` | MIT | 导入工具，但有“快速跳过”路径（按大小/名字判断已存在）与 xxHash64——违背“目标已存在必须按内容 SHA-256 比对”和“读回校验”要求。 | **不复用代码**；只借鉴“按卡/批次组织”的想法。 |
| ingesto | `286b6ed179aa6ca78791d508b6251dc642052311` | **GPL-3.0** | GPL 不得进入闭源核心。 | **不复用、不拷贝、不链接**。 |

## 3. 总决策

1. 自研 Photo Core（Python 3.13 + SQLite + stdlib，MCP/Pillow 为仅有第三方依赖，均为宽松许可证）。
2. Ingest 引擎自写：O_NOFOLLOW 只读源、流式 SHA-256、`.part` 临时文件 + fsync + 读回校验、硬链接无覆盖提交、提交后再读回校验。
3. 集成面：stdio MCP 服务，工具集中没有任意路径读写、shell、删除、审批工具。
4. Lightroom：抽象适配器；Mock 为 Linux 上验证用（明确标注 MOCK）；真实适配只通过 lightroom-mcp，不直接碰 .lrcat、不改 XMP/ACR、不用模拟鼠标。
5. 无 GPL 代码；无密钥入库。

## 4. 需要用户授权/后续的事项

- 私有 GitHub 仓库核查（需 GitHub App 授权）。
- 在 Mac 上运行 deepseek-harness 需要 Node ≥ 24.9。
- 真实 Lightroom / macOS 验收（见 `docs/MACOS_HANDOFF.md`）。
