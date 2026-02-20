"""CLI commands for nanobot."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path
    
    config_path = get_config_path()
    
    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()
    
    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }
    
    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")
    
    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    # Create dashboard directory and structure
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir(exist_ok=True)

    # Initialize dashboard JSON files
    import json

    dashboard_files = {
        "tasks.json": {"version": "1.0", "tasks": []},
        "questions.json": {"version": "1.0", "questions": []},
        "notifications.json": {"version": "1.0", "notifications": []},
    }

    for filename, data in dashboard_files.items():
        file_path = dashboard_dir / filename
        if not file_path.exists():
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    # Create knowledge subdirectory
    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)

    knowledge_files = {
        "history.json": {"version": "1.0", "completed_tasks": [], "projects": []},
        "insights.json": {"version": "1.0", "insights": []},
        "people.json": {"version": "1.0", "people": []},
    }

    for filename, data in knowledge_files.items():
        file_path = knowledge_dir / filename
        if not file_path.exists():
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    console.print("  [dim]Created dashboard/ structure[/dim]")

    # Copy DASHBOARD.md template
    dashboard_md = workspace / "DASHBOARD.md"
    if not dashboard_md.exists():
        template_path = Path(__file__).parent.parent.parent / "workspace" / "DASHBOARD.md"
        if template_path.exists():
            import shutil
            shutil.copy(template_path, dashboard_md)
            console.print("  [dim]Created DASHBOARD.md[/dim]")
        else:
            console.print("[yellow]Warning: DASHBOARD.md template not found[/yellow]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    
    # Create components
    bus = MessageBus()
    
    # Create provider (supports OpenRouter, Anthropic, OpenAI, Bedrock)
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers.openrouter.apiKey")
        raise typer.Exit(1)
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        notion_config=config.notion if config.notion.enabled else None,
    )
    
    # Set cron callback (needs agent)
    # DESIGN: Notification delivery goes through agent.process_direct (LLM turn).
    # This means LLM failure/delay can affect notification delivery.
    # Intentional: allows agent to enrich the notification with context.
    # For raw passthrough, the deliver=True path below sends directly via bus.
    async def _load_notifications_data() -> dict:
        """Load notifications from Notion backend or JSON file."""
        if agent.storage_backend:
            return await asyncio.to_thread(agent.storage_backend.load_notifications)
        notif_path = config.workspace_path / "dashboard" / "notifications.json"
        if notif_path.exists():
            import json
            return json.loads(notif_path.read_text(encoding="utf-8"))
        return {"version": "1.0", "notifications": []}

    async def _save_notifications_data(data: dict) -> bool:
        """Save notifications to Notion backend or JSON file. Returns success."""
        if agent.storage_backend:
            ok, _msg = await asyncio.to_thread(
                agent.storage_backend.save_notifications, data
            )
            return ok
        else:
            notif_path = config.workspace_path / "dashboard" / "notifications.json"
            import json
            notif_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True

    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        # Notification-specific: guard + mark delivered
        is_notification = job.name.startswith("notification_")
        notif_id = job.name.removeprefix("notification_") if is_notification else None

        if is_notification:
            data = await _load_notifications_data()
            notifs = data.get("notifications", [])
            notif = next((n for n in notifs if n.get("id") == notif_id), None)
            if notif is None:
                from loguru import logger
                logger.warning(f"Notification {notif_id} not found, skipping cron delivery")
                return None
            if notif.get("status") in ("cancelled", "delivered"):
                from loguru import logger
                logger.info(f"Skipping {notif['status']} notification cron: {notif_id}")
                return None

        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or ""
            ))

        # Mark notification as delivered (prevents duplicate from orphan crons)
        if is_notification:
            try:
                from datetime import datetime
                data = await _load_notifications_data()
                notifs = data.get("notifications", [])
                for n in notifs:
                    if n.get("id") == notif_id:
                        n["status"] = "delivered"
                        n["delivered_at"] = datetime.now().isoformat()
                        break
                ok = await _save_notifications_data(data)
                if not ok:
                    from loguru import logger
                    logger.warning(
                        f"Failed to persist delivered status for notification {notif_id}"
                    )
            except Exception:
                from loguru import logger
                logger.warning(f"Failed to mark notification {notif_id} as delivered")

        return response
    cron.on_job = on_cron_job
    
    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")

    # Determine worker model (from config or fallback to fast model)
    worker_config = getattr(config.agents, 'worker', None)
    worker_model = worker_config.model if worker_config else "google/gemini-2.0-flash-exp"
    use_llm_worker = worker_config.use_llm if worker_config else True

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True,
        provider=provider,
        model=worker_model,
        cron_service=cron,
        bus=bus,
        use_llm_worker=use_llm_worker,
        storage_backend=agent.storage_backend,
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)

    # Wire storage backend to Telegram channel for /questions, /tasks commands
    telegram_ch = channels.get_channel("telegram")
    if telegram_ch and agent.storage_backend:
        telegram_ch.storage_backend = agent.storage_backend

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    
    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
    
    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    
    config = load_config()
    
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        notion_config=config.notion if config.notion.enabled else None,
    )
    
    if message:
        # Single message mode
        async def run_once():
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")
        
        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue
                    
                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
        
        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )
    
    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess
    
    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)
    
    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)
    
    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge
    
    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Setting up bridge...")
    
    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))
    
    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)
    
    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule
    
    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )
    
    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    async def run():
        return await service.run_job(job_id, force=force)
    
    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Dashboard Commands
# ============================================================================

def _get_dashboard_manager():
    """Helper to initialize DashboardManager."""
    from nanobot.config.loader import load_config
    from nanobot.dashboard.manager import DashboardManager

    config = load_config()
    workspace = config.workspace_path
    dashboard_path = workspace / "dashboard"
    return DashboardManager(dashboard_path)


dashboard_app = typer.Typer(help="Manage your dashboard")
app.add_typer(dashboard_app, name="dashboard")


@dashboard_app.command("show")
def dashboard_show():
    """Show dashboard overview."""
    manager = _get_dashboard_manager()
    dashboard = manager.load()

    console.print(f"\n{__logo__} Dashboard\n")

    # Tasks summary
    tasks = dashboard.get('tasks', [])
    active_tasks = [t for t in tasks if t.get('status') == 'active']
    someday_tasks = [t for t in tasks if t.get('status') == 'someday']

    console.print(f"[bold]Tasks:[/bold] {len(active_tasks)} active, {len(someday_tasks)} someday")

    if active_tasks:
        table = Table(title="Active Tasks", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=10)
        table.add_column("Title", width=40)
        table.add_column("Progress", width=10)
        table.add_column("Deadline", width=20)

        for task in active_tasks[:10]:  # Show first 10
            progress = f"{task.get('progress', {}).get('percentage', 0):.0f}%"
            deadline = task.get('deadline_text', task.get('deadline', '-')[:10] if task.get('deadline') else '-')
            table.add_row(task['id'][:8], task['title'][:40], progress, deadline)

        console.print(table)

        if len(active_tasks) > 10:
            console.print(f"[dim]... and {len(active_tasks) - 10} more[/dim]\n")

    # Questions
    questions = dashboard.get('questions', [])
    pending_questions = [q for q in questions if not q.get('answered', False)]

    console.print(f"\n[bold]Questions:[/bold] {len(pending_questions)} pending")

    if pending_questions:
        for i, q in enumerate(pending_questions[:5], 1):
            priority = q.get('priority', 'low')
            color = {'high': 'red', 'medium': 'yellow', 'low': 'dim'}.get(priority, 'white')
            console.print(f"  [{color}]{i}. [{q['id'][:8]}] {q['question']}[/{color}]")

        if len(pending_questions) > 5:
            console.print(f"[dim]  ... and {len(pending_questions) - 5} more[/dim]")

    console.print()


@dashboard_app.command("tasks")
def dashboard_tasks(
    all: bool = typer.Option(False, "--all", "-a", help="Show all tasks including someday"),
    someday: bool = typer.Option(False, "--someday", "-s", help="Show only someday tasks"),
):
    """List tasks."""
    manager = _get_dashboard_manager()
    dashboard = manager.load()

    tasks = dashboard.get('tasks', [])

    if someday:
        tasks = [t for t in tasks if t.get('status') == 'someday']
        title = "Someday Tasks"
    elif all:
        title = "All Tasks"
    else:
        tasks = [t for t in tasks if t.get('status') == 'active']
        title = "Active Tasks"

    if not tasks:
        console.print("No tasks.")
        return

    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Title", width=35)
    table.add_column("Progress", width=10)
    table.add_column("Priority", width=10)
    table.add_column("Deadline", width=20)
    table.add_column("Status", width=10)

    for task in tasks:
        progress = f"{task.get('progress', {}).get('percentage', 0):.0f}%"
        priority = task.get('priority', '-')
        deadline = task.get('deadline_text', task.get('deadline', '-')[:10] if task.get('deadline') else '-')
        status = task.get('status', 'unknown')

        table.add_row(
            task['id'][:8],
            task['title'][:35],
            progress,
            priority,
            deadline,
            status
        )

    console.print(table)


@dashboard_app.command("questions")
def dashboard_questions():
    """List pending questions."""
    manager = _get_dashboard_manager()
    dashboard = manager.load()

    questions = dashboard.get('questions', [])
    pending = [q for q in questions if not q.get('answered', False)]

    if not pending:
        console.print("No pending questions.")
        return

    console.print(f"\n[bold]Question Queue[/bold] ({len(pending)} pending)\n")

    for q in pending:
        priority = q.get('priority', 'low')
        color = {'high': 'red', 'medium': 'yellow', 'low': 'dim'}.get(priority, 'white')

        console.print(f"[{color}]ID:[/{color}] [{color}]{q['id']}[/{color}]")
        console.print(f"[{color}]Q:[/{color}] {q['question']}")
        console.print(f"[{color}]Priority:[/{color}] {priority}")
        if q.get('related_task_id'):
            console.print(f"[{color}]Related Task:[/{color}] {q['related_task_id']}")
        console.print()


@dashboard_app.command("answer")
def dashboard_answer(
    question_id: str = typer.Argument(..., help="Question ID"),
    answer: str = typer.Argument(..., help="Your answer"),
):
    """Answer a question from the queue."""
    from datetime import datetime

    # Validate inputs
    if not answer or not answer.strip():
        console.print("[red]Error: Answer cannot be empty[/red]")
        raise typer.Exit(1)

    if len(answer) > 10000:
        console.print("[red]Error: Answer too long (max 10000 characters)[/red]")
        raise typer.Exit(1)

    manager = _get_dashboard_manager()
    dashboard = manager.load()

    questions = dashboard.get('questions', [])

    # Find question
    question = None
    for q in questions:
        if q['id'] == question_id or q['id'].startswith(question_id):
            question = q
            break

    if not question:
        console.print(f"[red]Question {question_id} not found[/red]")
        raise typer.Exit(1)

    # Mark as answered
    question['answered'] = True
    question['answer'] = answer
    question['answered_at'] = datetime.now().isoformat()

    # Save
    manager.save(dashboard)

    console.print(f"[green]✓[/green] Question answered: {question['question']}")
    console.print(f"[green]→[/green] {answer}")


@dashboard_app.command("dismiss")
def dashboard_dismiss(
    question_id: str = typer.Argument(..., help="Question ID to dismiss"),
):
    """Dismiss a question (keeps it in queue)."""
    console.print(f"[dim]Question {question_id} dismissed (stays in queue)[/dim]")
    console.print("[dim]Tip: Use 'answer' to actually respond[/dim]")


@dashboard_app.command("history")
def dashboard_history():
    """Show completed tasks history."""
    manager = _get_dashboard_manager()
    dashboard = manager.load()

    history = dashboard.get('knowledge', {}).get('history', {})
    completed = history.get('completed_tasks', [])

    if not completed:
        console.print("No completed tasks yet.")
        return

    table = Table(title="History", show_header=True, header_style="bold green")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Title", width=40)
    table.add_column("Completed", width=20)
    table.add_column("Duration", width=10)

    for task in reversed(completed[-20:]):  # Last 20
        completed_at = task.get('completed_at', '')[:10]
        duration = f"{task.get('duration_days', 0)}d"

        table.add_row(
            task['id'][:8],
            task['title'][:40],
            completed_at,
            duration
        )

    console.print(table)


@dashboard_app.command("worker")
def dashboard_worker():
    """Manually run the worker agent."""
    from nanobot.config.loader import load_config
    from nanobot.dashboard.worker import WorkerAgent

    config = load_config()
    workspace = config.workspace_path
    dashboard_path = workspace / "dashboard"

    console.print(f"{__logo__} Running worker agent...")

    async def run():
        worker = WorkerAgent(dashboard_path)
        await worker.run_cycle()

    asyncio.run(run())

    console.print("[green]✓[/green] Worker cycle complete")


# ============================================================================
# Notion Commands
# ============================================================================

notion_app = typer.Typer(help="Notion integration management")
app.add_typer(notion_app, name="notion")


@notion_app.command("validate")
def notion_validate():
    """Validate Notion database configuration and connectivity."""
    from nanobot.config.loader import load_config

    config = load_config()

    if not config.notion.enabled:
        console.print("[yellow]Notion integration is not enabled.[/yellow]")
        console.print("Set notion.enabled=true in ~/.nanobot/config.json")
        raise typer.Exit(1)

    if not config.notion.token:
        console.print("[red]Notion token not configured.[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} Validating Notion configuration...\n")

    from nanobot.notion.client import NotionClient, NotionAPIError

    client = NotionClient(token=config.notion.token)

    all_ok = True

    try:
        dbs = config.notion.databases
        db_map = {
            "Tasks": dbs.tasks,
            "Questions": dbs.questions,
            "Notifications": dbs.notifications,
            "Insights": dbs.insights,
            "History": dbs.history,
            "People": dbs.people,
        }

        # Check that at least core DBs are configured
        configured_count = sum(1 for db_id in db_map.values() if db_id)
        if configured_count == 0:
            console.print("[red]No database IDs configured at all.[/red]")
            console.print("Add database IDs to notion.databases in ~/.nanobot/config.json")
            raise typer.Exit(1)

        core_missing = []
        if not dbs.tasks:
            core_missing.append("tasks")
        if not dbs.questions:
            core_missing.append("questions")
        if core_missing:
            console.print(
                f"  [red]✗ Core databases missing:[/red] {', '.join(core_missing)}"
            )

        all_ok = not core_missing
        for name, db_id in db_map.items():
            if not db_id:
                console.print(f"  [yellow]⚠ {name}:[/yellow] No database ID configured")
                continue

            try:
                # Try querying to check access (NotionClient is synchronous)
                pages = client.query_database(db_id, filter=None, sorts=None)
                count = len(pages)
                console.print(f"  [green]✓ {name}:[/green] OK ({count} pages)")
            except NotionAPIError as e:
                console.print(f"  [red]✗ {name}:[/red] {e}")
                all_ok = False
            except Exception as e:
                console.print(f"  [red]✗ {name}:[/red] Connection error: {e}")
                all_ok = False
    finally:
        client.close()

    if all_ok:
        console.print("\n[green]✓ All configured databases are accessible![/green]")
    else:
        console.print("\n[red]Some databases failed validation.[/red]")
        console.print("Check your database IDs and integration permissions.")
        raise typer.Exit(1)


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")


if __name__ == "__main__":
    app()
