from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    APP_NAME: str = "AI Agent"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"

    OPENAI_API_KEY: str
    LLM_MODEL: str = "gpt-4o-mini"

    AGENT_API_KEY: str
    JWT_SECRET: str

    RATE_LIMIT_PER_MINUTE: int = 20
    DAILY_BUDGET_USD: float = 5.0

    REDIS_URL: str = "redis://localhost:6379/0"
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()