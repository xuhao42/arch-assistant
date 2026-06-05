"""架构助手 API Gateway 服务入口。

本服务负责接收浏览器和外部客户端的架构分析请求，统一暴露健康检查、
同步分析、SSE 流式分析和前端页面访问能力。网关不直接执行业务推理，
而是将分析请求转发给 orchestration-engine，并负责把下游错误转换为
面向调用方稳定的 HTTP 响应。
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
# 全局复用 AsyncClient，避免每次请求都重新建立连接；关闭逻辑放在 lifespan，
# 确保 uvicorn 停止时释放连接池资源。
client = httpx.AsyncClient(timeout=180.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理网关进程生命周期中的共享下游连接。

    Args:
        app: FastAPI 应用实例，当前仅用于满足 lifespan 协议。

    Yields:
        控制权交还给 FastAPI，以便应用在运行期间复用全局 HTTP 客户端。
    """
    logger.info("🌐 API Gateway starting...")
    yield
    await client.aclose()

app = FastAPI(title="Architecture Assistant API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 前端资源优先使用 Vue 构建产物，便于正式演示和部署；当 dist 不存在时，
# 保留旧版单文件页面作为课程答辩或本地开发的兜底入口。
APP_DIR = os.path.dirname(__file__)
LEGACY_HTML_PATH = os.path.join(APP_DIR, "templates", "index.html")
FRONTEND_DIST = os.getenv(
    "FRONTEND_DIST",
    os.path.abspath(os.path.join(APP_DIR, "..", "..", "..", "frontend", "dist")),
)
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")

if os.path.exists(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="frontend-assets")

class AnalyzeRequest(BaseModel):
    """架构分析请求的网关入参。

    Attributes:
        prompt: 用户描述的业务场景、约束和架构需求，会原样交给编排引擎。
        session_id: 前端或调用方传入的会话标识，用于串联日志和流式事件。
    """

    prompt: str
    session_id: str = "default"

@app.get("/health")
async def health():
    """返回网关自身健康状态。

    Returns:
        服务名和健康状态；该接口只验证网关进程存活，不级联探测下游服务，
        避免下游短暂抖动导致容器健康检查误判。
    """
    return {"service": "api-gateway", "status": "healthy"}

@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest):
    """将同步架构分析请求代理到编排引擎。

    Args:
        req: 已通过 Pydantic 校验的用户架构分析请求。

    Returns:
        orchestration-engine 生成的结构化分析结果，通常包含 features、
        candidates、topology、case_matches、report 和 steps。

    Raises:
        HTTPException: 下游返回非 200 时透传其状态码；下游不可达时返回 502，
        让前端能够区分业务失败和服务链路故障。
    """
    try:
        r = await client.post(
            f"{ORCHESTRATION_URL}/api/v1/analyze",
            json=req.model_dump(),
            timeout=180.0,
        )
        if r.status_code != 200:
            # 只截取下游错误片段，避免模型报告或堆栈过长时把网关响应撑大。
            raise HTTPException(status_code=r.status_code, detail=r.text[:500])
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Orchestration engine unreachable: {e}")

@app.post("/api/v1/analyze/stream")
async def analyze_stream(req: AnalyzeRequest):
    """将 SSE 架构分析请求流式代理到编排引擎。

    Args:
        req: 用户架构分析请求，prompt 用于生成报告，session_id 用于关联事件。

    Returns:
        text/event-stream 响应；网关逐行转发下游事件，使前端能分阶段展示
        features、candidates、report 等结果，而不用等待完整报告生成。
    """
    async def proxy():
        """逐行桥接下游 SSE 数据，保持浏览器端事件消费模型稳定。

        Yields:
            已按 SSE 空行分隔的事件片段。下游通常已经返回 data 行，这里只补齐
            事件边界，避免前端 EventSource 收不到阶段性更新。
        """
        async with client.stream("POST", f"{ORCHESTRATION_URL}/api/v1/analyze/stream",
                                  json=req.model_dump(), timeout=180.0) as r:
            async for line in r.aiter_lines():
                if line:
                    yield line + "\n\n"
    return StreamingResponse(proxy(), media_type="text/event-stream")

@app.get("/")
async def home():
    """返回默认前端页面。

    Returns:
        优先返回 Vue 构建后的 index.html；如果当前环境未构建前端，则返回旧版
        单文件演示页面，保证后端服务单独启动时仍有可访问入口。
    """
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    with open(LEGACY_HTML_PATH, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/legacy", response_class=HTMLResponse)
async def legacy_home():
    """返回旧版单文件演示页面。

    Returns:
        HTML 字符串；该入口用于前端构建产物异常或课堂演示需要回退时保留
        最小可用界面。
    """
    with open(LEGACY_HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()
