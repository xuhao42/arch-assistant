#!/bin/bash
# 本脚本作为 arch-assistant 的批量接口回归测试入口：
# 读取预置场景，逐条调用架构分析 API，并把执行进度和最终命中率写入本地 JSON 文件。
# 这里保持为轻量 shell 脚本，便于在不启动完整测试框架的情况下快速验证推荐链路。
API="http://localhost:8001/api/v1/analyze"
DATA="/mnt/e/workspace/UserRegister/arch-assistant/data/test_scenarios.json"
PROGRESS="/mnt/e/workspace/UserRegister/arch-assistant/test_progress.json"
RESULT="/mnt/e/workspace/UserRegister/arch-assistant/test_results.json"

# 总数从场景文件动态读取，避免新增或删除测试样例后还需要同步维护脚本常量。
TOTAL=$(python3 -c "import json; print(len(json.load(open('$DATA'))))")
echo "{\"current\":0,\"total\":$TOTAL,\"results\":[]}" > "$PROGRESS"

PASSED=0; FAILED=0; RESULTS="["

for i in $(seq 0 $((TOTAL-1))); do
    # 每个场景只抽取测试判定需要的字段，避免后续 curl 请求和命中判断依赖完整场景结构。
    SCENARIO=$(python3 -c "
import json
s = json.load(open('$DATA'))[$i]
print(json.dumps({
    'id': s['id'],
    'desc': s['description'],
    'expected': s.get('primary_recommendation','')
}))
")
    ID=$(echo "$SCENARIO" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
    DESC=$(echo "$SCENARIO" | python3 -c "import sys,json;print(json.load(sys.stdin)['desc'])")
    EXP=$(echo "$SCENARIO" | python3 -c "import sys,json;print(json.load(sys.stdin)['expected'])")

    echo -n "[$ID/$TOTAL] ${DESC:0:60}... "

    # 单个场景可能触发 RAG、规则引擎和模型编排，超时时间留得较长以覆盖端到端链路耗时。
    T0=$(date +%s%3N)
    RESP=$(curl -s --max-time 180 -X POST "$API" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\":$(echo "$DESC" | python3 -c "import sys,json;print(json.dumps(sys.stdin.read()))"), \"session_id\":\"batch_$ID\"}" 2>&1)
    T1=$(date +%s%3N)
    ELAPSED=$((T1 - T0))

    # 只取 Top 3 候选用于验收，是因为课程场景更关注推荐结果是否进入可解释候选集，
    # 而不是强制要求某个架构始终排在第一位。
    CANDIDATES=$(echo "$RESP" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    cands=d.get('candidates') or []
    names=[c['name'] for c in cands[:3]]
    print(json.dumps(names))
except:
    print('[]')
" 2>/dev/null)

    TOP=$(echo "$CANDIDATES" | python3 -c "import sys,json;a=json.load(sys.stdin);print(a[0] if a else 'N/A')" 2>/dev/null)
    # 命中判断使用包含匹配，兼容候选名称中带版本、别名或补充说明的情况。
    HIT=$(echo "$CANDIDATES" | python3 -c "
import sys,json,sys
a=json.load(sys.stdin)
exp='$EXP'
hit=any(exp in n for n in a)
print('true' if hit else 'false')
" 2>/dev/null)

    if [ "$HIT" = "true" ]; then
        echo "✅ $TOP (${ELAPSED}ms)"
        PASSED=$((PASSED+1))
    else
        echo "❌ $TOP | expected: $EXP (${ELAPSED}ms)"
        FAILED=$((FAILED+1))
    fi

    # 结果数组按场景逐步拼接，供进度文件在测试未完成时也能被前端或观察脚本读取。
    if [ $i -gt 0 ]; then RESULTS+=","; fi
    RESULTS+="{\"id\":$ID,\"top\":\"$TOP\",\"hit\":$HIT,\"elapsed\":$ELAPSED}"

    # 每轮结束立即落盘进度，方便长批次测试中途查看当前通过率和定位失败样例。
    echo "{\"current\":$((i+1)),\"total\":$TOTAL,\"passed\":$PASSED,\"failed\":$FAILED,\"results\":$RESULTS]}" > "$PROGRESS"
done

RESULTS+="]"

# 最终结果只保留汇总指标，详细逐条结果已经在进度文件中持续更新。
SUMMARY="{\"passed\":$PASSED,\"failed\":$FAILED,\"total\":$TOTAL,\"accuracy\":\"$PASSED/$TOTAL\"}"
echo "$SUMMARY" > "$RESULT"
echo ""
echo "======================="
echo "📊 DONE: $PASSED/$TOTAL passed, $FAILED failed"
