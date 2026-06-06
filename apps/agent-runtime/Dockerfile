# Agent Runtime 镜像：承载 LangGraph 三 Agent 推理、知识库接口和 SSE 输出。
FROM python:3.11-slim

WORKDIR /app

# 安装运行 Agent Runtime 所需的 FastAPI、LangChain/LangGraph 和 Neo4j 依赖。
RUN pip install --no-cache-dir fastapi uvicorn loguru httpx pydantic langchain langchain-openai langgraph langchain-core neo4j

# 只复制当前服务包，运行时通过挂载 /data 读取架构知识库。
COPY agent_runtime/ /app/agent_runtime/

# 环境变量默认值用于容器本地演示，真实密钥应由部署环境注入。
ENV PYTHONPATH=/app
ENV ARCHITECTURE_DATA_DIR=/data
ENV DEEPSEEK_API_KEY=""
ENV DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"

EXPOSE 8003

# 以 uvicorn 启动 Agent Runtime 服务，对外监听 8003。
CMD ["uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8003"]
