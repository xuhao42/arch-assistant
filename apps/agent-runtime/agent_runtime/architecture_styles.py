"""架构风格权威 JSON 数据的读取、归一化与安全追加工具。

本模块是 Agent Runtime 和 Neo4j 同步逻辑共同依赖的数据入口。
它把课程知识库中的中文字段整理成统一结构，保证规则引擎、提示词
上下文和图数据库投影都使用同一份源数据。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()


def _default_data_dir() -> Path:
    """推导默认 data 目录，容器浅层路径下则回退到 /data。"""
    parents = Path(__file__).resolve().parents
    return parents[3] / "data" if len(parents) > 3 else Path("/data")


DATA_DIR = Path(os.getenv("ARCHITECTURE_DATA_DIR") or _default_data_dir())
STYLES_PATH = DATA_DIR / "architecture_styles.json"
RELATIONS_PATH = DATA_DIR / "architecture_relations.json"


class DuplicateArchitectureStyleError(ValueError):
    """在线新增架构风格时，发现同名条目后抛出的业务异常。"""


def _deduplicate(values: list[str]) -> list[str]:
    """按原始顺序去掉空值和重复值，避免关键词权重被重复放大。"""
    return list(dict.fromkeys(value for value in values if value))


def load_styles(path: Path = STYLES_PATH) -> list[dict[str, Any]]:
    """读取完整架构风格 JSON，是知识库的权威数据来源。"""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_relations(path: Path = RELATIONS_PATH) -> list[dict[str, str]]:
    """读取架构之间的互补/相关关系，用于构建 Neo4j 边。"""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_style(style: dict[str, Any]) -> dict[str, Any]:
    """把一条中文 JSON 记录映射为规则引擎和 Neo4j 共用的扁平结构。"""
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
    """批量读取并归一化所有架构风格，供图谱对账和提示词摘要使用。"""
    return [normalize_style(style) for style in load_styles(path)]


def format_style_summary(style: dict[str, Any]) -> str:
    """把归一化后的架构风格渲染成 JSON fallback 提示词上下文。"""
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
    """以进程内锁和原子替换方式追加一条架构风格。

    该函数用于在线知识进化接口：先检查同名冲突，再写入临时文件，
    最后用 os.replace 替换正式文件，避免并发写入留下半截 JSON。
    """
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
