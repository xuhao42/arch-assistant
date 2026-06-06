#!/usr/bin/env python3
"""重建课程资料 RAG 的无 pickle TF-IDF 索引。

该脚本把词表、idf、文本切片和稀疏矩阵分别保存为 JSON/NPZ，
避免 lambda tokenizer 无法可靠 pickle 的问题。运行后会覆盖
data/rag_index 下的 vocab.json、idf.json、chunks.json 和 tfidf_matrix.npz。
"""
import json, os, pickle
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz, load_npz

CHUNKS_FILE = "/mnt/e/workspace/UserRegister/arch-assistant/data/rag_chunks/chunks.json"
INDEX_DIR = "/mnt/e/workspace/UserRegister/arch-assistant/data/rag_index"
os.makedirs(INDEX_DIR, exist_ok=True)

with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

def tokenize(text):
    """保留的中文分词辅助函数，便于测试或交互式复用。"""
    return list(jieba.cut(text))

texts = [c["text"] for c in chunks]
print(f"Building index for {len(texts)} chunks...")

# 构建向量器：运行期直接使用 jieba lambda，不再尝试序列化整个对象。
vectorizer = TfidfVectorizer(
    tokenizer=lambda x: list(jieba.cut(x)),
    max_features=8000,
    ngram_range=(1, 2),
    min_df=1,
)
tfidf_matrix = vectorizer.fit_transform(texts)

# 保存词表和 idf，而不是保存含 lambda 的 vectorizer 对象。
vocab = {k: int(v) for k, v in dict(vectorizer.vocabulary_).items()}
idf = [float(x) for x in vectorizer.idf_.tolist()]

with open(os.path.join(INDEX_DIR, "vocab.json"), "w") as f:
    json.dump(vocab, f, ensure_ascii=False)
with open(os.path.join(INDEX_DIR, "idf.json"), "w") as f:
    json.dump(idf, f)
with open(os.path.join(INDEX_DIR, "chunks.json"), "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False)
save_npz(os.path.join(INDEX_DIR, "tfidf_matrix.npz"), tfidf_matrix)

print(f"Done: {tfidf_matrix.shape[1]} features, {tfidf_matrix.shape[0]} docs")

# 快速查询测试：确认重建后的索引对典型架构关键词有响应。
q = "定时报表 Serverless 每天凌晨 函数计算"
q_vec = vectorizer.transform([q])
from sklearn.metrics.pairwise import cosine_similarity
scores = cosine_similarity(q_vec, tfidf_matrix).flatten()
top3 = scores.argsort()[-3:][::-1]
for idx in top3:
    print(f"  [{scores[idx]:.3f}] {chunks[idx]['source']}: {chunks[idx]['text'][:80]}...")

print("\nTest from reload:")
# 重建测试：用保存的词表/idf 重新构造向量器，验证加载路径可用。
del vectorizer
v2 = TfidfVectorizer(
    tokenizer=lambda x: list(jieba.cut(x)),
    vocabulary=vocab,
    max_features=8000,
)
v2.idf_ = idf
m2 = load_npz(os.path.join(INDEX_DIR, "tfidf_matrix.npz"))
q2 = v2.transform([q])
s2 = cosine_similarity(q2, m2).flatten()
t3 = s2.argsort()[-3:][::-1]
for idx in t3:
    print(f"  [{s2[idx]:.3f}] {chunks[idx]['source']}")
