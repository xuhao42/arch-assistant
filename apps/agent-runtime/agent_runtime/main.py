"""架构推荐 Agent Runtime 服务入口。

本服务负责接收编排层传入的架构分析请求，调用多 Agent 图完成用户需求特征抽取、
候选架构召回、拓扑生成和评估报告生成。服务同时维护轻量级历史案例库，用于在
后续分析中注入 Few-shot 参考，并提供架构风格知识库的查询和增量写入接口。
"""
import os, sys, json, time, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from .architecture_styles import (
    DuplicateArchitectureStyleError,
    append_style_atomic,
)
from .graph import agent_graph, AgentState, get_neo4j_kb

# ── Models ─────────────────────────────────────────
class RunTaskRequest(BaseModel):
    """Agent Runtime 执行一次架构分析的请求体。

    Attributes:
        prompt: 用户原始架构需求，会进入多 Agent 图作为核心业务输入。
        session_id: 调用方会话标识，用于日志串联和跳过测试会话的案例沉淀。
        metadata: 调用方附带的扩展信息，当前入口保留字段以兼容后续链路扩展。
    """

    prompt: str
    session_id: str = "default"
    metadata: dict | None = None

class RunTaskResponse(BaseModel):
    """多 Agent 架构分析的聚合响应。

    Attributes:
        session_id: 与请求对应的会话标识。
        features: 从用户需求中抽取出的业务领域、功能诉求和质量属性等结构化特征。
        candidates: 候选架构风格列表，通常已经过知识库召回和规则校验。
        topology: 推荐方案的拓扑结构，供前端可视化和报告解释使用。
        case_matches: 历史案例命中结果，用于展示本次推荐借鉴了哪些经验。
        report: 面向用户的最终架构推荐报告。
        current_stage: Agent 图返回的最终阶段，便于排障和前端状态展示。
        elapsed_ms: 本次分析在 Agent Runtime 内部消耗的毫秒数。
    """

    session_id: str
    features: dict | None = None
    candidates: list | None = None
    topology: dict | None = None
    case_matches: list | None = None
    report: str | None = None
    current_stage: str
    elapsed_ms: float

