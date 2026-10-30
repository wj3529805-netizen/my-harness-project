#!/usr/bin/env bash
# 只打印配置片段，不安装、不写文件、不联网。
cat <<'EOF'
# 1) 本项目 config.json 中启用真实 Lightroom 适配器（Mac 上、手工确认后）：
#    "lightroom": {
#      "adapter": "real_mcp",
#      "command": ["npx", "-y", "@mskalski/lightroom-mcp@0.26.0"],
#      "env": {"LIGHTROOM_MCP_TOOLSETS": "develop"}
#    }
#
# 2) 若想让 Codex/Claude Code 直接看见 CETACEA 工作台（stdio MCP）：
#    codex mcp add cetacea -- /ABS/PATH/.venv/bin/cetacea --home /ABS/PATH/home mcp-serve
#    （注意：不要同时把 lightroom-mcp 的 `all` 工具集直接暴露给 AI；AI 只应通过 cetacea 的白名单工具操作。）
#
# 3) deepseek-harness 的 mcp-client 片段（未实测；Harness 需要 Node >= 24.9）：
#    - id: mcp-cetacea
#      name: '@deepseek-ai/dsh-mcp-client'
#      config:
#        serverName: cetacea
#        transport: stdio
#        command: /ABS/PATH/.venv/bin/cetacea
#        args: ["--home", "/ABS/PATH/home", "mcp-serve"]
EOF
