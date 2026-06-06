#!/bin/bash
# arch-assistant 批量验收脚本：逐条调用编排引擎，检查推荐是否命中预期架构。
API="http://localhost:8001/api/v1/analyze"
DATA="/mnt/e/workspace/UserRegister/arch-assistant/data/test_scenarios.json"
PROGRESS="/mnt/e/workspace/UserRegister/arch-assistant/test_progress.json"
RESULT="/mnt/e/workspace/UserRegister/arch-assistant/test_results.json"

TOTAL=$(python3 -c "import json; print(len(json.load(open('$DATA'))))")
# 初始化进度文件，供前端或人工实时查看批量测试进度。
echo "{\"current\":0,\"total\":$TOTAL,\"results\":[]}" > "$PROGRESS"

PASSED=0; FAILED=0; RESULTS="["

for i in $(seq 0 $((TOTAL-1))); do
    # 读取当前测试场景，并抽取 id、需求描述和预期首选架构。
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

    T0=$(date +%s%3N)
    # 调用编排引擎普通分析接口，session_id 使用 batch_ 前缀避免写入学习案例库。
    RESP=$(curl -s --max-time 180 -X POST "$API" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\":$(echo "$DESC" | python3 -c "import sys,json;print(json.dumps(sys.stdin.read()))"), \"session_id\":\"batch_$ID\"}" 2>&1)
    T1=$(date +%s%3N)
    ELAPSED=$((T1 - T0))

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
    # 命中判断采用包含关系，兼容知识库中带括号全称的架构名称。
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

    # 追加本条结果到内存 JSON 字符串，最终写入测试结果文件。
    if [ $i -gt 0 ]; then RESULTS+=","; fi
    RESULTS+="{\"id\":$ID,\"top\":\"$TOP\",\"hit\":$HIT,\"elapsed\":$ELAPSED}"

    # 每条场景结束后刷新进度，便于长批次运行时观察。
    echo "{\"current\":$((i+1)),\"total\":$TOTAL,\"passed\":$PASSED,\"failed\":$FAILED,\"results\":$RESULTS]}" > "$PROGRESS"
done

RESULTS+="]"

# 写入最终汇总，包含通过数、失败数和准确率。
SUMMARY="{\"passed\":$PASSED,\"failed\":$FAILED,\"total\":$TOTAL,\"accuracy\":\"$PASSED/$TOTAL\"}"
echo "$SUMMARY" > "$RESULT"
echo ""
echo "======================="
echo "📊 DONE: $PASSED/$TOTAL passed, $FAILED failed"
