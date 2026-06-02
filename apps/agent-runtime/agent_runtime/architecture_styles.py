"""Authoritative JSON architecture-style data access and normalization."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()


def _default_data_dir() -> Path:
    parents = Path(__file__).resolve().parents
    return parents[3] / "data" if len(parents) > 3 else Path("/data")


DATA_DIR = Path(os.getenv("ARCHITECTURE_DATA_DIR") or _default_data_dir())
STYLES_PATH = DATA_DIR / "architecture_styles.json"
RELATIONS_PATH = DATA_DIR / "architecture_relations.json"


class DuplicateArchitectureStyleError(ValueError):
    """Raised when an online append would duplicate an architecture style."""


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def load_styles(path: Path = STYLES_PATH) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_relations(path: Path = RELATIONS_PATH) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_style(style: dict[str, Any]) -> dict[str, Any]:
    """Map one authoritative JSON record into the Neo4j projection."""
    aliases = _deduplicate(style.get("aliases", []))
    scenes = _deduplicate(style.get("适合场景", []))
    technologies = _deduplicate(style.get("关键技术", []))
    return {
        "name": style["name"],
        "category": style.get("category", ""),
        "description": style.get("description", ""),
        "keywords": _deduplicate([*aliases, *scenes, *technologies]),
        "anti_keywords": _deduplicate(style.get("不适合场景", [])),
        "pros": _deduplicate(style.get("优点", [])),
        "cons": _deduplicate(style.get("缺点", [])),
        "scenes": scenes,
    }


def load_normalized_styles(path: Path = STYLES_PATH) -> list[dict[str, Any]]:
    return [normalize_style(style) for style in load_styles(path)]


def format_style_summary(style: dict[str, Any]) -> str:
    """Render one normalized style for JSON fallback prompt context."""
    return (
        f"- {style['name']} [{style.get('category', '')}] | "
        f"{style.get('description', '')[:60]}... | "
        f"触发词: {'/'.join(style.get('keywords', []))} | "
        f"排除词: {'/'.join(style.get('anti_keywords', []))}"
    )


def append_style_atomic(
    style: dict[str, Any],
    path: Path = STYLES_PATH,
) -> list[dict[str, Any]]:
    """Append one JSON style using an in-process lock and atomic replacement."""
    path = Path(path)
    with _WRITE_LOCK:
        styles = load_styles(path)
        if any(existing["name"] == style["name"] for existing in styles):
            raise DuplicateArchitectureStyleError(style["name"])
        styles.append(style)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
            ) as file:
                json.dump(styles, file, ensure_ascii=False, indent=2)
                file.write("\n")
                temp_path = Path(file.name)
            os.replace(temp_path, path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
        return styles
