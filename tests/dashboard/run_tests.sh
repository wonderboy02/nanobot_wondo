#!/bin/bash
# Dashboard Test Runner
# Runs all dashboard tests and generates report

set -e

echo "======================================"
echo "Dashboard Test Suite"
echo "======================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if in correct directory
if [ ! -d "tests/dashboard" ]; then
    echo -e "${RED}Error: Run this script from project root${NC}"
    exit 1
fi

# Parse arguments
RUN_UNIT=true
RUN_E2E=false
RUN_COVERAGE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --unit-only)
            RUN_UNIT=true
            RUN_E2E=false
            shift
            ;;
        --e2e-only)
            RUN_UNIT=false
            RUN_E2E=true
            shift
            ;;
        --all)
            RUN_UNIT=true
            RUN_E2E=true
            shift
            ;;
        --coverage)
            RUN_COVERAGE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--unit-only|--e2e-only|--all] [--coverage]"
            exit 1
            ;;
    esac
done

# Default: run unit tests only (E2E requires API key)
if [ "$RUN_UNIT" = false ] && [ "$RUN_E2E" = false ]; then
    RUN_UNIT=true
fi

echo "Configuration:"
echo "  Unit Tests: $RUN_UNIT"
echo "  E2E Tests: $RUN_E2E"
echo "  Coverage: $RUN_COVERAGE"
echo ""

# Run tests
PYTEST_ARGS="-v"
if [ "$RUN_COVERAGE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS --cov=nanobot.dashboard --cov-report=html --cov-report=term"
fi

FAILED=0

# Unit tests
if [ "$RUN_UNIT" = true ]; then
    echo -e "${GREEN}Running Unit Tests...${NC}"
    echo "========================================"

    if pytest tests/dashboard/unit/ $PYTEST_ARGS; then
        echo -e "${GREEN}✓ Unit tests passed${NC}"
    else
        echo -e "${RED}✗ Unit tests failed${NC}"
        FAILED=1
    fi
    echo ""
fi

# E2E tests
if [ "$RUN_E2E" = true ]; then
    echo -e "${YELLOW}Running E2E Tests (requires LLM API)...${NC}"
    echo "========================================"

    # Check for API key
    if [ -z "$GEMINI_API_KEY" ] && [ ! -f "$HOME/.nanobot/config.json" ]; then
        echo -e "${RED}Warning: No API key found${NC}"
        echo "Set GEMINI_API_KEY or configure ~/.nanobot/config.json"
        echo ""
    fi

    if pytest tests/dashboard/e2e/ -s -m e2e $PYTEST_ARGS; then
        echo -e "${GREEN}✓ E2E tests passed${NC}"
    else
        echo -e "${RED}✗ E2E tests failed${NC}"
        FAILED=1
    fi
    echo ""
fi

# Summary
echo "======================================"
echo "Test Summary"
echo "======================================"

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Check coverage report: htmlcov/index.html"
    echo "  2. Update TEST_RESULTS.md"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo ""
    echo "Check the output above for details"
    exit 1
fi
