"""
Neo4j 知识图谱查询模块
为 Agent Runtime 提供图数据库查询能力

使用方式:
    from .neo4j_kb import Neo4jKnowledgeBase
    kb = Neo4jKnowledgeBase()
    context = kb.query_architecture_context(features=[...])
"""
import os
import time
from typing import Optional
from neo4j import GraphDatabase
from loguru import logger
from .architecture_styles import load_normalized_styles, load_relations, normalize_style


class Neo4jKnowledgeBase:
    """Neo4j 架构知识图谱查询封装。

    这个类把连接检查、图查询和 fallback 入口统一起来。
    上层只需要调用查询方法，不需要关心图数据库是否真正可用。
    如果 Neo4j 未启动或认证失败，这里会自动转为不可用状态，交给 JSON 知识库兜底。
    """

    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
        self._driver = None
        self._available = None  # 延迟检测
        self._unavailable_reason = ""
        self._last_failure_at = 0.0
        self._reconcile_required = True
        self.retry_interval_seconds = float(os.getenv("NEO4J_RETRY_INTERVAL_SECONDS", "30"))

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=self.auth)
        return self._driver

    def _mark_unavailable(self, error: Exception, operation: str) -> None:
        self._available = False
        self._last_failure_at = time.monotonic()
        self._reconcile_required = True
        self._unavailable_reason = f"{operation}: {error}"
        logger.warning(f"⚠️ Neo4j {operation}失败，回退到 JSON 知识库: {error}")

    def is_available(self) -> bool:
        """检测 Neo4j 是否可用。

        如果连接失败，就把结果缓存为不可用，后续直接走 JSON fallback，避免每次都重试。
        输入是当前配置的连接信息，输出是布尔值；失败时不影响主流程继续运行。
        """
        if self._available is True:
            return self._available
        if self._available is False and time.monotonic() - self._last_failure_at < self.retry_interval_seconds:
            return False
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            self._available = True
            self._unavailable_reason = ""
            logger.info("✅ Neo4j 知识图谱连接成功")
        except Exception as e:
            self._mark_unavailable(e, "连接检查")
        return self._available

    def _create_schema(self, session) -> None:
        session.run("CREATE CONSTRAINT architecture_style_name IF NOT EXISTS FOR (s:ArchitectureStyle) REQUIRE s.name IS UNIQUE")
        session.run("CREATE INDEX characteristic_name IF NOT EXISTS FOR (c:Characteristic) ON (c.name)")
        session.run("CREATE INDEX usecase_name IF NOT EXISTS FOR (u:UseCase) ON (u.name)")
        session.run("CREATE INDEX keyword_name IF NOT EXISTS FOR (k:Keyword) ON (k.name)")

    def _upsert_style(self, session, style: dict) -> None:
        name = style["name"]
        session.run("""
            MERGE (s:ArchitectureStyle {name: $name})
            SET s.category = $category,
                s.description = $description,
                s.keywords = $keywords,
                s.anti_keywords = $anti_keywords
        """, name=name, category=style["category"],
             description=style["description"], keywords=style["keywords"],
             anti_keywords=style["anti_keywords"])
        session.run("""
            MATCH (s:ArchitectureStyle {name: $name})-[r:HAS_PRO|HAS_CON|SUITABLE_FOR|HAS_KEYWORD]->()
            DELETE r
        """, name=name)
        for pro in style["pros"]:
            session.run("""
                MATCH (s:ArchitectureStyle {name: $name})
                MERGE (c:Characteristic {name: $char_name, type: '优点'})
                MERGE (s)-[:HAS_PRO]->(c)
            """, name=name, char_name=pro)
        for con in style["cons"]:
            session.run("""
                MATCH (s:ArchitectureStyle {name: $name})
                MERGE (c:Characteristic {name: $char_name, type: '缺点'})
                MERGE (s)-[:HAS_CON]->(c)
            """, name=name, char_name=con)
        for scene in style["scenes"]:
            session.run("""
                MATCH (s:ArchitectureStyle {name: $name})
                MERGE (u:UseCase {name: $scene_name})
                MERGE (s)-[:SUITABLE_FOR]->(u)
            """, name=name, scene_name=scene)
        for keyword in style["keywords"]:
            session.run("""
                MATCH (s:ArchitectureStyle {name: $name})
                MERGE (k:Keyword {name: $keyword})
                MERGE (s)-[:HAS_KEYWORD]->(k)
            """, name=name, keyword=keyword)

    def upsert_style(self, style: dict) -> bool:
        """Synchronize one JSON style after an online append."""
        if not self.is_available():
            return False
        if self._reconcile_required:
            return self.reconcile_from_json()
        normalized = style if "keywords" in style else normalize_style(style)
        try:
            with self.driver.session() as session:
                self._create_schema(session)
                self._upsert_style(session, normalized)
            return True
        except Exception as error:
            self._mark_unavailable(error, "单条架构同步")
            return False

    def _sync_relations(self, session, relations: list[dict[str, str]]) -> None:
        session.run("""
            MATCH (:ArchitectureStyle)-[r:COMPLEMENTS|RELATED_TO]->(:ArchitectureStyle)
            DELETE r
        """)
        for relation in relations:
            relation_type = relation["type"]
            if relation_type not in {"COMPLEMENTS", "RELATED_TO"}:
                raise ValueError(f"Unsupported architecture relation type: {relation_type}")
            session.run(f"""
                MATCH (a:ArchitectureStyle {{name: $from_name}})
                MATCH (b:ArchitectureStyle {{name: $to_name}})
                MERGE (a)-[:{relation_type} {{reason: $reason}}]->(b)
            """, from_name=relation["from"], to_name=relation["to"], reason=relation.get("reason", ""))

    def reconcile_from_json(
        self,
        styles: Optional[list[dict]] = None,
        relations: Optional[list[dict[str, str]]] = None,
    ) -> bool:
        """Make all JSON-managed Neo4j data match the authoritative files."""
        if not self.is_available():
            return False
        normalized_styles = styles if styles is not None else load_normalized_styles()
        architecture_relations = relations if relations is not None else load_relations()
        try:
            with self.driver.session() as session:
                self._create_schema(session)
                session.run("""
                    MATCH (s:ArchitectureStyle)
                    WHERE NOT s.name IN $names
                    DETACH DELETE s
                """, names=[style["name"] for style in normalized_styles])
                for style in normalized_styles:
                    self._upsert_style(session, style)
                self._sync_relations(session, architecture_relations)
                session.run("""
                    MATCH (n)
                    WHERE (n:Characteristic OR n:UseCase OR n:Keyword)
                      AND NOT ()-->(n)
                    DETACH DELETE n
                """)
            self._reconcile_required = False
            return True
        except Exception as error:
            self._mark_unavailable(error, "全量知识图谱对账")
            return False

    def _ensure_synced(self) -> bool:
        if not self.is_available():
            return False
        if self._reconcile_required:
            return self.reconcile_from_json()
        return True

    @property
    def unavailable_reason(self) -> str:
        return self._unavailable_reason

    def get_graph_stats(self) -> dict:
        """Return key node/relation counts for acceptance demo and health check."""
        if not self._ensure_synced():
            return {}
        try:
            with self.driver.session() as session:
                row = session.run(
                    """
                    MATCH (s:ArchitectureStyle)
                    OPTIONAL MATCH (s)-[:HAS_PRO]->(p:Characteristic)
                    OPTIONAL MATCH (s)-[:HAS_CON]->(c:Characteristic)
                    OPTIONAL MATCH (s)-[:SUITABLE_FOR]->(u:UseCase)
                    OPTIONAL MATCH (s)-[:HAS_KEYWORD]->(k:Keyword)
                    OPTIONAL MATCH ()-[r:COMPLEMENTS|RELATED_TO]->()
                    RETURN count(DISTINCT s) AS styles,
                           count(DISTINCT p) AS pros,
                           count(DISTINCT c) AS cons,
                           count(DISTINCT u) AS usecases,
                           count(DISTINCT k) AS keywords,
                           count(DISTINCT r) AS relations
                    """
                ).single()
                return dict(row) if row else {}
        except Exception as e:
            self._mark_unavailable(e, "统计查询")
            return {}

    def get_all_styles_summary(self) -> list[dict]:
        """获取所有架构风格的摘要信息（含优缺点的扁平列表）"""
        if not self._ensure_synced():
            return []
        try:
            with self.driver.session() as session:
                result = session.run("""
                    MATCH (a:ArchitectureStyle)
                    OPTIONAL MATCH (a)-[:HAS_PRO]->(p:Characteristic)
                    OPTIONAL MATCH (a)-[:HAS_CON]->(c:Characteristic)
                    OPTIONAL MATCH (a)-[:HAS_KEYWORD]->(k:Keyword)
                    RETURN a.name AS name,
                           a.category AS category,
                           a.description AS desc,
                           a.keywords AS keywords,
                           a.anti_keywords AS anti_keywords,
                           collect(DISTINCT p.name) AS pros,
                           collect(DISTINCT c.name) AS cons,
                           collect(DISTINCT k.name) AS kw_list
                    ORDER BY a.name
                """)
                return [dict(record) for record in result]
        except Exception as e:
            self._mark_unavailable(e, "架构摘要查询")
            return []

    def get_styles_by_keyword(self, keywords: list[str], limit: int = 5) -> list[dict]:
        """根据关键词匹配架构风格（用于规则引擎触发）"""
        if not self._ensure_synced():
            return []
        try:
            with self.driver.session() as session:
                result = session.run("""
                    MATCH (a:ArchitectureStyle)-[:HAS_KEYWORD]->(k:Keyword)
                    WHERE k.name IN $keywords
                    WITH a, count(k) AS matches
                    ORDER BY matches DESC
                    LIMIT $limit
                    MATCH (a)-[:HAS_PRO]->(p:Characteristic)
                    MATCH (a)-[:HAS_CON]->(c:Characteristic)
                    RETURN a.name AS name,
                           a.category AS category,
                           a.description AS desc,
                           collect(DISTINCT p.name) AS pros,
                           collect(DISTINCT c.name) AS cons,
                           matches
                """, keywords=keywords, limit=limit)
                return [dict(record) for record in result]
        except Exception as e:
            self._mark_unavailable(e, "关键词查询")
            return []

    def get_style_detail(self, style_name: str) -> Optional[dict]:
        """获取单个架构风格的完整信息"""
        if not self._ensure_synced():
            return None
        try:
            with self.driver.session() as session:
                result = session.run("""
                    MATCH (a:ArchitectureStyle {name: $name})
                    OPTIONAL MATCH (a)-[:HAS_PRO]->(p:Characteristic)
                    OPTIONAL MATCH (a)-[:HAS_CON]->(c:Characteristic)
                    OPTIONAL MATCH (a)-[:SUITABLE_FOR]->(u:UseCase)
                    OPTIONAL MATCH (a)-[:COMPLEMENTS]->(comp:ArchitectureStyle)
                    OPTIONAL MATCH (a)-[:RELATED_TO]->(rel:ArchitectureStyle)
                    RETURN a.name AS name,
                           a.category AS category,
                           a.description AS desc,
                           a.keywords AS keywords,
                           a.anti_keywords AS anti_keywords,
                           collect(DISTINCT p.name) AS pros,
                           collect(DISTINCT c.name) AS cons,
                           collect(DISTINCT u.name) AS usecases,
                           collect(DISTINCT comp.name) AS complements,
                           collect(DISTINCT rel.name) AS related
                """, name=style_name)
                record = result.single()
                return dict(record) if record else None
        except Exception as e:
            self._mark_unavailable(e, "架构详情查询")
            return None

    def get_complementary_styles(self, style_name: str) -> list[dict]:
        """获取某个架构风格的互补架构（通过 COMPLEMENTS 边）"""
        if not self._ensure_synced():
            return []
        try:
            with self.driver.session() as session:
                result = session.run("""
                    MATCH (a:ArchitectureStyle {name: $name})-[r:COMPLEMENTS]->(b:ArchitectureStyle)
                    RETURN b.name AS name, b.description AS desc, r.reason AS reason
                    UNION
                    MATCH (b:ArchitectureStyle)-[r:COMPLEMENTS]->(a:ArchitectureStyle {name: $name})
                    RETURN b.name AS name, b.description AS desc, r.reason AS reason
                """, name=style_name)
                return [dict(record) for record in result]
        except Exception as e:
            self._mark_unavailable(e, "互补关系查询")
            return []

    def query_architecture_context(self, features: list[str]) -> str:
        """核心方法：根据提取的需求特征，生成图查询上下文文本。

        输入是需求特征词列表，输出是可拼接到提示词中的结构化上下文。
        下游会调用关键词匹配、全量摘要和互补关系查询，把图数据库中的知识压缩成 LLM 可直接利用的文本。
        这样做的原因是：图谱信息更适合做“可解释增强”，而不是直接替代推理链路。
        如果 Neo4j 不可用，这里会返回空串，让上层自动 fallback 到 JSON 知识库。
        """
        if not self._ensure_synced():
            return ""

        try:
            lines = ["【Neo4j 知识图谱上下文】"]

            # 1. 关键词触发：看哪些架构匹配到当前特征
            matched = self.get_styles_by_keyword(features, limit=8)
            if not self.is_available():
                return ""
            if matched:
                lines.append("\n📌 关键词匹配到的架构风格:")
                for m in matched:
                    kw_match = m.get('matches', 0)
                    lines.append(
                        f"  • {m['name']} [{m['category']}] "
                        f"(关键词命中: {kw_match}) | "
                        f"优点: {', '.join(m.get('pros', [])[:3])} | "
                        f"缺点: {', '.join(m.get('cons', [])[:2])}"
                    )

            # 2. 全量架构摘要（含触发词和排除词）
            all_styles = self.get_all_styles_summary()
            if not self.is_available():
                return ""
            if all_styles:
                lines.append("\n📋 完整架构知识库（含触发/排除规则）:")
                for s in all_styles:
                    kws = ', '.join(s.get('keywords', [])[:4])
                    antis = ', '.join(s.get('anti_keywords', [])[:3])
                    lines.append(
                        f"  - {s['name']} [{s.get('category','')}] | "
                        f"触发词: {kws} | "
                        f"排除词: {antis} | "
                        f"优点: {', '.join(s.get('pros', [])[:2])}"
                    )

            # 3. 互补关系
            lines.append("\n🔗 架构间互补关系:")
            complements_found = False
            for s in all_styles[:12]:
                comps = self.get_complementary_styles(s.get('name', ''))
                if not self.is_available():
                    return ""
                if comps:
                    complements_found = True
                    for c in comps:
                        lines.append(f"  {s['name']} ⟷ {c['name']}: {c.get('reason','优势互补')}")
            if not complements_found:
                lines.append("  (暂无)")

            return "\n".join(lines)
        except Exception as e:
            self._mark_unavailable(e, "上下文查询")
            return ""

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
