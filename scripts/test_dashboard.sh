#!/bin/bash

# Dashboard Test Script
# Tests the dashboard functionality end-to-end

set -e  # Exit on error

echo "🧪 Dashboard Test Suite"
echo "======================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
pass_test() {
    echo -e "${GREEN}✓${NC} $1"
    ((TESTS_PASSED++))
}

fail_test() {
    echo -e "${RED}✗${NC} $1"
    ((TESTS_FAILED++))
}

info() {
    echo -e "${YELLOW}→${NC} $1"
}

# Check if nanobot is installed
if ! command -v nanobot &> /dev/null; then
    echo "❌ nanobot not found. Please install: pip install -e ."
    exit 1
fi

# Create test workspace
TEST_WORKSPACE="/tmp/nanobot_test_$$"
export NANOBOT_WORKSPACE="$TEST_WORKSPACE"

info "Creating test workspace: $TEST_WORKSPACE"
mkdir -p "$TEST_WORKSPACE"

# Initialize
info "Running nanobot onboard..."
nanobot onboard > /dev/null 2>&1 || fail_test "Onboard failed"

# Test 1: Dashboard files exist
echo ""
echo "Test 1: Dashboard Structure"
echo "----------------------------"

if [ -d "$TEST_WORKSPACE/dashboard" ]; then
    pass_test "dashboard/ directory exists"
else
    fail_test "dashboard/ directory missing"
fi

if [ -f "$TEST_WORKSPACE/dashboard/tasks.json" ]; then
    pass_test "tasks.json exists"
else
    fail_test "tasks.json missing"
fi

if [ -f "$TEST_WORKSPACE/dashboard/questions.json" ]; then
    pass_test "questions.json exists"
else
    fail_test "questions.json missing"
fi

if [ -d "$TEST_WORKSPACE/dashboard/knowledge" ]; then
    pass_test "knowledge/ directory exists"
else
    fail_test "knowledge/ directory missing"
fi

# Test 2: Load example data
echo ""
echo "Test 2: Load Example Data"
echo "-------------------------"

EXAMPLE_FILE="tests/fixtures/example_dashboard.json"
if [ -f "$EXAMPLE_FILE" ]; then
    info "Loading example data..."

    # Parse and split example data
    python3 << 'EOF'
import json
import os
from pathlib import Path

workspace = Path(os.environ['NANOBOT_WORKSPACE'])
dashboard_path = workspace / "dashboard"

with open("tests/fixtures/example_dashboard.json") as f:
    example = json.load(f)

# Save tasks
with open(dashboard_path / "tasks.json", "w") as f:
    json.dump({"version": "1.0", "tasks": example["tasks"]}, f, indent=2)

# Save questions
with open(dashboard_path / "questions.json", "w") as f:
    json.dump({"version": "1.0", "questions": example["questions"]}, f, indent=2)

# Save knowledge
knowledge_path = dashboard_path / "knowledge"
with open(knowledge_path / "history.json", "w") as f:
    json.dump(example["knowledge"]["history"], f, indent=2)

with open(knowledge_path / "insights.json", "w") as f:
    json.dump({"version": "1.0", "insights": example["knowledge"]["insights"]}, f, indent=2)

with open(knowledge_path / "people.json", "w") as f:
    json.dump({"version": "1.0", "people": example["knowledge"]["people"]}, f, indent=2)

print("✓ Example data loaded")
EOF

    pass_test "Example data loaded"
else
    fail_test "Example data file not found"
fi

# Test 3: CLI commands
echo ""
echo "Test 3: CLI Commands"
echo "--------------------"

if nanobot dashboard show > /dev/null 2>&1; then
    pass_test "dashboard show"
else
    fail_test "dashboard show"
fi

if nanobot dashboard tasks > /dev/null 2>&1; then
    pass_test "dashboard tasks"
else
    fail_test "dashboard tasks"
fi

if nanobot dashboard questions > /dev/null 2>&1; then
    pass_test "dashboard questions"
else
    fail_test "dashboard questions"
fi

if nanobot dashboard history > /dev/null 2>&1; then
    pass_test "dashboard history"
else
    fail_test "dashboard history"
fi

# Test 4: Worker execution
echo ""
echo "Test 4: Worker Agent"
echo "--------------------"

info "Running worker..."
if nanobot dashboard worker > /dev/null 2>&1; then
    pass_test "Worker executed successfully"
else
    fail_test "Worker execution failed"
fi

# Test 5: Data validation
echo ""
echo "Test 5: Schema Validation"
echo "-------------------------"

python3 << 'EOF'
import json
import os
from pathlib import Path

workspace = Path(os.environ['NANOBOT_WORKSPACE'])
dashboard_path = workspace / "dashboard"

try:
    from nanobot.dashboard.schema import (
        validate_tasks_file,
        validate_questions_file,
        validate_history_file,
        validate_insights_file,
        validate_people_file
    )

    # Validate tasks
    with open(dashboard_path / "tasks.json") as f:
        validate_tasks_file(json.load(f))
    print("✓ tasks.json valid")

    # Validate questions
    with open(dashboard_path / "questions.json") as f:
        validate_questions_file(json.load(f))
    print("✓ questions.json valid")

    # Validate history
    with open(dashboard_path / "knowledge" / "history.json") as f:
        validate_history_file(json.load(f))
    print("✓ history.json valid")

    # Validate insights
    with open(dashboard_path / "knowledge" / "insights.json") as f:
        validate_insights_file(json.load(f))
    print("✓ insights.json valid")

    # Validate people
    with open(dashboard_path / "knowledge" / "people.json") as f:
        validate_people_file(json.load(f))
    print("✓ people.json valid")

except Exception as e:
    print(f"✗ Validation failed: {e}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    pass_test "All schemas valid"
else
    fail_test "Schema validation failed"
fi

# Test 6: Question answering
echo ""
echo "Test 6: Question Answering"
echo "--------------------------"

# Get first question ID
QUESTION_ID=$(python3 << 'EOF'
import json
import os
from pathlib import Path

workspace = Path(os.environ['NANOBOT_WORKSPACE'])
with open(workspace / "dashboard" / "questions.json") as f:
    data = json.load(f)
    if data['questions']:
        print(data['questions'][0]['id'])
EOF
)

if [ -n "$QUESTION_ID" ]; then
    info "Answering question: $QUESTION_ID"
    if nanobot dashboard answer "$QUESTION_ID" "Test answer" > /dev/null 2>&1; then
        pass_test "Question answered"
    else
        fail_test "Question answering failed"
    fi
else
    info "No questions to answer (skipped)"
fi

# Cleanup
echo ""
echo "Cleanup"
echo "-------"
info "Removing test workspace..."
rm -rf "$TEST_WORKSPACE"
pass_test "Cleanup complete"

# Summary
echo ""
echo "======================="
echo "Test Summary"
echo "======================="
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed! ✨${NC}"
    exit 0
fi