# ── App ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理 Agent Runtime 服务生命周期。

    Args:
        app: FastAPI 应用实例，当前仅用于满足 lifespan 协议。

    Yields:
        控制权交还给 FastAPI；该服务当前没有需要显式关闭的长连接资源。
    """

    logger.info("🚀 Architecture Agent Runtime starting...")
    yield
    logger.info("Agent Runtime shutting down")

app = FastAPI(
    title="Architecture Recommendation Agent Runtime",
    version="1.0.0",
    lifespan=lifespan,
    description="Multi-Agent system for software architecture style recommendation.",
)

@app.get("/health")
async def health():
    """返回 Agent Runtime 进程存活状态。

    Returns:
        固定的服务名和健康状态。该接口只验证本进程可访问，不级联探测图谱、
        JSON 知识库或 Neo4j，避免可选依赖波动影响容器健康检查。
    """

    return {"service": "agent-runtime", "status": "healthy"}

@app.post("/api/v1/run", response_model=RunTaskResponse)
async def run_task(request: RunTaskRequest):
    """同步运行多 Agent 架构推荐流水线。

    该接口先从历史案例库检索相似需求并构造 Few-shot 上下文，再调用 Agent 图
    完成核心分析。成功返回后会尝试沉淀案例；案例保存失败不会影响本次推荐结果，
    因为知识进化是增量能力而非主流程依赖。

    Args:
        request: 包含用户需求、会话标识和扩展元数据的分析请求。

    Returns:
        包含 features、candidates、topology、case_matches 和 report 的完整结果。

    Raises:
        HTTPException: Agent 图执行失败时返回 500，调用方可据此区分核心分析失败。
    """

    t0 = time.perf_counter()
    logger.info(f"📥 Received task: {request.prompt[:80]}...")
    
    # 历史案例用于给 Agent 图补充课程验收场景中的成功经验，
    # 即使没有命中也继续执行，避免案例库冷启动时阻塞主流程。
    case_matches = _find_similar_cases(request.prompt)
    case_context = _build_case_context(case_matches)
    if case_context:
        logger.info(f"📚 知识进化: 注入 {case_context.count(chr(10))} 行案例参考")
    
    state: AgentState = {
        "messages": [],
        "user_requirement": request.prompt,
        "extracted_features": {},
        "candidate_styles": [],
        "recommendations": [],
        "evaluation_report": "",
        "topology": {},
        "current_stage": "init",
        "next_step": "",
        "case_context": case_context,
    }
    
    try:
        result = await agent_graph.ainvoke(state)
    except Exception as e:
        logger.error(f"Agent pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    # 案例沉淀属于知识进化的旁路能力；失败只记录告警，不能覆盖已完成的分析结果。
    try:
        _save_case(
            request.prompt,
            result.get("extracted_features", {}),
            result.get("candidate_styles", []),
            result.get("evaluation_report", ""),
            request.session_id,
        )
    except Exception as e:
        logger.warning(f"案例保存失败(非致命): {e}")
    
    elapsed = round((time.perf_counter() - t0) * 1000)
    logger.info(f"✅ Pipeline complete in {elapsed}ms")
    
    return RunTaskResponse(
        session_id=request.session_id,
        features=result.get("extracted_features"),
        candidates=result.get("candidate_styles"),
        topology=result.get("topology"),
        case_matches=case_matches,
        report=result.get("evaluation_report"),
        current_stage=result.get("current_stage", "unknown"),
        elapsed_ms=elapsed,
    )

@app.post("/api/v1/run/stream")
async def run_task_stream(request: RunTaskRequest):
    """以 SSE 形式流式返回 Agent 执行阶段结果。

    该接口面向前端渐进式展示场景：先返回分析状态和历史案例命中，再随着 Agent 图
    阶段推进输出 features、candidates、topology 和 report。异常会作为 error
    事件写入流中，保持浏览器端 EventSource 消费模型稳定。

    Args:
        request: 用户架构分析请求。

    Returns:
        text/event-stream 响应，事件载荷均为 JSON 字符串。
    """

    async def event_stream():
        """桥接 Agent 图事件到前端可消费的 SSE 事件。

        Yields:
            按 SSE 格式分隔的 data 事件；每类事件只携带当前阶段需要展示的数据，
            避免前端等待完整报告后才更新页面。
        """

        case_matches = _find_similar_cases(request.prompt)
        case_context = _build_case_context(case_matches)
        state: AgentState = {
            "messages": [],
            "user_requirement": request.prompt,
            "extracted_features": {},
            "candidate_styles": [],
            "recommendations": [],
            "evaluation_report": "",
            "topology": {},
            "current_stage": "init",
            "next_step": "",
            "case_context": case_context,
        }
        
        yield f"data: {json.dumps({'event': 'status', 'message': '🔍 正在分析需求...'})}\n\n"
        if case_matches:
            yield f"data: {json.dumps({'event': 'case_matches', 'data': case_matches})}\n\n"
        
        # Stream through graph steps manually
        try:
            async for event in agent_graph.astream(state):
                node_name = list(event.keys())[0] if event else "unknown"
                node_data = event.get(node_name, {})
                stage = node_data.get("current_stage", "")
                
                # 依据 Agent 图约定的阶段名称拆分事件类型，前端可以按事件名局部刷新，
                # 不需要理解后端内部节点结构。
                if "features" in stage:
                    feats = node_data.get("extracted_features", {})
                    yield f"data: {json.dumps({'event': 'features', 'data': feats})}\n\n"
                elif "matched" in stage:
                    cands = node_data.get("candidate_styles", [])
                    yield f"data: {json.dumps({'event': 'candidates', 'data': cands})}\n\n"
                elif "evaluation" in stage:
                    cands = node_data.get("candidate_styles", [])
                    yield f"data: {json.dumps({'event': 'candidates', 'data': cands})}\n\n"
                    topology = node_data.get("topology", {})
                    if topology:
                        yield f"data: {json.dumps({'event': 'topology', 'data': topology})}\n\n"
                    report = node_data.get("evaluation_report", "")
                    yield f"data: {json.dumps({'event': 'report', 'data': report})}\n\n"

            yield f"data: {json.dumps({'event': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )

# ── Knowledge Evolution ─────────────────────────
CASES_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "learned_cases.json")

def _load_cases() -> list[dict]:
    """读取历史案例库。

    Returns:
        已学习案例列表。案例库文件不存在时返回空列表，使新环境和测试环境能冷启动。
    """

    if not os.path.exists(CASES_PATH):
        return []
    import json
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_case(prompt: str, features: dict, candidates: list, report: str, session_id: str = ""):
    """自动保存一次成功分析结果，用于后续 Few-shot 案例参考。

    Args:
        prompt: 用户原始需求，用作案例去重和后续相似召回的主要文本。
        features: Agent 抽取的结构化特征。
        candidates: 本次推荐的候选架构列表。
        report: 最终报告，保存时会截断以控制本地案例库体积。
        session_id: 会话标识；测试、批处理和冒烟会话不会沉淀为真实经验。
    """

    if session_id.lower().startswith(("batch_", "test_", "smoke_", "e2e_")):
        logger.info(f"📚 知识进化: 跳过测试会话案例保存 ({session_id})")
        return
    cases = _load_cases()
    # 以归一化后的完整 prompt 去重，保留重复命中次数用于衡量案例复用价值。
    prompt_lower = prompt.strip().lower()
    for c in cases:
        if c.get("prompt", "").strip().lower() == prompt_lower:
            c["count"] = c.get("count", 1) + 1
            c["last_used"] = time.time()
            _write_cases(cases)
            return
    cases.append({
        "prompt": prompt,
        "features": features,
        "candidates": candidates,
        # 报告只保留摘要片段，避免 learned_cases.json 随着长报告快速膨胀。
        "report": report[:500],
        "count": 1,
        "created": time.time(),
        "last_used": time.time(),
    })
    _write_cases(cases)

def _write_cases(cases: list):
    """将案例库写回本地 JSON 文件。

    Args:
        cases: 已完成去重或追加后的完整案例列表。

    Side Effects:
        创建 data 目录并覆盖 learned_cases.json。该项目目前使用轻量本地文件承载
        课程场景下的知识进化数据，因此写入操作保持简单直接。
    """

    import json
    os.makedirs(os.path.dirname(CASES_PATH), exist_ok=True)
    with open(CASES_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

def _case_terms(case: dict) -> set[str]:
    """从历史案例中提取用于相似召回的业务关键词。

    Args:
        case: learned_cases.json 中的一条历史案例。

    Returns:
        由领域、功能、关键需求和头部候选架构名称组成的关键词集合。
    """

    terms = set()
    features = case.get("features", {})
    for value in [
        features.get("domain", ""),
        *features.get("features", []),
        *features.get("key_requirements", []),
        *[c.get("name", "") for c in case.get("candidates", [])[:3]],
    ]:
        value = str(value).strip().lower()
        if len(value) >= 2:
            terms.add(value)
    return terms

def _find_similar_cases(prompt: str, max_cases: int = 3) -> list[dict]:
    """检索相似历史案例，返回可展示的命中说明。

    召回逻辑优先使用结构化特征词命中用户输入；当旧案例缺少结构化特征时，
    退化为 prompt 分词匹配。这样可以兼容早期沉淀数据，同时避免无命中时
    影响主推荐流程。

    Args:
        prompt: 当前用户需求。
        max_cases: 最多返回的相似案例数量。

    Returns:
        按命中分数降序排列的案例摘要，包含命中词、推荐架构和复用次数。
    """

    cases = _load_cases()
    if not cases:
        return []
    prompt_lower = prompt.lower()
    scored = []
    for c in cases:
        matched_terms = [term for term in _case_terms(c) if term and term in prompt_lower]
        if not matched_terms:
            case_prompt = c.get("prompt", "").lower()
            matched_terms = [word for word in prompt_lower.split() if len(word) > 2 and word in case_prompt]
        score = len(matched_terms)
        if score > 0:
            scored.append((score, matched_terms[:4], c))
    scored.sort(key=lambda x: -x[0])
    matches = []
    for score, terms, case in scored[:max_cases]:
        cand_names = [c.get("name", "?") for c in case.get("candidates", [])[:2]]
        matches.append({
            "prompt": case.get("prompt", "")[:90],
            "matched_terms": terms,
            "recommendations": cand_names,
            "score": score,
            "count": case.get("count", 1),
        })
    return matches

def _build_case_context(matches: list[dict]) -> str:
    """根据相似案例命中结果生成 Agent 可读的 Few-shot 上下文。

    Args:
        matches: _find_similar_cases 返回的案例命中摘要。

    Returns:
        可直接注入 AgentState 的历史案例文本；没有命中时返回空字符串。
    """

    if not matches:
        return ""
    lines = ["\n【历史成功案例（Few-shot参考）】"]
    for case in matches:
        lines.append(f"- 需求: {case['prompt']}... → 推荐: {' > '.join(case['recommendations'])}")
    return "\n".join(lines) if len(lines) > 1 else ""

class KnowledgeEntry(BaseModel):
    """架构风格知识库的新增条目。

    Attributes:
        name: 架构风格主名称，用于 JSON 知识库去重和 Neo4j 节点写入。
        aliases: 架构风格别名，便于后续召回匹配用户不同表述。
        category: 架构分类，例如分布式、事件驱动或单体演进类。
        description: 面向用户解释该架构风格的业务语义。
        scalability: 扩展性评价。
        performance: 性能评价。
        coupling: 耦合度评价。
        complexity: 实施复杂度评价。
        deployability: 部署形态或部署便利性描述。
        testability: 可测试性评价。
        适合场景: 推荐使用该架构风格的典型业务场景。
        不适合场景: 需要降权或避免推荐的场景。
        优点: 该架构风格的主要收益。
        缺点: 该架构风格的主要风险或成本。
        关键技术: 落地该架构风格常见的技术组件。
        典型案例: 可用于报告解释的行业或课程案例。
    """

    name: str
    aliases: list[str] = []
    category: str = ""
    description: str = ""
    scalability: str = "中"
    performance: str = "中"
    coupling: str = "中"
    complexity: str = "中"
    deployability: str = "单体"
    testability: str = "中"
    适合场景: list[str] = []
    不适合场景: list[str] = []
    优点: list[str] = []
    缺点: list[str] = []
    关键技术: list[str] = []
    典型案例: list[str] = []

class FeedbackRequest(BaseModel):
    """用户手动提交案例反馈的请求体。

    Attributes:
        prompt: 用户反馈关联的原始需求。
        session_id: 会话标识，用于后续扩展真实案例沉淀或排障。
        rating: 用户对推荐结果的评分，当前接口只接收并回显。
        comment: 用户补充说明，保留给后续人工审核或知识库改进流程。
    """

    prompt: str
    session_id: str = ""
    rating: int = 5
    comment: str = ""

@app.get("/api/v1/knowledge")
async def list_knowledge():
    """列出当前 JSON 知识库中的架构风格摘要。

    Returns:
        架构风格总数和用于前端列表展示的轻量字段。接口有意不返回完整规则字段，
        避免知识库内容较大时影响管理页加载。
    """

    from .graph import load_knowledge
    styles = load_knowledge()
    return {"total": len(styles), "styles": [{"name": s["name"], "category": s.get("category",""), "scalability": s.get("scalability",""), "complexity": s.get("complexity","")} for s in styles]}

@app.post("/api/v1/knowledge")
async def add_knowledge(entry: KnowledgeEntry):
    """添加新架构风格到知识库并尝试同步到 Neo4j。

    JSON 知识库是主存储，Neo4j 用于图谱检索增强；因此 Neo4j 写入失败时只标记
    fallback，不回滚 JSON 写入，避免可选图数据库异常阻断知识扩展。

    Args:
        entry: 待新增的架构风格定义。

    Returns:
        新增状态、知识库总数和 Neo4j 同步结果。

    Raises:
        HTTPException: 架构名称重复时返回 409，提醒调用方修改或合并条目。
    """

    style = entry.model_dump()
    try:
        styles = append_style_atomic(style)
    except DuplicateArchitectureStyleError:
        raise HTTPException(status_code=409, detail=f"架构 '{entry.name}' 已存在")
    try:
        neo4j_synced = get_neo4j_kb().upsert_style(style)
    except Exception as error:
        neo4j_synced = False
        logger.warning("Neo4j 新增同步失败，已保留 JSON 写入: {}", error)
    logger.info(f"📚 知识进化: 新增架构风格 '{entry.name}'")
    return {
        "status": "added",
        "name": entry.name,
        "total": len(styles),
        "neo4j_synced": neo4j_synced,
        "fallback": not neo4j_synced,
    }

# ── Case Library ─────────────────────────────
@app.get("/api/v1/cases")
async def list_cases():
    """列出本地历史学习案例。

    Returns:
        learned_cases.json 中的完整案例列表。该接口主要用于课程演示和调试，
        因此直接暴露本地沉淀内容。
    """

    cases = _load_cases()
    return {"total": len(cases), "cases": cases}

@app.get("/api/v1/cases/stats")
async def case_stats():
    """统计历史案例库的规模和覆盖情况。

    Returns:
        案例数量、累计复用次数和已覆盖的唯一业务领域数量，用于观察知识进化效果。
    """

    cases = _load_cases()
    return {
        "total_cases": len(cases),
        "total_runs": sum(c.get("count", 1) for c in cases),
        "unique_domains": len({c.get("features", {}).get("domain", "") for c in cases if c.get("features", {}).get("domain")}),
    }

@app.post("/api/v1/cases")
async def add_case(feedback: FeedbackRequest):
    """接收用户对推荐案例的手动反馈。

    当前接口只完成反馈接收确认，不直接写入案例库，避免未经审核的低分或噪声反馈
    污染后续 Few-shot 上下文。

    Args:
        feedback: 用户提交的原始需求、评分和补充说明。

    Returns:
        接收状态、截断后的需求摘要和评分。
    """

    return {"status": "received", "prompt": feedback.prompt[:60], "rating": feedback.rating}
