"""课程资料 RAG 检索模块。

这里使用 jieba 分词 + TF-IDF 做轻量文本召回，第一次查询时从
data/rag_chunks/chunks.json 构建内存索引，不依赖 pickle 产物。
Agent 在生成报告前可把召回片段拼进提示词，补充课程讲义背景。
"""
import json, os
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "rag_index")
CHUNKS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "rag_chunks", "chunks.json")

# 延迟加载的全局索引对象：服务启动时不立刻占用内存，首次检索时再初始化。
_vectorizer = None
_tfidf_matrix = None
_chunks = None

def _build_index():
    """从课程资料切片构建 TF-IDF 索引。"""
    global _vectorizer, _tfidf_matrix, _chunks
    
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        _chunks = json.load(f)
    
    texts = [c["text"] for c in _chunks]
    
    _vectorizer = TfidfVectorizer(
        tokenizer=lambda x: list(jieba.cut(x)),
        max_features=5000,
        ngram_range=(1, 2),
        min_df=1,
    )
    _tfidf_matrix = _vectorizer.fit_transform(texts)

def _ensure_index():
    """确保索引已经构建，作为所有公开检索函数的轻量前置检查。"""
    if _vectorizer is None:
        _build_index()

def retrieve(query: str, top_k: int = 5) -> list[str]:
    """按查询文本召回最相关的课程资料片段。

    输入是用户需求或中间分析文本，输出是按余弦相似度排序后的文本切片。
    低于阈值的片段会被丢弃，避免无关资料污染 LLM 上下文。
    """
    _ensure_index()
    q_vec = _vectorizer.transform([query])
    scores = cosine_similarity(q_vec, _tfidf_matrix).flatten()
    top_indices = scores.argsort()[-top_k:][::-1]
    
    results = []
    for idx in top_indices:
        if scores[idx] > 0.01:
            results.append(_chunks[idx]["text"])
    return results

def retrieve_context(query: str, max_chars: int = 1500, top_k: int = 5) -> str:
    """召回资料并格式化成可直接拼接到 LLM 提示词中的中文上下文。"""
    chunks = retrieve(query, top_k)
    if not chunks:
        return ""
    
    context = "【参考资料（来自课程讲义）】\n"
    total = 0
    for i, chunk in enumerate(chunks):
        truncated = chunk[:400]
        context += f"\n--- 参考资料 {i+1} ---\n{truncated}\n"
        total += len(truncated)
        if total > max_chars:
            break
    return context
