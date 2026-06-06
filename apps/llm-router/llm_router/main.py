"""LLM Router 服务入口。

该服务把项目内部的模型调用统一封装成 OpenAI 兼容接口，
当前默认代理 DeepSeek，用于报告润色、通用生成和流式生成。
编排层只依赖这里的稳定 API，不直接暴露第三方模型细节。
"""
import os, asyncio, json, time
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

# ── 请求/响应模型：描述内部服务调用 LLM Router 的协议 ──
class RouteRequest(BaseModel):
    """模型路由请求，当前只保留 prompt 以便后续扩展多模型选择。"""
    prompt: str

class RouteResponse(BaseModel):
    """模型路由结果，告诉调用方应该使用哪个 provider/model。"""
    model: str
    provider: str
    confidence: float

class GenerateRequest(BaseModel):
    """非流式或流式生成请求，采用 OpenAI Chat Completions 风格消息数组。"""
    messages: list[dict]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    provider: str = "deepseek"

class GenerateResponse(BaseModel):
    """非流式生成接口的统一响应。"""
    content: str
    model: str
    provider: str
    usage: dict | None = None

# ── 配置：第三方模型地址、密钥和默认系统提示词 ──
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM_PROMPT = """你是一个软件架构设计专家助手。你擅长：
- 分析软件系统的架构需求
- 推荐合适的架构风格（微服务、事件驱动、CQRS、分层等12种）
- 对比不同架构的优缺点
- 根据具体场景给出架构决策建议

请用专业、简洁的中文回答。如果用户问的问题不涉及软件架构，礼貌地引导回架构话题。"""

# ── 应用入口：维护共享 HTTP 客户端并暴露模型代理路由 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子，创建并释放上游模型 API 客户端。"""
    app.state.http_client = httpx.AsyncClient(timeout=120.0, limits=httpx.Limits(max_keepalive_connections=8))
    logger.info(f"LLM Router ready. Provider: deepseek, Model: {DEFAULT_MODEL}")
    yield
    await app.state.http_client.aclose()

app = FastAPI(title="Architecture LLM Router", version="1.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    """健康检查接口，同时返回当前默认 provider 和模型名。"""
    return {"service": "llm-router", "status": "healthy", "provider": "deepseek", "model": DEFAULT_MODEL}

@app.post("/api/v1/route", response_model=RouteResponse)
async def route_prompt(body: RouteRequest):
    """简单模型路由：当前版本全部直连 DeepSeek。"""
    return RouteResponse(model=DEFAULT_MODEL, provider="deepseek", confidence=1.0)

@app.post("/api/v1/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, req: Request):
    """调用 DeepSeek 非流式接口生成完整回复。"""
    client = req.app.state.http_client
    
    # 如果调用方没有提供 system 消息，则补入架构助手默认角色，统一输出风格。
    msgs = request.messages
    if not any(m.get("role") == "system" for m in msgs):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
    
    payload = {
        "model": request.model or DEFAULT_MODEL,
        "messages": msgs,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": False,
    }
    
    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            r = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                timeout=120.0,
            )
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                elapsed = round((time.perf_counter() - t0) * 1000)
                logger.info(f"LLM generate: {len(content)} chars, {elapsed}ms")
                return GenerateResponse(
                    content=content,
                    model=data.get("model", DEFAULT_MODEL),
                    provider="deepseek",
                    usage=usage,
                )
            elif r.status_code == 429:
                await asyncio.sleep(1 * (attempt + 1))
            else:
                raise HTTPException(status_code=r.status_code, detail=r.text[:200])
        except httpx.HTTPError as e:
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
            else:
                raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate/stream")
async def generate_stream(request: GenerateRequest, req: Request):
    """调用 DeepSeek 流式接口，并转换成项目内部使用的 NDJSON 增量格式。"""
    client = req.app.state.http_client
    
    msgs = request.messages
    if not any(m.get("role") == "system" for m in msgs):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
    
    payload = {
        "model": request.model or DEFAULT_MODEL,
        "messages": msgs,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": True,
    }
    
    async def stream():
        """内部流式生成器，把上游 data: chunk 转成 JSON 行。"""
        async with client.stream(
            "POST", f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=120.0,
        ) as r:
            async for line in r.aiter_lines():
                line = line.strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        yield json.dumps({"type": "done"}) + "\n"
                        continue
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield json.dumps({"type": "delta", "content": content}) + "\n"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
    
    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )
