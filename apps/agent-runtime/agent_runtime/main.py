"""Agent Runtime 服务入口。

该 FastAPI 服务负责接收编排层请求，运行 LangGraph 三 Agent
架构推荐流水线，并提供知识库维护、历史案例学习和 SSE 流式输出接口。
它是业务推理的执行层，不直接面向浏览器，而由 Orchestration Engine 调用。
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

# ── 请求/响应模型：定义编排层和 Agent Runtime 之间的服务契约 ──
class RunTaskRequest(BaseModel):
    """一次架构分析任务的请求体。"""
    prompt: str
    session_id: str = "default"
    metadata: dict | None = None

class RunTaskResponse(BaseModel):
    """三 Agent 流水线完成后的结构化响应。"""
    session_id: str
    features: dict | None = None
    candidates: list | None = None
    topology: dict | None = None
    case_matches: list | None = None
    report: str | None = None
    current_stage: str
    elapsed_ms: float

# ── 应用生命周期：启动日志和退出日志集中放在这里 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子，用于记录服务启动和关闭。"""
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
    """健康检查接口，供 Docker、编排层和验收脚本确认服务在线。"""
    return {"service": "agent-runtime", "status": "healthy"}

@app.post("/api/v1/run", response_model=RunTaskResponse)
async def run_task(request: RunTaskRequest):
    """运行三 Agent 协作流水线并一次性返回完整结果。"""
    t0 = time.perf_counter()
    logger.info(f"📥 Received task: {request.prompt[:80]}...")
    
    # 注入历史案例作为Few-shot上下文
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
    
    # 自动保存案例（知识进化）
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
    """通过 SSE 分阶段返回 Agent 执行进度和最终报告。"""
    async def event_stream():
        """内部异步生成器，把 LangGraph 节点事件转换为前端可消费的 SSE。"""
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
        
        # 手动遍历图执行事件，按阶段拆成 features、candidates、topology、report。
        try:
            async for event in agent_graph.astream(state):
                node_name = list(event.keys())[0] if event else "unknown"
                node_data = event.get(node_name, {})
                stage = node_data.get("current_stage", "")
                
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

# ── 知识进化：把真实用户需求沉淀为后续 Few-shot 参考 ──
CASES_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "learned_cases.json")

def _load_cases() -> list[dict]:
    """读取历史案例库；文件不存在时返回空列表，保证主流程无状态可启动。"""
    if not os.path.exists(CASES_PATH):
        return []
    import json
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_case(prompt: str, features: dict, candidates: list, report: str, session_id: str = ""):
    """自动保存分析案例，用于知识进化和相似需求 few-shot 增强。"""
    if session_id.lower().startswith(("batch_", "test_", "smoke_", "e2e_")):
        logger.info(f"📚 知识进化: 跳过测试会话案例保存 ({session_id})")
        return
    cases = _load_cases()
    # 去重：完全相同的 prompt 不重复存，只累计命中次数和最近使用时间。
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
        "report": report[:500],  # 截断存储
        "count": 1,
        "created": time.time(),
        "last_used": time.time(),
    })
    _write_cases(cases)

def _write_cases(cases: list):
    """把案例库写回 JSON 文件，保持中文内容不转义。"""
    import json
    os.makedirs(os.path.dirname(CASES_PATH), exist_ok=True)
    with open(CASES_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

def _case_terms(case: dict) -> set[str]:
    """从历史案例中提取可用于相似度匹配的领域、特征和推荐架构词。"""
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
    """检索相似历史案例，返回可展示的命中说明。"""
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
    """根据相似案例命中结果生成Few-shot上下文。"""
    if not matches:
        return ""
    lines = ["\n【历史成功案例（Few-shot参考）】"]
    for case in matches:
        lines.append(f"- 需求: {case['prompt']}... → 推荐: {' > '.join(case['recommendations'])}")
    return "\n".join(lines) if len(lines) > 1 else ""

class KnowledgeEntry(BaseModel):
    """在线新增架构风格的请求模型，对应 data/architecture_styles.json 的字段。"""
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
    """用户手动提交案例反馈的请求模型。"""
    prompt: str
    session_id: str = ""
    rating: int = 5  # 1-5
    comment: str = ""

@app.get("/api/v1/knowledge")
async def list_knowledge():
    """列出所有架构风格摘要，供管理界面或验收脚本快速查看知识库规模。"""
    from .graph import load_knowledge
    styles = load_knowledge()
    return {"total": len(styles), "styles": [{"name": s["name"], "category": s.get("category",""), "scalability": s.get("scalability",""), "complexity": s.get("complexity","")} for s in styles]}

@app.post("/api/v1/knowledge")
async def add_knowledge(entry: KnowledgeEntry):
    """添加新架构风格到 JSON 权威知识库，并尽力同步到 Neo4j。"""
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

# ── 案例库接口：用于查看和补充知识进化数据 ──
@app.get("/api/v1/cases")
async def list_cases():
    """列出历史学习案例，方便演示知识进化效果。"""
    cases = _load_cases()
    return {"total": len(cases), "cases": cases}

@app.get("/api/v1/cases/stats")
async def case_stats():
    """返回案例数量、累计运行次数和已覆盖领域数量。"""
    cases = _load_cases()
    return {
        "total_cases": len(cases),
        "total_runs": sum(c.get("count", 1) for c in cases),
        "unique_domains": len({c.get("features", {}).get("domain", "") for c in cases if c.get("features", {}).get("domain")}),
    }

@app.post("/api/v1/cases")
async def add_case(feedback: FeedbackRequest):
    """接收手动案例反馈；当前版本只确认接收，不直接写入推荐知识库。"""
    return {"status": "received", "prompt": feedback.prompt[:60], "rating": feedback.rating}
