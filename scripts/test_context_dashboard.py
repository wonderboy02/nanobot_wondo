#!/usr/bin/env python3
"""
Test Context Builder - Dashboard Integration

Verifies that Dashboard state is included in agent context.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.agent.context import ContextBuilder


def test_context_includes_dashboard():
    """Test that ContextBuilder includes Dashboard state."""
    print("Testing Context Builder - Dashboard Integration")
    print("=" * 60)

    # Create test workspace
    with tempfile.TemporaryDirectory(prefix="nanobot_test_") as tmpdir:
        workspace = Path(tmpdir)

        # Create dashboard structure
        dashboard_dir = workspace / "dashboard"
        dashboard_dir.mkdir()

        # Create tasks.json with active task
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_001",
                    "title": "Test Task",
                    "status": "active",
                    "deadline": "2026-02-10T23:59:00",
                    "deadline_text": "다음 주",
                    "progress": {
                        "percentage": 30,
                        "last_update": datetime.now().isoformat(),
                        "note": "진행 중",
                        "blocked": False,
                    },
                    "priority": "high",
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                },
                {
                    "id": "task_002",
                    "title": "Someday Task",
                    "status": "someday",
                    "progress": {
                        "percentage": 0,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "priority": "low",
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                },
            ],
        }

        with open(dashboard_dir / "tasks.json", "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, indent=2)

        # Create questions.json with unanswered question
        questions_data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "언제 시작할 거야?",
                    "context": "Need start time",
                    "priority": "medium",
                    "type": "info_gather",
                    "related_task_id": "task_001",
                    "cooldown_hours": 24,
                    "answered": False,
                    "created_at": datetime.now().isoformat(),
                }
            ],
        }

        with open(dashboard_dir / "questions.json", "w", encoding="utf-8") as f:
            json.dump(questions_data, f, indent=2)

        # Create DASHBOARD.md
        dashboard_md = workspace / "DASHBOARD.md"
        dashboard_md.write_text(
            "# Dashboard Management\n\nYou are a Dashboard Sync Manager.", encoding="utf-8"
        )

        # Build context
        builder = ContextBuilder(workspace)
        system_prompt = builder.build_system_prompt()

        # Verify
        print("\nTests:")
        print()

        # Test 1: DASHBOARD.md is included
        if "Dashboard Management" in system_prompt:
            print("[PASS] DASHBOARD.md included in context")
        else:
            print("[FAIL] DASHBOARD.md NOT included")
            return False

        # Test 2: Active tasks included
        if "task_001" in system_prompt and "Test Task" in system_prompt:
            print("[PASS] Active tasks included in context")
        else:
            print("[FAIL] Active tasks NOT included")
            return False

        # Test 3: Someday tasks NOT included
        if "task_002" not in system_prompt:
            print("[PASS] Someday tasks correctly excluded")
        else:
            print("[FAIL] Someday tasks incorrectly included")
            return False

        # Test 4: Questions included
        if "q_001" in system_prompt and "언제 시작할 거야?" in system_prompt:
            print("[PASS] Unanswered questions included")
        else:
            print("[FAIL] Questions NOT included")
            return False

        # Test 5: Verify structure
        if "# Dashboard State" in system_prompt:
            print("[PASS] Dashboard State section exists")
        else:
            print("[FAIL] Dashboard State section missing")
            return False

        print()
        print("=" * 60)
        print("All tests passed!")
        print()

        # Print excerpt
        print("Context Excerpt (Dashboard State):")
        print("-" * 60)
        lines = system_prompt.split("\n")
        in_dashboard = False
        count = 0
        for line in lines:
            if "# Dashboard State" in line:
                in_dashboard = True
            if in_dashboard:
                print(line)
                count += 1
                if count > 20:  # Limit output
                    print("...")
                    break

        return True


if __name__ == "__main__":
    success = test_context_includes_dashboard()
    sys.exit(0 if success else 1)
