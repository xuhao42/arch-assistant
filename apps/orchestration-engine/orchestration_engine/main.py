"""架构推荐编排服务入口。

本服务负责接收架构推荐分析请求，将用户原始需求转交给 Agent Runtime
完成特征抽取、候选召回、拓扑生成和报告生成，并在可用时调用 LLM Router
对报告做非破坏性润色。服务对外提供同步分析接口、SSE 流式分析接口和健康检查接口。

完整流水线:
  User Input -> Agent Runtime -> optional LLM polish -> response/cache
"""
import os, json, time, asyncio, hashlib
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

# ── Config ─────────────────────────────────────────
LLM_ROUTER_URL = os.getenv("LLM_ROUTER_HOST", "http://localhost:8002")
AGENT_RUNTIME_URL = os.getenv("AGENT_RUNTIME_HOST", "http://localhost:8003")
CACHE_TTL = int(os.getenv("RESPONSE_CACHE_TTL", "300"))
CACHE_MAX = int(os.getenv("RESPONSE_CACHE_MAX", "500"))

# 仅缓存完整报告结果，避免中间阶段数据被复用后与最终报告不一致。
_cache: dict[str, tuple[dict, float]] = {}  # (full_response, timestamp)

def _cache_key(prompt: str) -> str:
    """为语义上相同的短期请求生成稳定缓存键。

    Args:
        prompt: 用户提交的原始架构需求文本。

    Returns:
        经过首尾空白裁剪和大小写归一化后的 SHA-256 摘要。
    """
    return hashlib.sha256(prompt.strip().lower().encode()).hexdigest()

# ── Models ─────────────────────────────────────────
class PipelineRequest(BaseModel):
    """架构推荐流水线的输入请求。

    Attributes:
        prompt: 用户对业务场景、约束或技术诉求的自然语言描述。
        session_id: 调用方用于串联日志、流式事件和前端会话状态的标识。
    """

    prompt: str
    session_id: str = "default"

class StepInfo(BaseModel):
    """记录编排流水线中单个阶段的执行状态。

    Attributes:
        name: 阶段名称，用于前端展示和问题定位。
        status: 阶段执行结果，例如 success、error 或 skipped。
        output: 阶段产生的摘要数据，避免把完整大对象塞进步骤日志。
    """

    name: str
    status: str
    output: dict | None = None

class PipelineResponse(BaseModel):
    """架构推荐流水线的聚合输出。

    Attributes:
        session_id: 与请求对应的会话标识。
        features: Agent Runtime 从用户需求中抽取的业务和技术约束。
        candidates: 候选架构方案列表。
        topology: 推荐方案的拓扑结构描述。
        case_matches: 知识库或案例库匹配结果。
        report: 面向用户展示的最终架构推荐报告。
        steps: 编排阶段执行记录，用于前端进度展示和排障。
        cached: 当前响应是否来自短期完整响应缓存。
    """

    session_id: str
    features: dict | None = None
    candidates: list | None = None
    topology: dict | None = None
    case_matches: list | None = None
    report: str | None = None
    steps: list[StepInfo] = []
    cached: bool = False

# ── HTTP Client ────────────────────────────────────
client = httpx.AsyncClient(timeout=120.0)

async def call_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """调用下游服务并对临时故障做有限重试。

    Args:
        method: HTTP 方法。
        url: 下游服务接口地址。
        **kwargs: 透传给 httpx 的请求参数，例如 json、timeout。

    Returns:
        下游返回的 HTTP 响应；4xx 会直接交给调用方处理，避免掩盖业务校验错误。

    Raises:
        HTTPException: 下游连续返回 5xx 或最终不可达时抛出网关错误。
    """

    for attempt in range(3):
        try:
            r = await client.request(method, url, **kwargs)
            # 只重试 5xx，避免把参数错误、鉴权错误等调用方问题误判为瞬时故障。
            if r.status_code < 500:
                return r
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
    raise HTTPException(status_code=502, detail="Upstream service unavailable")

# ── App ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理编排服务生命周期中的共享 HTTP 客户端。

    Args:
        app: FastAPI 应用实例，当前仅用于满足生命周期钩子签名。

    Yields:
        控制权交还给 FastAPI 运行期；服务退出时关闭全局异步客户端。
    """

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
    """返回服务存活状态。

    Returns:
        固定的服务名称和健康状态，用于本地调试、网关探活或容器健康检查。
    """

    return {"service": "orchestration-engine", "status": "healthy"}

@app.post("/api/v1/analyze", response_model=PipelineResponse)
async def analyze(request: PipelineRequest):
    """运行同步架构推荐流水线。

    该接口将用户需求交给 Agent Runtime 完成核心架构分析，随后在报告已生成且
    LLM Router 可用时进行可选润色。完整结果会写入短期缓存，以降低重复课程
    场景或前端重试带来的下游调用成本。

    Args:
        request: 包含用户需求和会话标识的分析请求。

    Returns:
        聚合后的架构推荐结果、阶段执行记录和缓存命中状态。

    Raises:
        HTTPException: Agent Runtime 核心分析失败时返回服务端错误。
    """

    t0 = time.perf_counter()
    logger.info(f"📥 [{request.session_id}] 收到请求: {request.prompt[:80]}...")
    
    # 缓存以归一化后的 prompt 为粒度；session_id 不参与缓存键，
    # 这样同一需求在不同前端会话中也能复用完整推荐结果。
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
    
    # Agent Runtime 是核心业务下游，负责编排多 Agent 完成特征、候选、拓扑、
    # 案例匹配和报告生成；这里不拆分其中间阶段，避免入口服务重复承载业务规则。
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
    
    # 报告润色是体验增强而非核心推荐依据；失败时保留 Agent Runtime 的原始报告，
    # 避免可选下游异常导致已完成的架构分析无法返回。
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
    
    # 仅在存在最终报告时缓存，确保缓存命中返回的是可直接展示的完整分析结果。
    # 超过容量后淘汰最早写入项，保持内存占用在课程项目可控范围内。
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
    """代理 Agent Runtime 的流式架构分析事件。

    该接口负责把用户请求转发到 Agent Runtime 的 SSE 接口，并原样透传下游阶段事件。
    前端可以据此逐步展示 features、candidates、report 等结果，避免等待完整报告生成。

    Args:
        request: 包含用户需求和会话标识的分析请求。

    Returns:
        text/event-stream 响应；下游异常会被转换为 error 事件写回前端。
    """

    async def event_stream():
        """生成面向前端的 SSE 事件流。

        Yields:
            已符合 SSE data 行格式的状态、业务阶段或错误事件。
        """

        # 先发出本地状态事件，让前端能立即进入进行中状态；后续事件由下游接管。
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
                            # Agent Runtime 已经输出 SSE data 行，这里只补齐事件分隔符。
                            yield line + "\n\n"
        except Exception as e:
            # 流式接口不能在响应开始后再抛 HTTPException，因此用 error 事件通知前端收尾。
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
