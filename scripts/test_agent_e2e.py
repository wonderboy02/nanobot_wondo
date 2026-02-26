#!/usr/bin/env python3
"""
E2E Test: Agent + Dashboard Integration

Tests the complete flow with real LLM.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Enable DEBUG logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config


async def test_e2e_agent_dashboard():
    """Test Agent with Dashboard - E2E"""
    print("=" * 60)
    print("E2E Test: Agent + Dashboard")
    print("=" * 60)
    print()

    # Load config
    config = load_config()
    workspace = Path.home() / ".nanobot" / "workspace"
    dashboard_path = workspace / "dashboard"

    # Set API keys from config to environment (required by LiteLLM)
    if config.providers.openai.api_key:
        os.environ["OPENAI_API_KEY"] = config.providers.openai.api_key
    if config.providers.gemini.api_key:
        os.environ["GEMINI_API_KEY"] = config.providers.gemini.api_key

    # Initialize Dashboard (clean state)
    print("[SETUP] Initializing Dashboard...")
    (dashboard_path / "tasks.json").write_text(
        json.dumps({"version": "1.0", "tasks": []}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (dashboard_path / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Create Agent
    print("[SETUP] Creating Agent...")
    print(f"[SETUP] Using model: {config.agents.defaults.model}")
    bus = MessageBus()

    # Use LiteLLM provider (supports all models)
    provider = LiteLLMProvider(
        api_key="dummy",  # Will use environment variables
        api_base=None,
    )

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=config.agents.defaults.model,  # Use model from config
        max_iterations=10,
    )

    # Test message
    test_message = "다음 주까지 블로그 글 써야 해"
    print(f"\n[TEST] Sending message: '{test_message}'")
    print()

    try:
        response = await agent_loop.process_direct(test_message, session_key="test:e2e")
        print(f"[RESPONSE] Agent: {response}")
    except Exception as e:
        print(f"[ERROR] Agent failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print()
    print("=" * 60)
    print("Verifying Dashboard Updates")
    print("=" * 60)
    print()

    # Verify Dashboard
    success = True

    # Check tasks.json
    print("[CHECK 1] Tasks...")
    with open(dashboard_path / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])
        if len(tasks) > 0:
            print(f"  [PASS] {len(tasks)} task(s) added")
            for task in tasks:
                print(f"    - {task['id']}: {task.get('title', 'N/A')}")
        else:
            print("  [FAIL] No tasks added")
            success = False

    print()

    # Check questions.json
    print("[CHECK 2] Questions...")
    with open(dashboard_path / "questions.json", encoding="utf-8") as f:
        questions_data = json.load(f)
        questions = questions_data.get("questions", [])
        if len(questions) > 0:
            print(f"  [PASS] {len(questions)} question(s) added")
            for q in questions:
                print(f"    - {q['id']}: {q.get('question', 'N/A')}")
        else:
            print("  [WARN] No questions added")

    print()

    # Check file paths (should be in dashboard/)
    print("[CHECK 3] File locations...")
    root_files = list((workspace).glob("*.json"))
    if root_files:
        print(f"  [FAIL] Files in wrong location (workspace root):")
        for f in root_files:
            print(f"    - {f.name}")
        success = False
    else:
        print("  [PASS] No files in workspace root (correct)")

    print()
    print("=" * 60)
    if success:
        print("[PASS] E2E Test PASSED!")
    else:
        print("[FAIL] E2E Test FAILED!")
    print("=" * 60)

    return success


if __name__ == "__main__":
    success = asyncio.run(test_e2e_agent_dashboard())
    sys.exit(0 if success else 1)
