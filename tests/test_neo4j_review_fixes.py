import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __iter__(self):
        return iter([])

    def single(self):
        return {
            "styles": 12,
            "pros": 1,
            "cons": 1,
            "usecases": 1,
            "keywords": 1,
            "relation_count": 1,
        }


class RecordingSession:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        return FakeResult()


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session

    def close(self):
        return None


def install_neo4j_stubs(driver=None):
    neo4j = types.ModuleType("neo4j")
    exceptions = types.ModuleType("neo4j.exceptions")

    class ServiceUnavailable(Exception):
        pass

    class AuthError(Exception):
        pass

    class GraphDatabase:
        @staticmethod
        def driver(*args, **kwargs):
            return driver

    neo4j.GraphDatabase = GraphDatabase
    exceptions.ServiceUnavailable = ServiceUnavailable
    exceptions.AuthError = AuthError
    sys.modules["neo4j"] = neo4j
    sys.modules["neo4j.exceptions"] = exceptions


def load_init_neo4j(driver=None):
    install_neo4j_stubs(driver)
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv
    return load_module("test_init_neo4j", ROOT / "init_neo4j.py")


def load_neo4j_kb():
    install_neo4j_stubs()
    package = types.ModuleType("agent_runtime")
    package.__path__ = []
    sys.modules["agent_runtime"] = package
    load_module(
        "agent_runtime.architecture_styles",
        ROOT / "apps" / "agent-runtime" / "agent_runtime" / "architecture_styles.py",
    )
    return load_module(
        "agent_runtime.neo4j_kb",
        ROOT / "apps" / "agent-runtime" / "agent_runtime" / "neo4j_kb.py",
    )


def load_graph():
    langgraph = types.ModuleType("langgraph")
    langgraph_graph = types.ModuleType("langgraph.graph")
    langgraph_message = types.ModuleType("langgraph.graph.message")

    class StateGraph:
        def __init__(self, *args, **kwargs):
            pass

        def add_node(self, *args, **kwargs):
            pass

        def set_entry_point(self, *args, **kwargs):
            pass

        def add_edge(self, *args, **kwargs):
            pass

        def compile(self):
            return object()

    langgraph_graph.StateGraph = StateGraph
    langgraph_graph.END = object()
    langgraph_message.add_messages = lambda *args, **kwargs: None
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = langgraph_graph
    sys.modules["langgraph.graph.message"] = langgraph_message

    langchain_openai = types.ModuleType("langchain_openai")
    langchain_openai.ChatOpenAI = object
    sys.modules["langchain_openai"] = langchain_openai

    langchain_core = types.ModuleType("langchain_core")
    langchain_messages = types.ModuleType("langchain_core.messages")
    langchain_messages.HumanMessage = object
    langchain_messages.AIMessage = object
    langchain_messages.SystemMessage = object
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.messages"] = langchain_messages

    package = types.ModuleType("agent_runtime")
    package.__path__ = []
    sys.modules["agent_runtime"] = package
    neo4j_kb = types.ModuleType("agent_runtime.neo4j_kb")
    neo4j_kb.Neo4jKnowledgeBase = object
    sys.modules["agent_runtime.neo4j_kb"] = neo4j_kb

    return load_module(
        "agent_runtime.graph",
        ROOT / "apps" / "agent-runtime" / "agent_runtime" / "graph.py",
    )


