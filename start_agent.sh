#!/bin/bash
# WSL/Linux 下启动 Agent Runtime 的快捷脚本。
# 它进入项目目录、加载 .env 环境变量，然后以前台方式运行 8003 服务。
cd /mnt/e/workspace/UserRegister/arch-assistant
# 导出 .env 中的变量，让 DeepSeek/OpenAI/Neo4j 配置对 uvicorn 进程可见。
set -a; source .env; set +a
# exec 替换当前 shell，便于容器或终端直接接收 uvicorn 的退出码和日志。
exec uvicorn apps.agent-runtime.agent_runtime.main:app --host 0.0.0.0 --port 8003 2>&1
