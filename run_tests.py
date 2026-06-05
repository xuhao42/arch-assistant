#!/usr/bin/env python3
"""批量运行架构推荐验收场景并输出命中统计。

脚本从测试场景 JSON 中读取用户需求和期望首选架构，逐条调用
orchestration-engine 的同步分析接口，再检查 Top 3 候选中是否命中
期望架构。执行过程中会持续写入进度文件，便于长批次中断后查看当前
通过/失败数量；全部场景结束后写出汇总结果和命中率。
"""
import json, subprocess, time, os

API = "http://localhost:8001/api/v1/analyze"
TEST_FILE = "/mnt/e/workspace/UserRegister/arch-assistant/data/test_scenarios.json"
PROGRESS_FILE = "/mnt/e/workspace/UserRegister/arch-assistant/test_progress.json"
RESULT_FILE = "/mnt/e/workspace/UserRegister/arch-assistant/test_results.json"

with open(TEST_FILE) as f:
    scenarios = json.load(f)

results = []
passed = 0
failed = 0

def save():
    """保存当前批量测试进度。

    进度文件包含已执行数量、总场景数、通过/失败计数和每条场景的简要结果，
    用于测试运行中实时观察，也避免长时间接口调用失败时丢失已完成记录。
    """
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"current": len(results), "total": len(scenarios),
                   "passed": passed, "failed": failed, "results": results}, f, ensure_ascii=False)

# 先写入一次空进度，清理旧批次状态，并让外部观察者知道本轮测试已开始。
save()

for s in scenarios:
    # 每个场景包含自然语言需求和期望主推荐架构；session_id 使用 batch_ 前缀，
    # 后端会据此跳过案例沉淀，避免测试数据污染知识进化案例库。
    sid = s["id"]
    desc = s["description"]
    exp = s.get("primary_recommendation", "")
    
    t0 = time.perf_counter()
    
    # 通过 curl 子进程调用本地编排接口，贴近命令行验收方式；
    # 超时时间略大于后端请求超时，确保卡住的模型或下游服务能被判为失败。
    payload = json.dumps({"prompt": desc, "session_id": f"batch_{sid}"})
    proc = subprocess.run([
        "curl", "-s", "--max-time", "180", "-X", "POST", API,
        "-H", "Content-Type: application/json",
        "-d", payload
    ], capture_output=True, text=True, timeout=200)
    
    elapsed = round((time.perf_counter() - t0) * 1000)
    
    # curl 自身失败通常代表接口不可达或请求超时，直接记录错误并进入下一场景。
    if proc.returncode != 0:
        results.append({"id": sid, "desc": desc[:60], "expected": exp,
                       "top": "ERROR", "hit": False, "elapsed": elapsed, "error": proc.stderr[:100]})
        failed += 1
        save()
        continue
    
    # 接口返回非 JSON 时无法判断候选架构，按失败记录，保留场景和耗时用于排障。
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        results.append({"id": sid, "desc": desc[:60], "expected": exp,
                       "top": "PARSE_ERR", "hit": False, "elapsed": elapsed})
        failed += 1
        save()
        continue
    
    # 命中判断以 Top 3 候选为范围，符合推荐结果展示和验收关注点：
    # 首选、备选、补充方案中任一包含期望架构即视为该场景命中。
    candidates = data.get("candidates") or []
    top_name = candidates[0]["name"] if candidates else "N/A"
    names = [c["name"] for c in candidates[:3]]
    hit = any(exp in n for n in names)
    
    # 宽松匹配：部分架构在后端可能返回英文全称、缩写或中文名，
    # 这里用别名表避免展示名称差异造成误判。
    if not hit:
        alias_map = {
            "CQRS": ["CQRS"],
            "SOA": ["SOA"],
            "MVC": ["MVC", "Model-View-Controller"],
            "P2P": ["P2P", "对等", "Peer"],
            "Serverless": ["Serverless", "无服务器"],
            "Space-Based": ["Space-Based", "空间架构", "SBA"],
        }
        for key, aliases in alias_map.items():
            if key in exp:
                hit = any(any(a.lower() in n.lower() for a in aliases) for n in names)
                break
    
    if hit:
        passed += 1
    else:
        failed += 1
    
    results.append({"id": sid, "desc": desc[:60], "expected": exp,
                   "top": top_name, "candidates": names, "hit": hit, "elapsed": elapsed})
    save()

# 最终结果文件面向验收报告或人工复盘，包含总体准确率和每个场景的候选详情。
summary = {"passed": passed, "failed": failed, "total": len(scenarios),
           "accuracy": f"{passed}/{len(scenarios)} ({100*passed/len(scenarios):.1f}%)"}
with open(RESULT_FILE, "w") as f:
    json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)

print(f"DONE: {summary['accuracy']}")
