"""初始化或校验 Neo4j 中的架构知识图谱投影。

本脚本是知识图谱维护入口，负责读取本地 JSON 架构风格权威数据，
并调用 Agent Runtime 的 Neo4j 同步封装完成图数据库对账。它也提供
只读验证模式，供本地开发、课程验收或 CI 检查确认 Neo4j 图谱与 JSON
数据源保持一致。
"""
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
    """读取 Neo4j 图谱中课程验收关注的节点和关系数量。

    Returns:
        图谱统计结果，包含架构风格、优缺点、适用场景、关键词以及核心关系数量。

    Raises:
        neo4j.exceptions.Neo4jError: Neo4j 查询失败时由驱动向上抛出，调用入口统一提示连接配置。

    Side Effects:
        只创建短生命周期 driver 和 session 读取统计信息，不修改图谱数据。
    """

    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        # 验证统计聚焦于推荐链路真正依赖的图谱形状：
        # 风格节点必须与 JSON 完全一致，派生节点和关系必须非空，
        # 才能说明优缺点、场景和关键词召回可正常工作。
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
    """判断图谱统计是否满足初始化后的最低可用条件。

    Args:
        stats: ``verify_graph`` 返回的 Neo4j 统计结果。
        expected_styles: 期望的架构风格数量；为空时使用本地 JSON 权威数据数量。

    Returns:
        Neo4j 是否已包含完整架构风格节点，并具备推荐所需的核心派生节点和关系。
    """

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
    """从 JSON 权威数据对账 Neo4j 架构知识图谱。

    Args:
        reset: 是否先清空当前 Neo4j 数据库。演示环境需要彻底重建时使用，
            日常开发默认保留图谱并执行幂等同步，避免误删手工排查数据。

    Returns:
        对账完成后的图谱统计结果。

    Raises:
        ConnectionError: Neo4j 不可用，或 JSON 到图谱的同步过程失败。

    Side Effects:
        会根据 ``reset`` 清空或更新 Neo4j 图谱，并向终端输出初始化统计。
    """

    kb = Neo4jKnowledgeBase()
    if not kb.is_available():
        raise ConnectionError(kb.unavailable_reason)
    if reset:
        with kb.driver.session() as session:
            # reset 只用于明确要求重建的场景；默认路径走幂等对账，
            # 这样可以降低本地调试时误清空整库的风险。
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
    """按人工验收友好的格式输出图谱统计。

    Args:
        stats: ``verify_graph`` 返回的 Neo4j 统计结果。

    该函数只负责展示，不参与通过/失败判断，避免输出格式调整影响校验规则。
    """

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
            # verify-only 用于 CI 或演示前检查，不触发任何写入；
            # 如果图谱落后于 JSON，直接返回非零退出码让调用方显式初始化。
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
