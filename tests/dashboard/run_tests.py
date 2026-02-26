#!/usr/bin/env python3
"""
Dashboard Test Runner (Python version)

Runs all dashboard tests and generates detailed report.
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime


def run_command(cmd, description):
    """Run command and return result."""
    print(f"\n{'=' * 60}")
    print(f"{description}")
    print("=" * 60)

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    return result.returncode == 0


def main():
    """Main test runner."""
    print("Dashboard Test Suite")
    print("=" * 60)
    print()

    # Parse arguments
    run_unit = "--unit-only" in sys.argv or "--all" in sys.argv or len(sys.argv) == 1
    run_e2e = "--e2e-only" in sys.argv or "--all" in sys.argv
    run_coverage = "--coverage" in sys.argv

    print("Configuration:")
    print(f"  Unit Tests: {run_unit}")
    print(f"  E2E Tests: {run_e2e}")
    print(f"  Coverage: {run_coverage}")

    results = {
        "timestamp": datetime.now().isoformat(),
        "unit_passed": None,
        "e2e_passed": None,
        "total_passed": 0,
        "total_failed": 0,
    }

    # Run unit tests
    if run_unit:
        coverage_args = (
            "--cov=nanobot.dashboard --cov-report=html --cov-report=term" if run_coverage else ""
        )
        cmd = f"pytest tests/dashboard/unit/ -v {coverage_args}"

        unit_passed = run_command(cmd, "Running Unit Tests")
        results["unit_passed"] = unit_passed

        if not unit_passed:
            print("\n❌ Unit tests failed")

    # Run E2E tests
    if run_e2e:
        # Check for API key
        config_path = Path.home() / ".nanobot" / "config.json"
        if not config_path.exists():
            print("\n⚠️  Warning: No config.json found")
            print("E2E tests require LLM API key")
            print()

        coverage_args = (
            "--cov=nanobot.dashboard --cov-report=html --cov-report=term" if run_coverage else ""
        )
        cmd = f"pytest tests/dashboard/e2e/ -v -s -m e2e {coverage_args}"

        e2e_passed = run_command(cmd, "Running E2E Tests (requires LLM API)")
        results["e2e_passed"] = e2e_passed

        if not e2e_passed:
            print("\n❌ E2E tests failed")

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    all_passed = all(
        [results["unit_passed"] if run_unit else True, results["e2e_passed"] if run_e2e else True]
    )

    if all_passed:
        print("✅ All tests passed!")
        print()
        print("Next steps:")
        print("  1. Check coverage: htmlcov/index.html")
        print("  2. Update TEST_RESULTS.md")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        print()
        print("Check output above for details")
        sys.exit(1)


if __name__ == "__main__":
    if "--help" in sys.argv:
        print("Usage: python run_tests.py [options]")
        print()
        print("Options:")
        print("  --unit-only    Run only unit tests (default)")
        print("  --e2e-only     Run only E2E tests")
        print("  --all          Run all tests")
        print("  --coverage     Generate coverage report")
        print("  --help         Show this help")
        sys.exit(0)

    main()
