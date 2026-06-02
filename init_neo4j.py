"""Initialize or verify the Neo4j projection of the JSON architecture knowledge base."""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "apps", "agent-runtime"))
load_dotenv()

from agent_runtime.architecture_styles import load_normalized_styles
from agent_runtime.neo4j_kb import Neo4jKnowledgeBase


URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))


def verify_graph() -> dict:
    """Return counts used by acceptance checks without mutating the graph."""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        row = session.run(
            """
            CALL () {
                MATCH (s:ArchitectureStyle)
                RETURN count(s) AS styles
            }
            CALL () {
                MATCH (c:Characteristic)
                RETURN count(c) AS characteristics
            }
            CALL () {
                MATCH (u:UseCase)
                RETURN count(u) AS usecases
            }
            CALL () {
                MATCH (k:Keyword)
                RETURN count(k) AS keywords
            }
            CALL () {
                MATCH ()-[hp:HAS_PRO]->()
                RETURN count(hp) AS has_pro
            }
            CALL () {
                MATCH ()-[hc:HAS_CON]->()
                RETURN count(hc) AS has_con
            }
            CALL () {
                MATCH ()-[sf:SUITABLE_FOR]->()
                RETURN count(sf) AS suitable_for
            }
            CALL () {
                MATCH ()-[hk:HAS_KEYWORD]->()
                RETURN count(hk) AS has_keyword
            }
            RETURN styles, characteristics, usecases, keywords, has_pro, has_con, suitable_for, has_keyword
            """
        ).single()
        result = dict(row) if row else {}
    driver.close()
    return result


def graph_has_required_data(stats: dict, expected_styles: int | None = None) -> bool:
    """Require an exact JSON style count and non-empty managed graph relations."""
    if expected_styles is None:
        expected_styles = len(load_normalized_styles())
    required_counts = (
        "characteristics",
        "usecases",
        "keywords",
        "has_pro",
        "has_con",
        "suitable_for",
        "has_keyword",
    )
    return stats.get("styles") == expected_styles and all(stats.get(name, 0) > 0 for name in required_counts)


def init_graph(reset: bool = False) -> dict:
    """Reconcile Neo4j from JSON, optionally clearing the existing demo graph first."""
    kb = Neo4jKnowledgeBase()
    if not kb.is_available():
        raise ConnectionError(kb.unavailable_reason)
    if reset:
        with kb.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("已清空旧数据，开始从 JSON 重建知识图谱...")
    else:
        print("保留现有图谱数据，开始从 JSON 执行幂等对账...")
    if not kb.reconcile_from_json():
        raise ConnectionError(kb.unavailable_reason)
    stats = verify_graph()
    expected_styles = len(load_normalized_styles())
    print("\n[统计] 知识图谱统计:")
    print(f"   架构风格: {stats.get('styles', 0)} / {expected_styles} 种")
    print(f"   Characteristic: {stats.get('characteristics', 0)}")
    print(f"   UseCase: {stats.get('usecases', 0)}")
    print(f"   Keyword: {stats.get('keywords', 0)}")
    print(f"   HAS_PRO: {stats.get('has_pro', 0)}")
    print(f"   HAS_CON: {stats.get('has_con', 0)}")
    print(f"   SUITABLE_FOR: {stats.get('suitable_for', 0)}")
    print(f"   HAS_KEYWORD: {stats.get('has_keyword', 0)}")
    kb.close()
    return stats


def _print_verification(stats: dict) -> None:
    expected_styles = len(load_normalized_styles())
    print("\nNeo4j 图谱验证结果:")
    print(f"   ArchitectureStyle: {stats.get('styles', 0)} / {expected_styles}")
    print(f"   Characteristic: {stats.get('characteristics', 0)}")
    print(f"   UseCase: {stats.get('usecases', 0)}")
    print(f"   Keyword: {stats.get('keywords', 0)}")
    print(f"   HAS_PRO: {stats.get('has_pro', 0)}")
    print(f"   HAS_CON: {stats.get('has_con', 0)}")
    print(f"   SUITABLE_FOR: {stats.get('suitable_for', 0)}")
    print(f"   HAS_KEYWORD: {stats.get('has_keyword', 0)}")


if __name__ == "__main__":
    print(f"连接 Neo4j: {URI}")
    try:
        if "--verify-only" in sys.argv:
            verification_stats = verify_graph()
            _print_verification(verification_stats)
            if not graph_has_required_data(verification_stats):
                print("\n验证未通过：图谱与 JSON 权威数据源不一致，请运行初始化。")
                sys.exit(2)
            print("\n验证通过：图谱风格数量与 JSON 一致，核心节点与关系已存在。")
        else:
            init_graph(reset=("--reset" in sys.argv))
            print("\nNeo4j 知识图谱初始化完成")
    except Exception as error:
        print(f"\n连接失败: {error}")
        print("请确保:")
        print("  1. Neo4j 服务已启动 (本地: neo4j start, 或 AuraDB 实例运行中)")
        print("  2. .env 中 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 配置正确")
        print("  3. 使用项目虚拟环境: .venv-win\\Scripts\\python.exe init_neo4j.py")
        sys.exit(1)
