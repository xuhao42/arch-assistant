import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "apps"
    / "agent-runtime"
    / "agent_runtime"
    / "architecture_styles.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("test_architecture_styles_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ArchitectureStyleTests(unittest.TestCase):
    def test_repository_json_contains_21_parseable_styles(self):
        module = load_module()
        styles = module.load_styles(ROOT / "data" / "architecture_styles.json")
        self.assertEqual(len(styles), 21)

    def test_explicit_data_dir_imports_from_shallow_container_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = MODULE_PATH.read_text(encoding="utf-8").replace(
                "Path(__file__).resolve()",
                "Path('C:/architecture_styles.py')",
            )
            with patch.dict(os.environ, {"ARCHITECTURE_DATA_DIR": temp_dir}):
                namespace = {}
                exec(compile(source, "architecture_styles.py", "exec"), namespace)

            self.assertEqual(namespace["DATA_DIR"], Path(temp_dir))

    def test_normalize_style_builds_ordered_deduplicated_keywords(self):
        module = load_module()
        style = {
            "name": "Test",
            "aliases": ["alias", "shared"],
            "适合场景": ["scene", "shared"],
            "关键技术": ["tech", "alias"],
            "不适合场景": ["avoid", "avoid"],
            "优点": ["pro"],
            "缺点": ["con"],
        }

        normalized = module.normalize_style(style)

        self.assertEqual(normalized["keywords"], ["alias", "shared", "scene", "tech"])
        self.assertEqual(normalized["anti_keywords"], ["avoid"])
        self.assertEqual(normalized["pros"], ["pro"])
        self.assertEqual(normalized["cons"], ["con"])
        self.assertEqual(normalized["scenes"], ["scene", "shared"])

    def test_repository_keyword_baseline_matches_json_source(self):
        module = load_module()
        styles = [
            module.normalize_style(style)
            for style in module.load_styles(ROOT / "data" / "architecture_styles.json")
        ]

        self.assertEqual(sum(len(style["keywords"]) for style in styles), 270)
        self.assertEqual(len({kw for style in styles for kw in style["keywords"]}), 267)
        self.assertEqual(sum(len(style["pros"]) for style in styles), 84)
        self.assertEqual(sum(len(style["cons"]) for style in styles), 71)
        self.assertEqual(sum(len(style["scenes"]) for style in styles), 94)

    def test_append_style_atomic_rejects_duplicate_name(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "styles.json"
            path.write_text(json.dumps([{"name": "Existing"}]), encoding="utf-8")

            with self.assertRaises(module.DuplicateArchitectureStyleError):
                module.append_style_atomic({"name": "Existing"}, path)

            self.assertEqual(module.load_styles(path), [{"name": "Existing"}])

    def test_append_style_atomic_persists_new_style(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "styles.json"
            path.write_text("[]", encoding="utf-8")

            styles = module.append_style_atomic({"name": "New"}, path)

            self.assertEqual(styles, [{"name": "New"}])
            self.assertEqual(module.load_styles(path), [{"name": "New"}])

    def test_format_style_summary_uses_normalized_json_fields(self):
        module = load_module()
        line = module.format_style_summary({
            "name": "Test",
            "category": "Category",
            "description": "Description",
            "keywords": ["alias", "scene", "tech"],
            "anti_keywords": ["avoid"],
            "pros": ["pro"],
            "cons": ["con"],
            "scenes": ["scene"],
        })

        self.assertIn("触发词: alias/scene/tech", line)
        self.assertIn("排除词: avoid", line)


if __name__ == "__main__":
    unittest.main()