class LlmConfigTests(unittest.TestCase):
    def test_openai_key_uses_openai_defaults(self):
        graph = load_graph()
        values = {"OPENAI_API_KEY": "openai-secret"}
        with patch.object(graph, "_read_env_value", side_effect=lambda key: values.get(key, "")):
            config = graph.resolve_llm_config()
        self.assertEqual(config["api_key"], "openai-secret")
        self.assertEqual(config["base_url"], "https://api.openai.com/v1")
        self.assertEqual(config["model"], "gpt-4o-mini")

    def test_deepseek_key_uses_deepseek_defaults(self):
        graph = load_graph()
        values = {"DEEPSEEK_API_KEY": "deepseek-secret"}
        with patch.object(graph, "_read_env_value", side_effect=lambda key: values.get(key, "")):
            config = graph.resolve_llm_config()
        self.assertEqual(config["api_key"], "deepseek-secret")
        self.assertEqual(config["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(config["model"], "deepseek-chat")


class InitNeo4jTests(unittest.TestCase):
    def test_init_script_does_not_embed_architecture_styles(self):
        module = load_init_neo4j()
        self.assertFalse(hasattr(module, "STYLES"))

    def test_verify_query_uses_scoped_subqueries(self):
        session = RecordingSession()
        module = load_init_neo4j(FakeDriver(session))
        module.verify_graph()
        query = session.queries[0][0]
        self.assertEqual(query.count("CALL () {"), 8)
        self.assertNotIn("CALL {", query)

    def test_verify_requires_core_relationships(self):
        module = load_init_neo4j()
        stats = {
            "styles": 12,
            "characteristics": 4,
            "usecases": 4,
            "keywords": 4,
            "has_pro": 0,
            "has_con": 0,
            "suitable_for": 0,
            "has_keyword": 0,
        }
        self.assertFalse(module.graph_has_required_data(stats))

    def test_idempotent_init_removes_managed_style_relationships_before_rebuild(self):
        session = RecordingSession()
        module = load_init_neo4j(FakeDriver(session))
        module.init_graph()
        queries = [query for query, _ in session.queries]
        cleanup_queries = [
            query
            for query in queries
            if "DELETE r" in query
            and "HAS_PRO|HAS_CON|SUITABLE_FOR|HAS_KEYWORD" in query
        ]
        self.assertEqual(len(cleanup_queries), 21)


class Neo4jFallbackTests(unittest.TestCase):
    def test_context_query_failure_marks_neo4j_unavailable_and_returns_empty_context(self):
        module = load_neo4j_kb()
        kb = module.Neo4jKnowledgeBase()
        kb._available = True
        kb._reconcile_required = False
        kb.get_styles_by_keyword = lambda *args, **kwargs: []
        kb.get_all_styles_summary = lambda: [{"name": "CQRS"}]

        def raise_query_failure(*args, **kwargs):
            raise RuntimeError("query failed")

        kb.get_complementary_styles = raise_query_failure
        self.assertEqual(kb.query_architecture_context([]), "")
        self.assertFalse(kb._available)
        self.assertIn("query failed", kb.unavailable_reason)


class Neo4jSyncTests(unittest.TestCase):
    def test_upsert_style_rebuilds_all_managed_relationships(self):
        module = load_neo4j_kb()
        kb = module.Neo4jKnowledgeBase()
        session = RecordingSession()
        style = {
            "name": "Test",
            "category": "Category",
            "description": "Description",
            "keywords": ["alias", "scene", "tech"],
            "anti_keywords": ["avoid"],
            "pros": ["pro"],
            "cons": ["con"],
            "scenes": ["scene"],
        }

        kb._upsert_style(session, style)

        queries = [query for query, _ in session.queries]
        self.assertTrue(any("SET s.category = $category" in query for query in queries))
        self.assertTrue(any("HAS_PRO|HAS_CON|SUITABLE_FOR|HAS_KEYWORD" in query for query in queries))
        self.assertTrue(any("MERGE (s)-[:HAS_PRO]->(c)" in query for query in queries))
        self.assertTrue(any("MERGE (s)-[:HAS_CON]->(c)" in query for query in queries))
        self.assertTrue(any("MERGE (s)-[:SUITABLE_FOR]->(u)" in query for query in queries))
        self.assertTrue(any("MERGE (s)-[:HAS_KEYWORD]->(k)" in query for query in queries))

    def test_reconcile_deletes_stale_styles_syncs_relations_and_cleans_orphans(self):
        module = load_neo4j_kb()
        session = RecordingSession()
        kb = module.Neo4jKnowledgeBase()
        kb._driver = FakeDriver(session)
        kb._available = True
        styles = [{
            "name": "A",
            "category": "",
            "description": "",
            "keywords": [],
            "anti_keywords": [],
            "pros": [],
            "cons": [],
            "scenes": [],
        }]
        relations = [{"from": "A", "type": "RELATED_TO", "to": "B", "reason": "reason"}]

        kb.reconcile_from_json(styles=styles, relations=relations)

        queries = [query for query, _ in session.queries]
        self.assertTrue(any("WHERE NOT s.name IN $names" in query for query in queries))
        self.assertTrue(any("DELETE r" in query and "COMPLEMENTS|RELATED_TO" in query for query in queries))
        self.assertTrue(any("MERGE (a)-[:RELATED_TO {reason: $reason}]->(b)" in query for query in queries))
        self.assertTrue(any("NOT ()-->(n)" in query for query in queries))

    def test_retry_window_allows_recovery_reconcile_without_restart(self):
        module = load_neo4j_kb()
        session = RecordingSession()
        kb = module.Neo4jKnowledgeBase()
        kb._driver = FakeDriver(session)
        kb._available = False
        kb._last_failure_at = 100
        kb.retry_interval_seconds = 30
        calls = []
        kb.reconcile_from_json = lambda: calls.append("reconciled") or True

        with patch.object(module.time, "monotonic", return_value=131):
            self.assertTrue(kb._ensure_synced())

        self.assertEqual(calls, ["reconciled"])

    def test_summary_query_reconciles_before_reading_graph(self):
        module = load_neo4j_kb()
        session = RecordingSession()
        kb = module.Neo4jKnowledgeBase()
        kb._driver = FakeDriver(session)
        kb._available = True
        calls = []
        kb.reconcile_from_json = lambda: calls.append("reconciled") or True

        self.assertEqual(kb.get_all_styles_summary(), [])

        self.assertEqual(calls, ["reconciled"])


if __name__ == "__main__":
    unittest.main()
