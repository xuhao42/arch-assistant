"""
Neo4j 知识图谱初始化脚本
创建 12 种软件架构风格节点及其优缺点、适用场景的关系图

运行: python3 init_neo4j.py
要求: .env 中配置 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password123"))
# 这个脚本负责初始化架构知识图谱：创建节点、关系和统计输出。
# 运行时会把节点、特征和互补关系一次性写入 Neo4j，便于 Agent Runtime 后续做图查询增强。
# 统计输出是为了确认节点、特征和关联关系都被正确写入，而不是默默失败。

# ── 12 种架构风格完整定义 ────────────────────────
STYLES = [
    {
        "name": "分层架构 (Layered Architecture)",
        "category": "单体/模块化",
        "description": "将系统划分为表示层、业务逻辑层、数据访问层等层次，每层只依赖下层",
        "pros": ["结构简单易理解", "开发速度快", "调试方便", "学习成本低"],
        "cons": ["层间紧耦合", "难以水平扩展", "单点故障", "技术栈锁定"],
        "scenes": ["小型应用", "快速原型", "业务逻辑简单", "企业OA"],
        "keywords": ["分层", "三层", "n-tier", "单体"],
        "anti_keywords": ["微服务", "分布式", "高并发", "独立部署"],
    },
    {
        "name": "微服务架构 (Microservices Architecture)",
        "category": "分布式",
        "description": "将单一应用程序划分成一组小的服务，服务之间相互协调、互相配合",
        "pros": ["独立部署", "技术异构", "弹性伸缩", "故障隔离"],
        "cons": ["分布式运维成本高", "网络开销", "数据一致性复杂", "调试困难"],
        "scenes": ["复杂业务域划分", "大型团队协作", "高并发电商", "在线教育平台"],
        "keywords": ["微服务", "独立部署", "多团队", "技术栈多样性", "持续交付"],
        "anti_keywords": ["小项目", "个人", "简单", "单体", "快速原型", "低成本"],
    },
    {
        "name": "事件驱动架构 (Event-Driven Architecture)",
        "category": "分布式/异步",
        "description": "通过事件的生产、检测、消费来解耦系统组件的架构风格",
        "pros": ["高吞吐量", "模块解耦", "异步削峰", "实时响应"],
        "cons": ["事件溯源实现复杂度高", "调试追踪困难", "最终一致性", "消息顺序保证复杂"],
        "scenes": ["高并发场景", "异步处理", "实时消息推送", "物联网数据采集"],
        "keywords": ["事件", "消息", "异步", "实时", "Kafka", "削峰", "解耦"],
        "anti_keywords": ["简单CRUD", "强一致性事务", "同步请求响应"],
    },
    {
        "name": "CQRS (命令查询职责分离)",
        "category": "分布式/数据",
        "description": "将读操作和写操作分离到不同的模型中，分别进行优化",
        "pros": ["读写独立扩展", "查询性能优化", "模型简化", "安全性隔离"],
        "cons": ["实现复杂度高", "数据同步延迟", "运维成本高", "最终一致性"],
        "scenes": ["读写负载差异大", "复杂查询报表", "事件溯源", "银行核心交易", "Feed流推送"],
        "keywords": ["读写分离", "CQRS", "命令查询", "复杂查询", "报表", "银行", "交易", "转账", "一致性", "事务"],
        "anti_keywords": ["简单CRUD", "业务逻辑极少", "无查询需求"],
    },
    {
        "name": "管道-过滤器架构 (Pipe-Filter Architecture)",
        "category": "数据流",
        "description": "将数据处理过程组织为一系列过滤组件，通过管道连接形成处理链",
        "pros": ["组件可重用", "并行处理", "易于扩展", "每个过滤器独立测试"],
        "cons": ["不适合交互式应用", "数据格式转换开销", "错误处理复杂", "状态管理困难"],
        "scenes": ["数据ETL", "编译器设计", "音视频处理", "日志处理", "数据转换流水线"],
        "keywords": ["管道", "pipeline", "流水线", "过滤器", "ETL", "数据流", "编译器", "音视频处理", "日志处理"],
        "anti_keywords": ["交互式", "请求响应", "Web应用", "电商"],
    },
    {
        "name": "SOA (面向服务架构)",
        "category": "企业集成",
        "description": "通过企业服务总线(ESB)连接异构系统，实现服务化集成",
        "pros": ["系统集成能力强", "服务复用", "标准化接口", "遗留系统兼容"],
        "cons": ["ESB成为瓶颈", "治理复杂", "性能开销大", "敏捷性不足"],
        "scenes": ["企业集成", "遗留系统对接", "异构系统互联", "电子政务"],
        "keywords": ["SOA", "ESB", "企业集成", "遗留系统", "异构系统", "企业服务总线", "WebService", "SOAP"],
        "anti_keywords": ["新系统", "敏捷", "微服务", "初创", "快速迭代"],
    },
    {
        "name": "六边形架构/端口适配器 (Hexagonal/Ports & Adapters)",
        "category": "领域驱动",
        "description": "将核心业务逻辑置于中心，通过端口和适配器隔离外部依赖",
        "pros": ["核心可独立测试", "依赖反转", "技术无关性", "易于替换外部系统"],
        "cons": ["抽象层次多", "初始设计成本高", "团队学习曲线", "过度设计风险"],
        "scenes": ["核心业务复杂", "多外部系统对接", "DDD项目", "保险理赔系统"],
        "keywords": ["六边形", "端口适配器", "DDD", "领域驱动", "防腐层", "依赖反转", "保险", "理赔", "审计追溯"],
        "anti_keywords": ["简单CRUD", "快速原型", "DDD不熟悉"],
    },
    {
        "name": "MVC架构 (Model-View-Controller)",
        "category": "单体/Web",
        "description": "将应用分为模型、视图、控制器三层，实现关注点分离",
        "pros": ["结构清晰", "开发效率高", "框架生态丰富", "适合团队分工"],
        "cons": ["Controller易膨胀", "View与Model耦合", "测试覆盖率难以保证", "不适合复杂交互"],
        "scenes": ["Web应用", "博客系统", "CMS", "快速开发", "个人项目"],
        "keywords": ["MVC", "Web应用", "博客", "CMS", "单体", "快速开发", "个人项目"],
        "anti_keywords": ["分布式", "微服务", "高并发", "独立部署", "多团队"],
    },
    {
        "name": "Space-Based架构 (基于空间的架构)",
        "category": "分布式/高性能",
        "description": "以分布式内存网格为核心，消除数据库瓶颈，实现极低延迟",
        "pros": ["极低延迟", "极高吞吐", "线性扩展", "无单点瓶颈"],
        "cons": ["实现复杂度极高", "内存成本高", "持久化策略复杂", "运维难度大"],
        "scenes": ["秒杀系统", "高频交易", "实时竞价", "游戏服务器"],
        "keywords": ["高频交易", "秒杀", "极低延迟", "空间架构", "内存网格", "实时竞价", "游戏服务器"],
        "anti_keywords": ["小规模", "简单", "低并发", "运维能力弱", "团队小"],
    },
    {
        "name": "对等架构 (Peer-to-Peer Architecture)",
        "category": "分布式/去中心化",
        "description": "节点地位对等，无中心服务器，每个节点既是客户端也是服务端",
        "pros": ["去中心化", "自组织扩展", "无单点故障", "资源利用率高"],
        "cons": ["安全控制困难", "一致性保证复杂", "NAT穿透问题", "服务质量不稳定"],
        "scenes": ["文件共享", "区块链", "CDN内容分发", "即时通讯"],
        "keywords": ["P2P", "去中心化", "点对点", "区块链", "CDN", "内容分发", "边缘节点", "全球部署"],
        "anti_keywords": ["中央控制", "强一致性", "合规监管", "事务"],
    },
    {
        "name": "Serverless架构",
        "category": "云计算/无服务器",
        "description": "开发者无需管理服务器，以函数为单位运行代码，按需自动扩缩",
        "pros": ["零运维", "自动扩缩", "按需计费", "快速上线"],
        "cons": ["冷启动延迟", "供应商锁定", "调试困难", "状态管理受限"],
        "scenes": ["定时任务", "报表生成", "事件触发处理", "API后端", "突发流量"],
        "keywords": ["Serverless", "无服务器", "函数计算", "FaaS", "Lambda", "按需", "定时", "凌晨", "报表", "无需运维"],
        "anti_keywords": ["长时间运行", "有状态", "精细控制", "延迟敏感实时系统"],
    },
    {
        "name": "插件架构/微内核 (Plugin/Microkernel Architecture)",
        "category": "模块化/可扩展",
        "description": "核心系统提供最小功能，通过插件机制扩展能力",
        "pros": ["高度可扩展", "核心稳定", "第三方集成", "按需加载"],
        "cons": ["插件接口设计困难", "版本兼容性问题", "插件质量参差", "核心功能边界模糊"],
        "scenes": ["IDE开发", "可扩展平台", "API网关", "路由中间件", "CMS"],
        "keywords": ["插件", "模块化", "IDE", "可扩展平台", "微内核", "API网关", "路由", "中间件", "限流", "认证"],
        "anti_keywords": ["简单应用", "不需扩展", "实时系统", "一次性项目"],
    },
]


def _create_schema(session):
    """Create indexes/constraints used by query and demo."""
    session.run("CREATE CONSTRAINT architecture_style_name IF NOT EXISTS FOR (s:ArchitectureStyle) REQUIRE s.name IS UNIQUE")
    session.run("CREATE INDEX characteristic_name IF NOT EXISTS FOR (c:Characteristic) ON (c.name)")
    session.run("CREATE INDEX usecase_name IF NOT EXISTS FOR (u:UseCase) ON (u.name)")
    session.run("CREATE INDEX keyword_name IF NOT EXISTS FOR (k:Keyword) ON (k.name)")


def verify_graph() -> dict:
    """Verify required labels and relation types for acceptance checks."""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        row = session.run(
            """
            CALL {
                MATCH (s:ArchitectureStyle)
                RETURN count(s) AS styles
            }
            CALL {
                MATCH (c:Characteristic)
                RETURN count(c) AS characteristics
            }
            CALL {
                MATCH (u:UseCase)
                RETURN count(u) AS usecases
            }
            CALL {
                MATCH (k:Keyword)
                RETURN count(k) AS keywords
            }
            CALL {
                MATCH ()-[hp:HAS_PRO]->()
                RETURN count(hp) AS has_pro
            }
            CALL {
                MATCH ()-[hc:HAS_CON]->()
                RETURN count(hc) AS has_con
            }
            CALL {
                MATCH ()-[sf:SUITABLE_FOR]->()
                RETURN count(sf) AS suitable_for
            }
            CALL {
                MATCH ()-[hk:HAS_KEYWORD]->()
                RETURN count(hk) AS has_keyword
            }
            RETURN styles, characteristics, usecases, keywords, has_pro, has_con, suitable_for, has_keyword
            """
        ).single()
        result = dict(row) if row else {}
    driver.close()
    return result


def graph_has_required_data(stats: dict) -> bool:
    """Return whether all core labels and managed relation types contain data."""
    required_counts = (
        "styles",
        "characteristics",
        "usecases",
        "keywords",
        "has_pro",
        "has_con",
        "suitable_for",
        "has_keyword",
    )
    return all(stats.get(name, 0) > 0 for name in required_counts)


def init_graph(reset: bool = False):
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        _create_schema(session)
        if reset:
            # Optional full reset for demo environments only.
            session.run("MATCH (n) DETACH DELETE n")
            _create_schema(session)
            print("已清空旧数据并重建索引/约束，开始写入 12 种架构风格...")
        else:
            print("保留现有图谱数据，执行幂等写入和更新...")

        for i, style in enumerate(STYLES, 1):
            name = style["name"]

            # 幂等创建/更新 ArchitectureStyle 节点
            session.run("""
                MERGE (s:ArchitectureStyle {name: $name})
                SET s.category = $category,
                    s.description = $description,
                    s.keywords = $keywords,
                    s.anti_keywords = $anti_keywords
            """, name=name, category=style["category"],
                 description=style["description"],
                 keywords=style["keywords"],
                 anti_keywords=style["anti_keywords"])

            # Remove managed relationships before rebuilding them from STYLES.
            # This keeps idempotent updates from retaining removed keywords or scenes.
            session.run("""
                MATCH (s:ArchitectureStyle {name: $name})-[r:HAS_PRO|HAS_CON|SUITABLE_FOR|HAS_KEYWORD]->()
                DELETE r
            """, name=name)

            # 创建优点 (Characteristic: pro)
            for pro in style["pros"]:
                session.run("""
                    MATCH (s:ArchitectureStyle {name: $name})
                    MERGE (c:Characteristic {name: $char_name, type: '优点'})
                    MERGE (s)-[:HAS_PRO]->(c)
                """, name=name, char_name=pro)

            # 创建缺点 (Characteristic: con)
            for con in style["cons"]:
                session.run("""
                    MATCH (s:ArchitectureStyle {name: $name})
                    MERGE (c:Characteristic {name: $char_name, type: '缺点'})
                    MERGE (s)-[:HAS_CON]->(c)
                """, name=name, char_name=con)

            # 创建适用场景 (UseCase)
            for scene in style["scenes"]:
                session.run("""
                    MATCH (s:ArchitectureStyle {name: $name})
                    MERGE (u:UseCase {name: $scene_name})
                    MERGE (s)-[:SUITABLE_FOR]->(u)
                """, name=name, scene_name=scene)

            # 创建关键词关联
            for kw in style["keywords"]:
                session.run("""
                    MATCH (s:ArchitectureStyle {name: $name})
                    MERGE (k:Keyword {name: $kw})
                    MERGE (s)-[:HAS_KEYWORD]->(k)
                """, name=name, kw=kw)

            print(f"  [{i}/12] OK {name}")

        # 创建架构之间的关联关系（共享特征/互补/互斥）
        print("\n创建架构间关联关系...")

        # 事件驱动 ←→ CQRS (互补)
        session.run("""
            MATCH (a:ArchitectureStyle {name: '事件驱动架构 (Event-Driven Architecture)'})
            MATCH (b:ArchitectureStyle {name: 'CQRS (命令查询职责分离)'})
            MERGE (a)-[:COMPLEMENTS {reason: '事件驱动为CQRS提供异步事件流转，CQRS为事件驱动提供读写优化'}]->(b)
        """)

        # 微服务 ←→ 事件驱动 (互补)
        session.run("""
            MATCH (a:ArchitectureStyle {name: '微服务架构 (Microservices Architecture)'})
            MATCH (b:ArchitectureStyle {name: '事件驱动架构 (Event-Driven Architecture)'})
            MERGE (a)-[:COMPLEMENTS {reason: '事件驱动实现微服务间异步解耦通信'}]->(b)
        """)

        # 六边形 ←→ DDD (互补)
        session.run("""
            MATCH (a:ArchitectureStyle {name: '六边形架构/端口适配器 (Hexagonal/Ports & Adapters)'})
            MATCH (b:ArchitectureStyle {name: 'CQRS (命令查询职责分离)'})
            MERGE (a)-[:COMPLEMENTS {reason: '六边形的端口抽象天然适配CQRS的读写分离模型'}]->(b)
        """)

        # 插件架构 ←→ 微内核 (自关联)
        session.run("""
            MATCH (a:ArchitectureStyle {name: '插件架构/微内核 (Plugin/Microkernel Architecture)'})
            MATCH (b:ArchitectureStyle {name: '微服务架构 (Microservices Architecture)'})
            MERGE (a)-[:RELATED_TO {reason: 'API网关场景下，插件架构处理路由中间件，微服务处理业务逻辑'}]->(b)
        """)

        print("OK 架构间关联关系创建完成")

        # 统计
        result = session.run("""
            MATCH (s:ArchitectureStyle)
            OPTIONAL MATCH (s)-[:HAS_PRO]->(p)
            OPTIONAL MATCH (s)-[:HAS_CON]->(c)
            OPTIONAL MATCH (s)-[:SUITABLE_FOR]->(u)
            OPTIONAL MATCH (s)-[:HAS_KEYWORD]->(k)
            OPTIONAL MATCH ()-[r:COMPLEMENTS|RELATED_TO]->()
            RETURN count(DISTINCT s) AS styles,
                   count(DISTINCT p) AS pros,
                   count(DISTINCT c) AS cons,
                   count(DISTINCT u) AS usecases,
                   count(DISTINCT k) AS keywords,
                   count(DISTINCT r) AS relation_count
        """)
        record = result.single()
        print(f"\n[统计] 知识图谱统计:")
        print(f"   架构风格: {record['styles']} 种")
        print(f"   优点特征: {record['pros']} 条")
        print(f"   缺点特征: {record['cons']} 条")
        print(f"   适用场景: {record['usecases']} 个")
        print(f"   关键词: {record['keywords']} 个")
        print(f"   关联关系: {record['relation_count']} 条")

    driver.close()
    print("\nNeo4j 知识图谱初始化完成")


if __name__ == "__main__":
    print(f"连接 Neo4j: {URI}")
    try:
        verify_only = "--verify-only" in sys.argv
        if verify_only:
            stats = verify_graph()
            print("\n📋 Neo4j 图谱验证结果:")
            print(f"   ArchitectureStyle: {stats.get('styles', 0)}")
            print(f"   Characteristic: {stats.get('characteristics', 0)}")
            print(f"   UseCase: {stats.get('usecases', 0)}")
            print(f"   Keyword: {stats.get('keywords', 0)}")
            print(f"   HAS_PRO: {stats.get('has_pro', 0)}")
            print(f"   HAS_CON: {stats.get('has_con', 0)}")
            print(f"   SUITABLE_FOR: {stats.get('suitable_for', 0)}")
            print(f"   HAS_KEYWORD: {stats.get('has_keyword', 0)}")
            if not graph_has_required_data(stats):
                print("\n验证未通过：至少一种核心节点或关系不存在，请先运行初始化。")
                sys.exit(2)
            print("\n验证通过：核心节点与关系已存在。")
        else:
            init_graph(reset=("--reset" in sys.argv))
    except Exception as e:
        print(f"\n连接失败: {e}")
        print("请确保:")
        print("  1. Neo4j 服务已启动 (本地: neo4j start, 或 AuraDB 实例运行中)")
        print("  2. .env 中 NEO4J_URI 配置正确")
        print("  3. 如果是 AuraDB: URI 格式为 neo4j+s://<id>.databases.neo4j.io")
        print("  4. 命令示例: python init_neo4j.py --reset  或  python init_neo4j.py --verify-only")
        sys.exit(1)
