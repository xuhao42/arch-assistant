"""API Gateway 服务入口。

该服务是浏览器和后端微服务之间的统一入口：托管构建后的 Vue 前端，
接收分析请求，并把普通 HTTP 或 SSE 流式请求转发给 Orchestration Engine。
"""
import os, json, asyncio
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

ORCHESTRATION_URL = os.getenv("ORCHESTRATION_HOST", "http://localhost:8001")
# 全局异步客户端复用连接池，避免每个请求重复建连。
client = httpx.AsyncClient(timeout=180.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子，负责关闭全局 httpx 客户端。"""
    logger.info("🌐 API Gateway starting...")
    yield
    await client.aclose()

app = FastAPI(title="Architecture Assistant API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

APP_DIR = os.path.dirname(__file__)
LEGACY_HTML_PATH = os.path.join(APP_DIR, "templates", "index.html")
FRONTEND_DIST = os.getenv(
    "FRONTEND_DIST",
    os.path.abspath(os.path.join(APP_DIR, "..", "..", "..", "frontend", "dist")),
)
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")

if os.path.exists(os.path.join(FRONTEND_DIST, "assets")):
    # 只有前端已经构建出 assets 目录时才挂载静态资源，开发环境可回退到 legacy 页面。
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="frontend-assets")

class AnalyzeRequest(BaseModel):
    """前端提交架构分析任务时使用的最小请求体。"""
    prompt: str
    session_id: str = "default"

@app.get("/health")
async def health():
    """健康检查接口，确认网关进程可用。"""
    return {"service": "api-gateway", "status": "healthy"}

@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest):
    """把同步分析请求转发到编排引擎，并透传其 JSON 结果。"""
    try:
        r = await client.post(
            f"{ORCHESTRATION_URL}/api/v1/analyze",
            json=req.model_dump(),
            timeout=180.0,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:500])
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Orchestration engine unreachable: {e}")

@app.post("/api/v1/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """把前端 SSE 请求流式代理到编排引擎，保持事件格式不变。"""
    async def proxy():
        """内部流式代理生成器，逐行读取上游事件并补齐 SSE 空行分隔。"""
        async with client.stream("POST", f"{ORCHESTRATION_URL}/api/v1/analyze/stream",
                                  json=req.model_dump(), timeout=180.0) as r:
            async for line in r.aiter_lines():
                if line:
                    yield line + "\n\n"
    return StreamingResponse(proxy(), media_type="text/event-stream")

@app.get("/")
async def home():
    """优先返回构建后的 Vue 首页；未构建时回退到单文件演示页面。"""
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    with open(LEGACY_HTML_PATH, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/legacy", response_class=HTMLResponse)
async def legacy_home():
    """保留原始单文件演示页，便于答辩或前端构建失败时备用。"""
    with open(LEGACY_HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()
