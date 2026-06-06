# Orchestration Engine 镜像：协调 Agent Runtime 和 LLM Router 的调用链。
FROM python:3.11-slim
WORKDIR /app
# 编排层只需要 FastAPI 与 httpx，不直接加载模型或图谱依赖。
RUN pip install --no-cache-dir fastapi uvicorn loguru httpx pydantic
COPY orchestration_engine/ /app/orchestration_engine/
ENV PYTHONPATH=/app
EXPOSE 8001
# 对外监听 8001，供 API Gateway 转发普通分析和 SSE 分析请求。
CMD ["uvicorn", "orchestration_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
