#!/bin/bash
# Cross-platform testing script

echo "🧪 Testing filesystem path handling (cross-platform)"

# Run tests locally
echo ""
echo "=== Local Tests (Windows) ==="
pytest tests/test_cross_platform_paths.py -v

# Run tests in Docker (Linux)
echo ""
echo "=== Docker Tests (Linux) ==="
docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c "
  pip install -q pytest pathlib &&
  pytest tests/test_cross_platform_paths.py -v
"

echo ""
echo "✅ Both platforms tested!"
