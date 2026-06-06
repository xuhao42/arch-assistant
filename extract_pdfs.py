#!/usr/bin/env python3
"""把软件体系结构课程 PDF 抽取成 RAG 可用的文本切片。

脚本遍历指定资料目录中的 PDF，抽取每页文本，按段落和长度拆分后写入
data/rag_chunks/chunks.json，同时输出 full_text.txt 方便人工检查。
"""
import pymupdf, os, json

PDF_DIR = "/mnt/e/项目/大作业/软件体系结构参考资料"
OUT_DIR = "/mnt/e/workspace/UserRegister/arch-assistant/data/rag_chunks"
os.makedirs(OUT_DIR, exist_ok=True)

pdfs = sorted([f for f in os.listdir(PDF_DIR) if f.endswith('.pdf')])
print(f"Found {len(pdfs)} PDFs")

all_chunks = []

for pdf_file in pdfs:
    path = os.path.join(PDF_DIR, pdf_file)
    doc = pymupdf.open(path)
    print(f"  {pdf_file}: {len(doc)} pages")
    
    full_text = ""
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            full_text += f"\n--- Page {i+1} ---\n{text}"
    
    # 先按较自然的空行边界切片，尽量保留课程段落语义。
    raw_chunks = full_text.split("\n\n\n")
    
    for ci, chunk in enumerate(raw_chunks):
        chunk = chunk.strip()
        if len(chunk) < 50:  # 跳过太短的页眉、页脚或孤立碎片。
            continue
        
        # 过长切片继续按段落拆分，避免单个 chunk 超过提示词可控范围。
        if len(chunk) > 2000:
            # 按单换行段落累积到约 1500 字符后落盘为一个切片。
            paragraphs = [p.strip() for p in chunk.split("\n") if p.strip()]
            current = ""
            for p in paragraphs:
                if len(current) + len(p) > 1500 and current:
                    all_chunks.append({
                        "source": pdf_file,
                        "chunk_id": f"{pdf_file}_{len(all_chunks)}",
                        "text": current
                    })
                    current = p
                else:
                    current = (current + "\n" + p).strip()
            if current:
                all_chunks.append({
                    "source": pdf_file,
                    "chunk_id": f"{pdf_file}_{len(all_chunks)}",
                    "text": current
                })
        else:
            all_chunks.append({
                "source": pdf_file,
                "chunk_id": f"{pdf_file}_{len(all_chunks)}",
                "text": chunk
            })

# 保存结构化切片，供索引构建脚本读取。
with open(os.path.join(OUT_DIR, "chunks.json"), "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False, indent=2)

# 额外保存合并文本，便于人工检查抽取质量和资料来源。
with open(os.path.join(OUT_DIR, "full_text.txt"), "w", encoding="utf-8") as f:
    for c in all_chunks:
        f.write(f"\n\n=== {c['source']} ===\n{c['text']}")

total_chars = sum(len(c['text']) for c in all_chunks)
print(f"\nDone: {len(all_chunks)} chunks, {total_chars} chars total")
print(f"Saved to: {OUT_DIR}")
