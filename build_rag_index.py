#!/usr/bin/env python3
"""构建课程资料 RAG 的 jieba + TF-IDF 索引产物。

该脚本从 data/rag_chunks/chunks.json 读取已切分的课程资料，
生成 vectorizer.pkl、chunks.pkl 和 tfidf_matrix.npz，供早期 pickle 版
RAG 检索流程使用。运行脚本会改写 data/rag_index 下的索引文件。
"""
import json, pickle, os
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz

CHUNKS_FILE = "/mnt/e/workspace/UserRegister/arch-assistant/data/rag_chunks/chunks.json"
INDEX_DIR = "/mnt/e/workspace/UserRegister/arch-assistant/data/rag_index"
os.makedirs(INDEX_DIR, exist_ok=True)

with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

def jieba_tokenizer(text):
    """供 scikit-learn 调用的中文分词函数。"""
    return list(jieba.cut(text))

texts = [c["text"] for c in chunks]
print(f"Building jieba+TF-IDF index for {len(texts)} chunks...")

vectorizer = TfidfVectorizer(
    tokenizer=jieba_tokenizer,
    max_features=8000,
    ngram_range=(1, 2),
    min_df=1,
)
tfidf_matrix = vectorizer.fit_transform(texts)

# 保存索引产物：向量器、原始切片和稀疏矩阵需要配套使用。
with open(os.path.join(INDEX_DIR, "vectorizer.pkl"), "wb") as f:
    pickle.dump(vectorizer, f)
with open(os.path.join(INDEX_DIR, "chunks.pkl"), "wb") as f:
    pickle.dump(chunks, f)
save_npz(os.path.join(INDEX_DIR, "tfidf_matrix.npz"), tfidf_matrix)

print(f"Index: {tfidf_matrix.shape[1]} features, {tfidf_matrix.shape[0]} docs")

# 构建后做几组人工查询冒烟测试，确认中文关键词能召回相关片段。
from sklearn.metrics.pairwise import cosine_similarity
tests = ["事件驱动架构风格", "管道过滤器数据流", "P2P去中心化对等架构", "MVC模型视图控制器", "软件体系结构评估方法"]
for q in tests:
    q_vec = vectorizer.transform([q])
    scores = cosine_similarity(q_vec, tfidf_matrix).flatten()
    top3 = scores.argsort()[-3:][::-1]
    print(f"\n'{q}':")
    for idx in top3:
        print(f"  [{scores[idx]:.3f}] {chunks[idx]['source']}: {chunks[idx]['text'][:100]}...")
