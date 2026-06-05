#!/bin/bash
# ============================================================
# dependency_regression_test.sh — Before/After regression test
#
# Verifies that dependency updates don't break existing functionality.
# Run BEFORE and AFTER patching, then diff the results.
#
# Usage:
#   bash tests/dependency_regression_test.sh before        # Save baseline
#   bash tests/dependency_regression_test.sh after <tag>   # Compare with baseline
#
# Output:
#   /tmp/dep-test-before.json   (baseline)
#   /tmp/dep-test-after.json    (post-patch)
#   /tmp/dep-test-diff.txt      (comparison)
# ============================================================

set -uo pipefail
export AWS_PAGER=""

MODE="${1:-run}"
TAG="${2:-}"
RESULT_FILE="/tmp/dep-test-${MODE}.json"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}PASS${NC} $1"; }
fail() { echo -e "${RED}FAIL${NC} $1"; }
warn() { echo -e "${YELLOW}WARN${NC} $1"; }

RESULTS="{}"
add_result() {
    local key="$1" status="$2" detail="$3"
    RESULTS=$(echo "$RESULTS" | python3 -c "
import json, sys
r = json.load(sys.stdin)
r['$key'] = {'status': '$status', 'detail': '''$detail'''}
json.dump(r, sys.stdout, ensure_ascii=False)
")
}

echo "============================================"
echo "Dependency Regression Test (${MODE}${TAG:+ / $TAG})"
echo "Date: $(date)"
echo "============================================"

# ---------- Test 1: self-hosted uv sync ----------
echo ""; echo "=== Test 1: self-hosted uv sync ==="
cd "${PROJECT_ROOT}/self-hosted"
if uv sync 2>&1 | tail -2; then
    add_result "selfhosted_sync" "PASS" "uv sync ok"; pass "self-hosted uv sync"
else
    add_result "selfhosted_sync" "FAIL" "uv sync failed"; fail "self-hosted uv sync"
fi

# ---------- Test 2: self-hosted imports ----------
echo ""; echo "=== Test 2: self-hosted imports ==="
cd "${PROJECT_ROOT}/self-hosted"
IMPORTS=(boto3 strands dotenv matplotlib pandas numpy seaborn plotly docx weasyprint reportlab sklearn PIL yaml lxml)
FAILED=""
for pkg in "${IMPORTS[@]}"; do
    uv run python -c "import ${pkg}" 2>/dev/null || FAILED="${FAILED} ${pkg}"
done
if [ -z "$FAILED" ]; then
    add_result "selfhosted_imports" "PASS" "all ${#IMPORTS[@]} ok"; pass "self-hosted imports (${#IMPORTS[@]})"
else
    add_result "selfhosted_imports" "FAIL" "failed:${FAILED}"; fail "self-hosted imports:${FAILED}"
fi

# ---------- Test 3: self-hosted versions snapshot ----------
echo ""; echo "=== Test 3: self-hosted versions ==="
cd "${PROJECT_ROOT}/self-hosted"
VERS=$(uv run python -c "
import importlib.metadata as m
pkgs=['boto3','strands-agents','strands-agents-tools','cryptography','tornado','orjson','protobuf','pyasn1','urllib3','idna','requests','langchain-core','langsmith','python-multipart','lxml','gitpython','pygments','weasyprint','python-docx']
for p in pkgs:
    try: print(f'{p}=={m.version(p)}')
    except: print(f'{p}==NA')
" 2>/dev/null || echo "FAILED")
add_result "selfhosted_versions" "INFO" "$VERS"
echo "$VERS" | head -8; echo "  ... ($(echo "$VERS" | wc -l) pkgs)"

# ---------- Test 4: managed phase3 uv sync ----------
echo ""; echo "=== Test 4: managed-agentcore phase3 uv sync ==="
cd "${PROJECT_ROOT}/managed-agentcore/production_deployment/scripts/phase3"
if uv sync 2>&1 | tail -2; then
    add_result "managed_sync" "PASS" "uv sync ok"; pass "managed phase3 uv sync"
else
    add_result "managed_sync" "FAIL" "uv sync failed"; fail "managed phase3 uv sync"
fi

# ---------- Test 5: managed phase3 imports ----------
echo ""; echo "=== Test 5: managed phase3 imports ==="
cd "${PROJECT_ROOT}/managed-agentcore/production_deployment/scripts/phase3"
MIMPORTS=(boto3 strands bedrock_agentcore dotenv jwt cryptography langchain_core langsmith)
MFAILED=""
for pkg in "${MIMPORTS[@]}"; do
    uv run python -c "import ${pkg}" 2>/dev/null || MFAILED="${MFAILED} ${pkg}"
done
if [ -z "$MFAILED" ]; then
    add_result "managed_imports" "PASS" "all ${#MIMPORTS[@]} ok"; pass "managed imports (${#MIMPORTS[@]})"
else
    add_result "managed_imports" "FAIL" "failed:${MFAILED}"; fail "managed imports:${MFAILED}"
fi

# ---------- Test 6: managed phase3 versions snapshot ----------
echo ""; echo "=== Test 6: managed phase3 versions ==="
cd "${PROJECT_ROOT}/managed-agentcore/production_deployment/scripts/phase3"
MVERS=$(uv run python -c "
import importlib.metadata as m
pkgs=['boto3','strands-agents','bedrock-agentcore','cryptography','tornado','orjson','urllib3','idna','requests','langchain-core','langsmith','python-multipart','mistune','authlib','fastmcp','pygments','pyjwt']
for p in pkgs:
    try: print(f'{p}=={m.version(p)}')
    except: print(f'{p}==NA')
" 2>/dev/null || echo "FAILED")
add_result "managed_versions" "INFO" "$MVERS"
echo "$MVERS" | head -8; echo "  ... ($(echo "$MVERS" | wc -l) pkgs)"

# ---------- Test 7: self-hosted graph import (entry-point smoke) ----------
echo ""; echo "=== Test 7: self-hosted graph build smoke ==="
cd "${PROJECT_ROOT}/self-hosted"
if uv run python -c "from src.graph.builder import build_graph; build_graph(); print('graph ok')" 2>/dev/null | grep -q "graph ok"; then
    add_result "selfhosted_graph" "PASS" "build_graph() ok"; pass "self-hosted graph build"
else
    add_result "selfhosted_graph" "FAIL" "build_graph() import/exec failed"; fail "self-hosted graph build"
fi

# ---------- Save ----------
echo ""; echo "$RESULTS" > "$RESULT_FILE"
echo "Saved: ${RESULT_FILE}"
PASS_N=$(echo "$RESULTS" | grep -o '"PASS"' | wc -l)
FAIL_N=$(echo "$RESULTS" | grep -o '"FAIL"' | wc -l)
echo ""; echo "Results: ${PASS_N} PASS / ${FAIL_N} FAIL"

# ---------- Compare (after mode) ----------
if [ "$MODE" = "after" ] && [ -f "/tmp/dep-test-before.json" ]; then
    echo ""; echo "=== Comparing with baseline ==="
    python3 -c "
import json
before=json.load(open('/tmp/dep-test-before.json'))
after=json.load(open('/tmp/dep-test-after.json'))
regr=[]
for k in set(before)|set(after):
    if k.endswith('_versions'): continue
    b=before.get(k,{}).get('status','MISSING'); a=after.get(k,{}).get('status','MISSING')
    if b=='PASS' and a!='PASS':
        regr.append(f'  REGRESSION {k}: {b}->{a} | after detail: {after.get(k,{}).get(\"detail\",\"\")[:200]}')
if regr:
    print('REGRESSIONS DETECTED:'); [print(r) for r in regr]
    print(); print('ACTION: rollback offending package(s)')
else:
    print('NO REGRESSIONS. All functional tests match or improved.')
# version diffs
for env in ['selfhosted','managed']:
    bv=before.get(f'{env}_versions',{}).get('detail',''); av=after.get(f'{env}_versions',{}).get('detail','')
    if bv!=av:
        print(); print(f'{env} version changes:')
        bs=set(bv.split(chr(10))); as_=set(av.split(chr(10)))
        for l in sorted(bs-as_):
            if l.strip(): print(f'  - {l}')
        for l in sorted(as_-bs):
            if l.strip(): print(f'  + {l}')
" | tee /tmp/dep-test-diff.txt
fi
