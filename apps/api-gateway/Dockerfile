# API Gateway 镜像：托管构建后的 Vue 前端，并代理请求到编排引擎。
FROM python:3.11-slim
WORKDIR /app
# 网关只需要轻量 FastAPI/httpx 依赖，不包含 Agent 或 LLM 运行库。
RUN pip install --no-cache-dir fastapi uvicorn loguru httpx pydantic
# 复制网关代码和前端构建产物；若 dist 不存在，镜像构建会暴露前端构建缺失问题。
COPY apps/api-gateway/api_gateway/ /app/api_gateway/
COPY frontend/dist/ /app/frontend/dist/
# FRONTEND_DIST 指向容器内静态资源目录，供 main.py 优先返回 Vue 应用。
ENV PYTHONPATH=/app
ENV FRONTEND_DIST=/app/frontend/dist
EXPOSE 3000
# 对外监听 3000，作为浏览器访问和 API 调用的统一入口。
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "3000"]
