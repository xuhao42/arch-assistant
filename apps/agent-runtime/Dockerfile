FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn loguru httpx pydantic langchain langchain-openai langgraph langchain-core neo4j

COPY agent_runtime/ /app/agent_runtime/

ENV PYTHONPATH=/app
ENV ARCHITECTURE_DATA_DIR=/data
ENV DEEPSEEK_API_KEY=""
ENV DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"

EXPOSE 8003

CMD ["uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8003"]
