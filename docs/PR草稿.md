# PR 草稿：统一 JSON 与 Neo4j 架构知识

## Summary

本 PR 将 `data/architecture_styles.json` 固定为 21 种架构风格的唯一权威数据源，并把 Neo4j 调整为可自动恢复的图谱投影。这样可以避免 JSON fallback 与 Neo4j 图谱分别维护导致的数据漂移。

## What Changed

- 新增 `architecture_styles.py`，统一处理 JSON 读取、归一化、摘要生成和原子追加写入。
- 将 Neo4j 架构节点、优缺点、适用场景和关键词关系改为从 JSON 幂等对账。
- 新增 `data/architecture_relations.json`，独立维护 `COMPLEMENTS`、`RELATED_TO` 架构间关系。
- 删除 Neo4j 中已经不在 JSON 内的旧风格和孤立节点，重建受管关系，避免删除后的关键词或场景继续残留。
- `POST /api/v1/knowledge` 先写 JSON，再尝试同步 Neo4j。图谱不可用时保留 JSON 写入并返回 `fallback=true`。
- Neo4j 连接或查询失败时标记为不可用，冷却窗口后重新探测并从 JSON 执行全量对账。
- Docker Compose 使用可写 `./data:/data`，并增加 `NEO4J_DOCKER_URI`。
- DeepSeek 与 OpenAI 分别使用自己的默认 endpoint 和 model。
- `init_neo4j.py --verify-only` 校验 JSON 风格数量和核心节点、关系，并兼容 Windows GBK 控制台。

## Current Baseline

- architecture styles: `21`
- normalized keyword relations: `270`
- unique keyword nodes: `267`
- architecture relations: `4`
- regression tests: `21`

## Validation

- `.\.venv-win\Scripts\python.exe -m unittest discover -s tests -v`
- `.\.venv-win\Scripts\python.exe -m py_compile apps/agent-runtime/agent_runtime/architecture_styles.py apps/agent-runtime/agent_runtime/graph.py apps/agent-runtime/agent_runtime/main.py apps/agent-runtime/agent_runtime/neo4j_kb.py init_neo4j.py tests/test_architecture_styles.py tests/test_knowledge_api.py tests/test_neo4j_review_fixes.py`
- `git diff --check origin/master...HEAD`
- GitHub PR merge state: `MERGEABLE / CLEAN`

## Residual Risk

- 完整 LLM 端到端效果依赖外部模型 API 稳定性。
- Neo4j 仍是可选增强层；不可用时系统按设计回退 JSON。
- 批量 29 场景推荐验收应在最终演示前重新运行并刷新结果。
