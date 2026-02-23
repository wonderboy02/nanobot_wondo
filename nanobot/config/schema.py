"""Configuration schema using Pydantic."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class NotificationPolicyConfig(BaseModel):
    """Smart notification policy configuration.

    DESIGN: No Pydantic range validators (e.g., ge=0, le=23) applied intentionally.
    Config is written by the user in config.json — invalid values cause no crash,
    just unexpected quiet-hours behavior. See CLAUDE.md "Known Limitations #6".
    """

    quiet_hours_start: int = 23  # 23:00
    quiet_hours_end: int = 8  # 08:00
    daily_limit: int = 10  # Max notifications per day (High bypasses)
    dedup_window_hours: int = 24  # Block duplicate notifications within this window
    batch_max: int = 5  # Max notifications per batch message


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )
    notification_chat_id: str = ""  # Chat ID for instant notification delivery
    notification_policy: NotificationPolicyConfig = Field(default_factory=NotificationPolicyConfig)


class FeishuConfig(BaseModel):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = ""  # App ID from Feishu Open Platform
    app_secret: str = ""  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription (optional)
    verification_token: str = ""  # Verification Token for event subscription (optional)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user open_ids


class DiscordConfig(BaseModel):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""

    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)


class AgentDefaults(BaseModel):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20


class WorkerConfig(BaseModel):
    """Worker Agent configuration.

    COMPAT: extra='ignore' so existing config.json with removed fields
    (use_llm, fallback_to_rules) won't cause Pydantic validation errors.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    model: str = "google/gemini-2.0-flash-exp"


class AgentsConfig(BaseModel):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""

    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)


class NotionDatabasesConfig(BaseModel):
    """Notion database IDs for each Dashboard entity."""

    tasks: str = ""
    questions: str = ""
    notifications: str = ""
    insights: str = ""


class NotionConfig(BaseModel):
    """Notion integration configuration."""

    enabled: bool = False
    token: str = ""  # Notion integration token (secret_xxx)
    databases: NotionDatabasesConfig = Field(default_factory=NotionDatabasesConfig)
    cache_ttl_s: int = 300  # In-memory cache TTL (5 minutes)


class GoogleCalendarConfig(BaseModel):
    """Google Calendar sync configuration."""

    enabled: bool = False
    calendar_id: str = "primary"
    timezone: str = Field(default="Asia/Seoul", pattern=r"^[A-Za-z_]+/[A-Za-z_]+$")
    default_duration_minutes: int = Field(default=30, ge=1)
    client_secret_path: str = "~/.nanobot/google/client_secret.json"
    token_path: str = "~/.nanobot/google/token.json"


class GoogleConfig(BaseModel):
    """Google integrations configuration."""

    calendar: GoogleCalendarConfig = Field(default_factory=GoogleCalendarConfig)


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(BaseModel):
    """Web search tool configuration."""

    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(BaseModel):
    """Web tools configuration."""

    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(BaseModel):
    """Shell exec tool configuration."""

    timeout: int = 60


class ToolsConfig(BaseModel):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory


class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    notion: NotionConfig = Field(default_factory=NotionConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Match a provider based on model name."""
        model = (model or self.agents.defaults.model).lower()
        # Map of keywords to provider configs
        providers = {
            "openrouter": self.providers.openrouter,
            "deepseek": self.providers.deepseek,
            "anthropic": self.providers.anthropic,
            "claude": self.providers.anthropic,
            "openai": self.providers.openai,
            "gpt": self.providers.openai,
            "gemini": self.providers.gemini,
            "zhipu": self.providers.zhipu,
            "glm": self.providers.zhipu,
            "zai": self.providers.zhipu,
            "groq": self.providers.groq,
            "moonshot": self.providers.moonshot,
            "kimi": self.providers.moonshot,
            "vllm": self.providers.vllm,
        }
        for keyword, provider in providers.items():
            if keyword in model and provider.api_key:
                return provider
        return None

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model (or default model). Falls back to first available key."""
        # Try matching by model name first
        matched = self._match_provider(model)
        if matched:
            return matched.api_key
        # Fallback: return first available key
        for provider in [
            self.providers.openrouter,
            self.providers.deepseek,
            self.providers.anthropic,
            self.providers.openai,
            self.providers.gemini,
            self.providers.zhipu,
            self.providers.moonshot,
            self.providers.vllm,
            self.providers.groq,
        ]:
            if provider.api_key:
                return provider.api_key
        return None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL based on model name."""
        model = (model or self.agents.defaults.model).lower()
        if "openrouter" in model:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        if any(k in model for k in ("zhipu", "glm", "zai")):
            return self.providers.zhipu.api_base
        if "vllm" in model:
            return self.providers.vllm.api_base
        return None

    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
