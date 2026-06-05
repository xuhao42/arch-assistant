"""为架构推荐流程提供基于课程讲义的轻量级 RAG 召回能力。

本模块在首次检索时从本地切片文件构建 TF-IDF 索引，并使用 jieba
对中文课程内容分词。它不依赖预生成 pickle 索引，便于课程演示环境在
数据文件存在时直接启动，但首次请求会承担一次索引构建开销。
"""
import json, os
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "rag_index")
CHUNKS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "rag_chunks", "chunks.json")

# 索引对象延迟初始化，避免服务启动时因课程讲义缺失或构建耗时阻塞所有入口。
# 这些全局对象只保存本地静态讲义索引，不承载用户会话状态。
_vectorizer = None
_tfidf_matrix = None
_chunks = None

def _build_index():
    """从课程讲义切片构建 TF-IDF 检索索引。

    该函数承担 RAG 的本地知识库初始化职责，会读取预切分的讲义文本，
    并把文本转换为后续余弦相似度检索所需的向量矩阵。

    Raises:
        FileNotFoundError: 当课程讲义切片文件不存在时抛出。
        json.JSONDecodeError: 当切片文件不是合法 JSON 时抛出。
    """
    global _vectorizer, _tfidf_matrix, _chunks
    
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        _chunks = json.load(f)
    
    texts = [c["text"] for c in _chunks]
    
    # 中文课程描述需要先分词；同时保留 1-gram 和 2-gram，
    # 让“微服务”“高并发”等短语特征在架构场景检索中有更高辨识度。
    _vectorizer = TfidfVectorizer(
        tokenizer=lambda x: list(jieba.cut(x)),
        max_features=5000,
        ngram_range=(1, 2),
        min_df=1,
    )
    _tfidf_matrix = _vectorizer.fit_transform(texts)

def _ensure_index():
    """确保检索前已有可用索引。

    延迟构建索引可以降低普通模块导入成本，并把索引构建失败暴露在真正
    需要 RAG 的调用链上，便于接口层按业务场景返回降级结果。
    """
    if _vectorizer is None:
        _build_index()

def retrieve(query: str, top_k: int = 5) -> list[str]:
    """根据用户需求召回最相关的课程讲义片段。

    Args:
        query: 用户输入或已整理过的架构需求描述。
        top_k: 最多检查的候选片段数量，返回结果可能因相似度阈值更少。

    Returns:
        按相关性从高到低排序的讲义文本片段，用于后续候选推荐或报告生成。
    """
    _ensure_index()
    q_vec = _vectorizer.transform([query])
    scores = cosine_similarity(q_vec, _tfidf_matrix).flatten()
    top_indices = scores.argsort()[-top_k:][::-1]
    
    results = []
    for idx in top_indices:
        # 低相似度片段更可能是词面偶然重合，过滤后可减少 LLM 引用无关课程内容。
        if scores[idx] > 0.01:
            results.append(_chunks[idx]["text"])
    return results

def retrieve_context(query: str, max_chars: int = 1500, top_k: int = 5) -> str:
    """召回课程资料并格式化为可直接拼入 LLM 提示词的上下文。

    Args:
        query: 用户输入或已整理过的架构需求描述。
        max_chars: 上下文总字符预算，用于控制提示词长度。
        top_k: 最多召回的候选片段数量。

    Returns:
        带有资料来源标题的提示词上下文；无有效召回时返回空字符串，便于
        上层逻辑继续使用规则或模型本身生成结果。
    """
    chunks = retrieve(query, top_k)
    if not chunks:
        return ""
    
    context = "【参考资料（来自课程讲义）】\n"
    total = 0
    for i, chunk in enumerate(chunks):
        # 单片段截断优先保证多个参考来源都能进入提示词，避免长切片挤占全部上下文预算。
        truncated = chunk[:400]
        context += f"\n--- 参考资料 {i+1} ---\n{truncated}\n"
        total += len(truncated)
        # max_chars 是业务侧的软预算，拼接到达上限后停止追加，保留已加入片段的完整标题和内容。
        if total > max_chars:
            break
    return context
