"""验证 Agent Runtime 在线知识库接口的回退行为。

这些测试不启动真实 FastAPI 服务，而是动态加载 main.py 并替换图谱依赖，
确保新增知识写入 JSON 成功后，即使 Neo4j 同步失败也能给出明确 fallback 状态。
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "apps" / "agent-runtime" / "agent_runtime"


def load_module(name: str, path: Path):
    """按文件路径动态加载模块，绕开项目包名中连字符带来的导入问题。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_main():
    """加载 agent_runtime.main，并用最小假 graph 模块隔离 LangGraph 依赖。"""
    package = types.ModuleType("agent_runtime")
    package.__path__ = [str(RUNTIME)]
    sys.modules["agent_runtime"] = package
    graph = types.ModuleType("agent_runtime.graph")
    graph.agent_graph = object()
    graph.AgentState = dict
    graph.load_knowledge = lambda: []
    graph.get_neo4j_kb = lambda: None
    sys.modules["agent_runtime.graph"] = graph
    load_module("agent_runtime.architecture_styles", RUNTIME / "architecture_styles.py")
    return load_module("agent_runtime.main", RUNTIME / "main.py")


class FakeKnowledgeBase:
    """可配置同步结果的假 Neo4j 知识库。"""
    def __init__(self, synced: bool):
        self.synced = synced

    def upsert_style(self, style):
        return self.synced


class RaisingKnowledgeBase:
    """模拟 Neo4j 写入时抛异常的知识库对象。"""
    def upsert_style(self, style):
        raise RuntimeError("neo4j write failed")


class KnowledgeApiTests(unittest.TestCase):
    """覆盖新增知识接口在图谱同步成功、失败和异常时的返回语义。"""
    def test_add_knowledge_returns_synced_status_when_neo4j_upsert_succeeds(self):
        module = load_main()
        with patch.object(module, "append_style_atomic", return_value=[{"name": "New"}]), \
             patch.object(module, "get_neo4j_kb", return_value=FakeKnowledgeBase(True)):
            result = asyncio.run(module.add_knowledge(module.KnowledgeEntry(name="New")))

        self.assertTrue(result["neo4j_synced"])
        self.assertFalse(result["fallback"])

    def test_add_knowledge_keeps_json_success_when_neo4j_upsert_fails(self):
        module = load_main()
        with patch.object(module, "append_style_atomic", return_value=[{"name": "New"}]), \
             patch.object(module, "get_neo4j_kb", return_value=FakeKnowledgeBase(False)):
            result = asyncio.run(module.add_knowledge(module.KnowledgeEntry(name="New")))

        self.assertFalse(result["neo4j_synced"])
        self.assertTrue(result["fallback"])

    def test_add_knowledge_keeps_json_success_when_neo4j_client_raises(self):
        module = load_main()
        with patch.object(module, "append_style_atomic", return_value=[{"name": "New"}]), \
             patch.object(module, "get_neo4j_kb", return_value=RaisingKnowledgeBase()):
            result = asyncio.run(module.add_knowledge(module.KnowledgeEntry(name="New")))

        self.assertFalse(result["neo4j_synced"])
        self.assertTrue(result["fallback"])


if __name__ == "__main__":
    unittest.main()
