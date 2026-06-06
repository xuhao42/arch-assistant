"""Orchestration Engine - 微服务编排引擎

完整流水线:
  User Input → classify_intent → agent_analysis → knowledge_retrieval → generate_report → response

本服务负责把网关请求编排到 Agent Runtime 和 LLM Router。
它保留响应缓存、上游重试和 SSE 透传逻辑，是前端体验和后端推理服务之间的协调层。
"""
import os, json, time, asyncio, hashlib
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

# ── 配置：通过环境变量决定上游服务地址和响应缓存策略 ──
LLM_ROUTER_URL = os.getenv("LLM_ROUTER_HOST", "http://localhost:8002")
AGENT_RUNTIME_URL = os.getenv("AGENT_RUNTIME_HOST", "http://localhost:8003")
CACHE_TTL = int(os.getenv("RESPONSE_CACHE_TTL", "300"))
CACHE_MAX = int(os.getenv("RESPONSE_CACHE_MAX", "500"))

_cache: dict[str, tuple[dict, float]] = {}  # (full_response, timestamp)

def _cache_key(prompt: str) -> str:
    """把用户需求规范化后生成缓存键，避免大小写和首尾空白影响命中。"""
    return hashlib.sha256(prompt.strip().lower().encode()).hexdigest()

# ── 请求/响应模型：定义网关与编排层之间的 API 契约 ──
class PipelineRequest(BaseModel):
    """前端一次分析请求进入编排层后的请求体。"""
    prompt: str
    session_id: str = "default"

class StepInfo(BaseModel):
    """记录流水线中单个步骤的执行状态，便于前端展示和排障。"""
    name: str
    status: str
    output: dict | None = None

class PipelineResponse(BaseModel):
    """编排层返回给网关的完整架构分析响应。"""
    session_id: str
    features: dict | None = None
    candidates: list | None = None
    topology: dict | None = None
    case_matches: list | None = None
    report: str | None = None
    steps: list[StepInfo] = []
    cached: bool = False

# ── HTTP 客户端：统一管理上游调用超时和重试 ──
client = httpx.AsyncClient(timeout=120.0)

async def call_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """调用上游服务并对临时失败做最多三次重试。"""
    for attempt in range(3):
        try:
            r = await client.request(method, url, **kwargs)
            if r.status_code < 500:
                return r
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
    raise HTTPException(status_code=502, detail="Upstream service unavailable")

# ── 应用入口：编排服务的生命周期和路由定义 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子，服务退出时关闭共享 HTTP 客户端。"""
    logger.info("🎯 Architecture Orchestration Engine starting...")
    yield
    await client.aclose()

app = FastAPI(
    title="Architecture Recommendation Orchestration Engine",
    version="1.0.0",
    lifespan=lifespan,
)

@app.get("/health")
async def health():
    """健康检查接口，供网关、Docker 和验收脚本探活。"""
    return {"service": "orchestration-engine", "status": "healthy"}

@app.post("/api/v1/analyze", response_model=PipelineResponse)
async def analyze(request: PipelineRequest):
    """运行完整的架构推荐流水线"""
    t0 = time.perf_counter()
    logger.info(f"📥 [{request.session_id}] 收到请求: {request.prompt[:80]}...")
    
    # 缓存检查：相同需求在 TTL 内直接复用完整响应，降低 LLM 和 Agent 调用成本。
    key = _cache_key(request.prompt)
    if CACHE_TTL > 0 and key in _cache:
        cached_data, cached_ts = _cache[key]
        if time.time() - cached_ts < CACHE_TTL:
            logger.info("⚡ 缓存命中（完整响应）")
            return PipelineResponse(
                session_id=request.session_id,
                features=cached_data.get("features"),
                candidates=cached_data.get("candidates"),
                topology=cached_data.get("topology"),
                case_matches=cached_data.get("case_matches"),
                report=cached_data.get("report"),
                steps=[StepInfo(name="cache_hit", status="success")],
                cached=True,
            )
    
    steps = []
    
    # Step 1: 调用 Agent Runtime（三 Agent 协作），这是结构化特征和候选架构的主来源。
    logger.info("🤖 调用 Agent Runtime...")
    try:
        r = await call_with_retry(
            "POST", f"{AGENT_RUNTIME_URL}/api/v1/run",
            json={"prompt": request.prompt, "session_id": request.session_id},
            timeout=180.0,
        )
        agent_result = r.json()
        steps.append(StepInfo(name="agent_analysis", status="success",
            output={"stage": agent_result.get("current_stage")}))
    except Exception as e:
        logger.error(f"Agent Runtime 调用失败: {e}")
        steps.append(StepInfo(name="agent_analysis", status="error"))
        raise HTTPException(status_code=500, detail=f"Agent analysis failed: {e}")
    
    features = agent_result.get("features")
    candidates = agent_result.get("candidates")
    topology = agent_result.get("topology")
    case_matches = agent_result.get("case_matches")
    report = agent_result.get("report")
    
    # Step 2: LLM 润色报告（可选），失败不影响主推荐结果返回。
    if report and LLM_ROUTER_URL:
        try:
            logger.info("✨ LLM 润色报告...")
            r = await call_with_retry(
                "POST", f"{LLM_ROUTER_URL}/api/v1/generate",
                json={
                    "messages": [
                        {"role": "system", "content": "你是一个软件架构报告编辑。请润色以下评估报告，使其更加专业和结构化。保持原有内容和结论不变。"},
                        {"role": "user", "content": report},
                    ],
                    "temperature": 0.2,
                },
                timeout=60.0,
            )
            polished = r.json().get("content", report)
            report = polished
            steps.append(StepInfo(name="report_polish", status="success"))
        except Exception as e:
            logger.warning(f"LLM 润色失败(非致命): {e}")
            steps.append(StepInfo(name="report_polish", status="skipped"))
    
    # 缓存完整响应：达到容量上限时淘汰最旧条目，避免内存无限增长。
    if report and CACHE_TTL > 0:
        if len(_cache) >= CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k][1])
            _cache.pop(oldest, None)
        _cache[key] = ({"features": features, "candidates": candidates, "topology": topology, "case_matches": case_matches, "report": report}, time.time())
    
    elapsed = round((time.perf_counter() - t0) * 1000)
    logger.info(f"✅ [{request.session_id}] 流水线完成 ({elapsed}ms)")
    
    return PipelineResponse(
        session_id=request.session_id,
        features=features,
        candidates=candidates,
        topology=topology,
        case_matches=case_matches,
        report=report,
        steps=steps,
    )

@app.post("/api/v1/analyze/stream")
async def analyze_stream(request: PipelineRequest):
    """把 Agent Runtime 的 SSE 分析事件透传给网关。"""
    async def event_stream():
        """内部流式生成器，负责建立上游流连接并逐行转发。"""
        yield f"data: {json.dumps({'event': 'status', 'message': '🤖 正在调用 Agent Runtime...'})}\n\n"
        
        try:
            async with httpx.AsyncClient() as stream_client:
                async with stream_client.stream(
                    "POST",
                    f"{AGENT_RUNTIME_URL}/api/v1/run/stream",
                    json={"prompt": request.prompt, "session_id": request.session_id},
                    timeout=180.0,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
