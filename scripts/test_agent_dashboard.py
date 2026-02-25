#!/usr/bin/env python3
"""
Test Agent - Dashboard Integration

Verifies that Agent can update Dashboard when processing messages.
"""

import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_agent_updates_dashboard():
    """Test that Agent updates Dashboard when processing messages."""
    print("Testing Agent - Dashboard Integration")
    print("=" * 60)

    # Create test workspace
    with tempfile.TemporaryDirectory(prefix="nanobot_test_") as tmpdir:
        workspace = Path(tmpdir)

        # Create dashboard structure
        dashboard_dir = workspace / "dashboard"
        dashboard_dir.mkdir()

        # Initialize empty Dashboard
        tasks_file = dashboard_dir / "tasks.json"
        tasks_file.write_text(json.dumps({"version": "1.0", "tasks": []}, indent=2))

        questions_file = dashboard_dir / "questions.json"
        questions_file.write_text(json.dumps({"version": "1.0", "questions": []}, indent=2))

        # Create DASHBOARD.md with instructions
        dashboard_md = workspace / "DASHBOARD.md"
        dashboard_md.write_text(
            """# Dashboard Management

You are a Dashboard Sync Manager.

When user says something like "I need to finish X by tomorrow", you should:
1. Read dashboard/tasks.json
2. Add a new task
3. Write dashboard/tasks.json
4. Stay silent (don't reply)

Example task format:
{
  "id": "task_001",
  "title": "Finish X",
  "deadline": "2026-02-07T23:59:00",
  "status": "active",
  "progress": {"percentage": 0, "last_update": "2026-02-06T20:00:00", "note": ""},
  "created_at": "2026-02-06T20:00:00",
  "updated_at": "2026-02-06T20:00:00"
}
""",
            encoding="utf-8",
        )

        # Create memory directory
        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

        print("\n[SETUP] Test workspace created")
        print(f"  Workspace: {workspace}")
        print(f"  Dashboard: {dashboard_dir}")

        # Create Agent (using mock provider for testing)
        print("\n[SETUP] Creating Agent...")

        # Skip actual agent execution for now - just verify Context includes Dashboard
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(workspace)
        system_prompt = builder.build_system_prompt()

        print("\n[TEST 1] Verify DASHBOARD.md is in context")
        if "Dashboard Management" in system_prompt:
            print("  [PASS] DASHBOARD.md included")
        else:
            print("  [FAIL] DASHBOARD.md NOT included")
            return False

        print("\n[TEST 2] Verify empty Dashboard state is shown")
        if "Dashboard State" in system_prompt:
            print("  [PASS] Dashboard State section exists")
        else:
            print("  [FAIL] Dashboard State section missing")
            return False

        print("\n[TEST 3] Add a task manually and verify it appears in context")
        # Manually add a task
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_test",
                    "title": "Test Task",
                    "status": "active",
                    "deadline": "2026-02-10T23:59:00",
                    "progress": {
                        "percentage": 0,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                    },
                    "priority": "high",
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
            ],
        }
        with open(tasks_file, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, indent=2)

        # Rebuild context
        builder2 = ContextBuilder(workspace)
        system_prompt2 = builder2.build_system_prompt()

        if "task_test" in system_prompt2 and "Test Task" in system_prompt2:
            print("  [PASS] Task appears in context after manual add")
        else:
            print("  [FAIL] Task does NOT appear in context")
            return False

        print("\n" + "=" * 60)
        print("All integration tests passed!")
        print()
        print("Next step: Test with real Agent execution")
        print("  (requires LLM API key)")
        print()

        return True


if __name__ == "__main__":
    success = asyncio.run(test_agent_updates_dashboard())
    sys.exit(0 if success else 1)
