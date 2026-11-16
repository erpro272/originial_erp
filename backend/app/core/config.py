"""Application settings, read from environment variables (prefix ``ERP_``)."""

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERP_", env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    # Dev convenience: `seed.run --if-empty` fills in demo data only when this is true.
    seed_demo: bool = False
    app_name: str = "Brand"  # neutral placeholder until the product is named

    # Database. The API connects as a NON-owner role so row-level security applies.
    database_url: str = "postgresql+asyncpg://erp_app:erp_app@localhost:5432/erp"
    # Migrations and seeding run as the owner role (creates tables, policies, grants).
    database_owner_url: str = "postgresql+asyncpg://erp_owner:erp_owner@localhost:5432/erp"

    redis_url: str = "redis://localhost:6379/0"
    jobs_inline: bool = False  # tests: run background jobs in-process

    # Object storage (S3-compatible; MinIO locally).
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_public_endpoint_url: str | None = None  # host the browser uses for signed URLs
    s3_region: str = "ap-south-1"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "erp-files"
    signed_url_ttl_seconds: int = 300
    # Optional extra at-rest encryption by the store (e.g. "AES256" on AWS S3). Files are
    # already encrypted by the app with the company key before upload.
    s3_server_side_encryption: str | None = None

    # Auth
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "erp-api"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 3600
    cookie_secure: bool = False

    # Layer-2 encryption: key-encryption key (KEK) that wraps each tenant's data key.
    # 32 bytes, base64. Replace the KeyProvider with a KMS in production.
    master_key: SecretStr = SecretStr("ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcyEhISE=")

    # AI: any OpenAI-compatible endpoint, Groq's free tier by default (owner's choice). When LLM_API_KEY is
    # unset everything runs in mock mode (fixture / scripted responses, used by all tests).
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.groq.com/openai/v1", validation_alias="LLM_BASE_URL")
    llm_primary_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="LLM_PRIMARY_MODEL")
    llm_fallback_model: str = Field(default="llama-3.1-8b-instant", validation_alias="LLM_FALLBACK_MODEL")
    llm_vision_model: str = Field(default="meta-llama/llama-4-scout-17b-16e-instruct",
                                  validation_alias="LLM_VISION_MODEL")  # fmt: skip
    llm_timeout_seconds: float = 60.0

    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> "Settings":
        if self.env == "prod":
            dev = Settings.model_fields
            for name in ("jwt_secret", "master_key", "s3_secret_key"):
                if getattr(self, name) == dev[name].default:
                    raise ValueError(f"ERP_{name.upper()} must be set in production")
            if not self.cookie_secure:
                raise ValueError("ERP_COOKIE_SECURE must be true in production")
        return self

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
