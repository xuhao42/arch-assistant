# LLM Router 镜像：统一代理项目内部的模型生成请求。
FROM python:3.11-slim
WORKDIR /app
# 这里只安装 HTTP API 代理所需依赖，第三方模型密钥由运行环境注入。
RUN pip install --no-cache-dir fastapi uvicorn loguru httpx pydantic
COPY llm_router/ /app/llm_router/
ENV PYTHONPATH=/app
EXPOSE 8002
# 对外监听 8002，供 Orchestration Engine 调用报告润色和生成接口。
CMD ["uvicorn", "llm_router.main:app", "--host", "0.0.0.0", "--port", "8002"]
