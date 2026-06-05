"""Neo4j 架构知识图谱访问模块。

本模块负责为 Agent Runtime 提供图数据库查询与同步能力。它从本地
架构风格 JSON 文件构建 Neo4j 节点、属性和架构关系，并向上层推荐
流程返回关键词匹配、架构摘要、互补关系等上下文。

Neo4j 在本项目中是增强知识源，不是主流程的强依赖；当连接、认证或
查询失败时，调用方会继续使用本地 JSON 知识库完成推荐，保证课程演示
和本地开发环境不会因为图数据库不可用而中断。
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
        """初始化图数据库连接配置和可用性缓存。

        连接参数来自环境变量，默认指向本地 Neo4j。构造阶段不会立即建立
        网络连接，避免服务启动时因为 Neo4j 未准备好而阻断 Agent Runtime。
        """

        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
        self._driver = None
        # Neo4j 只作为增强知识源，延迟探测可以让服务在图数据库未启动时仍正常启动。
        self._available = None
        self._unavailable_reason = ""
        self._last_failure_at = 0.0
        self._reconcile_required = True
        self.retry_interval_seconds = float(os.getenv("NEO4J_RETRY_INTERVAL_SECONDS", "30"))

    @property
    def driver(self):
        """按需创建 Neo4j driver。

        Returns:
            可复用的 Neo4j driver 实例。实际网络可用性仍由 ``is_available``
            通过轻量查询确认。
        """

        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=self.auth)
        return self._driver

    def _mark_unavailable(self, error: Exception, operation: str) -> None:
        """记录 Neo4j 故障并打开 JSON fallback。

        Args:
            error: 当前连接、同步或查询阶段抛出的异常。
            operation: 便于日志定位的业务操作名称。

        Side Effects:
            缓存不可用状态和最近失败时间，后续查询会在重试间隔内直接
            走本地 JSON 知识库，避免每个 Agent 阶段都重复触发连接超时。
        """

        self._available = False
        self._last_failure_at = time.monotonic()
        # 下次 Neo4j 恢复后必须全量对账，避免故障期间 JSON 新增内容没有进入图谱。
        self._reconcile_required = True
        self._unavailable_reason = f"{operation}: {error}"
        logger.warning(f"⚠️ Neo4j {operation}失败，回退到 JSON 知识库: {error}")

    def is_available(self) -> bool:
        """检测 Neo4j 是否可用。

        Returns:
            Neo4j 当前是否可作为增强知识源使用。

        Side Effects:
            连接失败时会缓存不可用原因，并在重试间隔内避免重复探测。失败
            不会向上抛出，因为推荐主流程应继续使用 JSON fallback。
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
        """创建图谱写入所需的唯一约束和查询索引。

        Args:
            session: 已打开的 Neo4j session。

        约束保证 ArchitectureStyle 以名称为稳定主键，索引用于加速关键词、
        场景和优缺点节点的 MERGE/查询。使用 IF NOT EXISTS 是为了让同步
        过程可以重复执行，适配本地开发和服务重启后的幂等对账。
        """

        session.run("CREATE CONSTRAINT architecture_style_name IF NOT EXISTS FOR (s:ArchitectureStyle) REQUIRE s.name IS UNIQUE")
        session.run("CREATE INDEX characteristic_name IF NOT EXISTS FOR (c:Characteristic) ON (c.name)")
        session.run("CREATE INDEX usecase_name IF NOT EXISTS FOR (u:UseCase) ON (u.name)")
        session.run("CREATE INDEX keyword_name IF NOT EXISTS FOR (k:Keyword) ON (k.name)")

    def _upsert_style(self, session, style: dict) -> None:
        """写入单个架构风格及其派生关系。

        Args:
            session: 已打开的 Neo4j session。
            style: 已归一化的架构风格定义，字段来自本地 JSON 权威数据。

        单条写入会先刷新该风格的优缺点、适用场景和关键词关系，再按当前
        JSON 内容重建，避免历史关系残留影响规则匹配和演示统计。
        """

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
        # 关系随 JSON 定义变化频率较高，先删除再重建比逐条 diff 更简单且可预测。
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
        """同步在线新增或修改的单个架构风格。

        Args:
            style: 在线接口接收到的架构风格定义，允许是原始格式或已归一化格式。

        Returns:
            同步是否成功写入 Neo4j。Neo4j 不可用或写入失败时返回 False，
            调用方据此提示 fallback，但不阻断 JSON 权威数据更新。
        """

        if not self.is_available():
            return False
        if self._reconcile_required:
            # 故障恢复后的首次写入需要先全量对账，避免只写入当前 style 导致图谱缺失历史变更。
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
        """按 JSON 关系定义重建架构间关系。

        Args:
            session: 已打开的 Neo4j session。
            relations: 架构关系列表，目前只支持互补关系和相关关系。

        Raises:
            ValueError: 关系类型不在允许集合内。这里主动失败是为了避免把拼写
                错误写成新的边类型，导致查询层无法感知。
        """

        # 关系数量较小且由本地 JSON 管理，全量刷新能保证删除、改名和理由更新都被准确反映。
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
        """让 Neo4j 中的托管知识与本地 JSON 权威文件保持一致。

        Args:
            styles: 可选的架构风格列表，主要用于测试或调用方已经加载数据的场景。
            relations: 可选的架构关系列表，主要用于测试或批量同步场景。

        Returns:
            对账是否完成。失败时返回 False 并打开 JSON fallback，避免推荐链路
            暴露图数据库故障。

        Side Effects:
            会删除 Neo4j 中不再存在于 JSON 的架构风格和孤立派生节点。
        """

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
                # 派生节点没有独立业务身份，删除孤立节点可以避免统计接口展示过期知识。
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
        """确保查询前 Neo4j 可用且完成 JSON 对账。

        Returns:
            当前查询是否可以安全使用 Neo4j。返回 False 时调用方应使用空结果
            触发 JSON fallback。
        """

        if not self.is_available():
            return False
        if self._reconcile_required:
            return self.reconcile_from_json()
        return True

    @property
    def unavailable_reason(self) -> str:
        """返回最近一次 Neo4j 不可用的业务原因。

        Returns:
            最近失败操作和异常信息。调用方用于日志或响应字段，不参与业务判断。
        """

        return self._unavailable_reason

    def get_graph_stats(self) -> dict:
        """获取图谱核心节点和关系统计。

        Returns:
            包含架构风格、优点、缺点、使用场景、关键词和架构关系数量的字典。
            Neo4j 不可用或查询失败时返回空字典，供健康检查和课程验收展示降级处理。
        """

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
        """获取所有架构风格的摘要信息。

        Returns:
            面向提示词注入和规则摘要展示的扁平列表，包含名称、分类、描述、
            触发词、排除词、优点和缺点。Neo4j 不可用时返回空列表，让上层
            使用本地 JSON 摘要。
        """

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
        """根据需求特征关键词匹配候选架构风格。

        Args:
            keywords: 特征抽取 Agent 产出的需求关键词列表。
            limit: 返回的候选架构数量上限。

        Returns:
            按关键词命中数降序排列的架构风格列表，包含优缺点和命中数。
            该结果用于增强 LLM 候选召回，不直接替代规则引擎的最终校验。
        """

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
        """获取单个架构风格的完整图谱信息。

        Args:
            style_name: 架构风格名称，必须与 JSON/Neo4j 中的名称一致。

        Returns:
            架构风格详情，包含优缺点、适用场景和关系信息；未命中或 Neo4j
            不可用时返回 None。
        """

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
        """获取与指定架构互补的架构风格。

        Args:
            style_name: 架构风格名称。

        Returns:
            与当前架构存在 COMPLEMENTS 关系的架构列表，包含互补原因。
            查询会同时读取正向和反向边，因为业务上互补关系用于解释推荐组合，
            不应受 JSON 中书写方向影响。
        """

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

        Args:
            features: 特征抽取 Agent 从用户需求中提取的业务和技术关键词。

        Returns:
            可追加到架构匹配提示词中的结构化上下文文本。Neo4j 不可用时返回
            空字符串，让上层继续使用 JSON 知识库。

        下游会调用关键词匹配、全量摘要和互补关系查询，把图数据库中的知识
        压缩成 LLM 可直接利用的文本。图谱信息在这里用于“可解释增强”，
        而不是替代规则引擎或 LLM 的推理链路。
        """
        if not self._ensure_synced():
            return ""

        try:
            lines = ["【Neo4j 知识图谱上下文】"]

            # 关键词命中用于给 LLM 一个“优先关注列表”，降低候选召回只依赖模型惯性的风险。
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

            # 全量摘要保留排除词，是为了让后续候选解释能同时看到正向触发和反向约束。
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

            # 互补关系用于解释组合推荐；限制遍历范围可以避免提示词过长影响 LLM 主任务。
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
        """关闭 Neo4j driver。

        Side Effects:
            释放底层连接资源，并清空本地 driver 引用，便于测试或服务退出时
            显式回收连接。
        """

        if self._driver:
            self._driver.close()
            self._driver = None
