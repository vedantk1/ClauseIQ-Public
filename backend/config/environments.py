"""
Environment-specific configuration management for ClauseIQ.
Provides configuration validation and environment-aware settings.
"""
from enum import Enum
from urllib.parse import urlsplit
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    """Application environment types."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class DatabaseConfig(BaseModel):
    """Database configuration with validation."""
    uri: str = Field(..., description="MongoDB connection URI")
    database: str = Field(..., description="Database name")
    collection: str = Field(default="documents", description="Default collection name")
    collection_prefix: str = Field(default="", description="Collection prefix for multi-tenancy")

    # Connection pool settings
    max_pool_size: int = Field(default=20, ge=1, le=100, description="Maximum connection pool size")
    min_pool_size: int = Field(default=5, ge=0, le=50, description="Minimum connection pool size")
    max_idle_time_ms: int = Field(default=600000, ge=10000, description="Max idle time in milliseconds (10 minutes)")
    wait_queue_timeout_ms: int = Field(default=30000, ge=1000, description="Wait queue timeout in milliseconds")
    server_selection_timeout_ms: int = Field(default=30000, ge=1000, description="Server selection timeout in milliseconds")

    @validator('uri')
    def validate_uri(cls, v):
        if not v.startswith(('mongodb://', 'mongodb+srv://')):
            raise ValueError('MongoDB URI must start with mongodb:// or mongodb+srv://')
        return v


class ServerConfig(BaseModel):
    """Server configuration with validation."""
    host: str = Field(default="localhost", description="Server host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    cors_origins: list[str] = Field(default_factory=list, description="CORS allowed origins")
    debug: bool = Field(default=False, description="Debug mode")

    @validator('cors_origins', pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v or []


class AIConfig(BaseModel):
    """AI model and generation configuration with validation."""
    default_model: str = Field(default="gpt-5", description="Default AI model")
    max_tokens: int = Field(default=4000, ge=1, description="Maximum tokens per request")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="AI temperature")

    # Conversation context settings
    conversation_history_window: int = Field(default=10, ge=1, le=50, description="Max conversation turns to consider for context")
    gate_model: str = Field(default="gpt-5-nano", description="Model for conversation context gate")
    rewrite_model: str = Field(default="gpt-5", description="Model for query rewriting")






class QdrantConfig(BaseModel):
    """Qdrant configuration for vector search (self-hosted)."""
    host: str = Field(default="localhost", description="Qdrant server host")
    port: int = Field(default=6333, ge=1, le=65535, description="Qdrant REST API port")
    grpc_port: int = Field(default=6334, ge=1, le=65535, description="Qdrant gRPC port")
    collection_name: str = Field(default="clauseiq-vectors", description="Qdrant collection name")
    api_key: Optional[str] = Field(default=None, description="Qdrant API key (optional, for cloud)")


class FileUploadConfig(BaseModel):
    """File upload configuration with validation."""
    max_file_size_mb: int = Field(default=10, ge=1, le=100, description="Maximum file size in MB")
    allowed_file_types: list[str] = Field(default=[".pdf"], description="Allowed file extensions")
    storage_dir: str = Field(default="./documents_storage", description="Storage directory")

    @validator('allowed_file_types', pre=True)
    def parse_file_types(cls, v):
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return v or [".pdf"]


class EnvironmentConfig(BaseSettings):
    """Full application configuration with environment variable support."""
    # Environment
    environment: Environment = Field(default=Environment.DEVELOPMENT, description="Application environment")

    # Database - Environment variables mapped directly
    mongodb_uri: str = Field(default="mongodb://localhost:27017/", description="MongoDB local connection URI")
    mongodb_database: str = Field(default="legal_ai", description="MongoDB database name")
    mongodb_collection: str = Field(default="documents", description="MongoDB collection name")
    mongodb_collection_prefix: str = Field(default="", description="MongoDB collection prefix for multi-tenancy")

    # Database connection pool settings
    mongodb_max_pool_size: int = Field(default=20, description="MongoDB maximum connection pool size")
    mongodb_min_pool_size: int = Field(default=5, description="MongoDB minimum connection pool size")
    mongodb_max_idle_time_ms: int = Field(default=600000, description="MongoDB max idle time in milliseconds")
    mongodb_wait_queue_timeout_ms: int = Field(default=30000, description="MongoDB wait queue timeout in milliseconds")
    mongodb_server_selection_timeout_ms: int = Field(default=30000, description="MongoDB server selection timeout in milliseconds")

    # Server
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", description="Local frontend origins")
    debug: bool = Field(default=False, description="Debug mode")

    # Relative paths are resolved from the backend directory, including in Docker.
    workspace_state_dir: str = Field(default=".local-only/workspace", description="Private local credential state directory")

    # AI
    openai_default_model: str = Field(default="gpt-5", description="Default AI model")
    openai_max_tokens: int = Field(default=4000, description="Maximum tokens per request")
    openai_temperature: float = Field(default=0.7, description="AI temperature")



    # Qdrant Vector Search (self-hosted)
    qdrant_host: str = Field(default="localhost", description="Qdrant server host")
    qdrant_port: int = Field(default=6333, description="Qdrant REST API port")
    qdrant_grpc_port: int = Field(default=6334, description="Qdrant gRPC port")
    qdrant_collection: str = Field(default="clauseiq-vectors", description="Qdrant collection name")
    qdrant_api_key: Optional[str] = Field(default=None, description="Qdrant API key (optional)")

    # File Upload
    max_file_size_mb: int = Field(default=10, description="Maximum file size in MB")
    allowed_file_types: str = Field(default=".pdf", description="Allowed file extensions")
    storage_dir: str = Field(default="./documents_storage", description="Storage directory")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    @property
    def database(self) -> DatabaseConfig:
        """Get database configuration."""
        return DatabaseConfig(
            uri=self.mongodb_uri,
            database=self.mongodb_database,
            collection=self.mongodb_collection,
            collection_prefix=self.mongodb_collection_prefix,
            max_pool_size=self.mongodb_max_pool_size,
            min_pool_size=self.mongodb_min_pool_size,
            max_idle_time_ms=self.mongodb_max_idle_time_ms,
            wait_queue_timeout_ms=self.mongodb_wait_queue_timeout_ms,
            server_selection_timeout_ms=self.mongodb_server_selection_timeout_ms
        )

    @property
    def server(self) -> ServerConfig:
        """Get server configuration."""
        return ServerConfig(
            host=self.host,
            port=self.port,
            cors_origins=[origin.strip() for origin in self.cors_origins.split(",") if origin.strip()],
            debug=self.debug
        )

    @property
    def ai(self) -> AIConfig:
        """Get AI configuration."""
        return AIConfig(
            default_model=self.openai_default_model,
            max_tokens=self.openai_max_tokens,
            temperature=self.openai_temperature
        )



    @property
    def qdrant(self) -> QdrantConfig:
        """Get Qdrant configuration."""
        return QdrantConfig(
            host=self.qdrant_host,
            port=self.qdrant_port,
            grpc_port=self.qdrant_grpc_port,
            collection_name=self.qdrant_collection,
            api_key=self.qdrant_api_key
        )

    @property
    def file_upload(self) -> FileUploadConfig:
        """Get file upload configuration."""
        return FileUploadConfig(
            max_file_size_mb=self.max_file_size_mb,
            allowed_file_types=[ext.strip() for ext in self.allowed_file_types.split(",") if ext.strip()],
            storage_dir=self.storage_dir
        )

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PRODUCTION

    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.environment == Environment.TESTING

    def get_environment_vars(self) -> Dict[str, Any]:
        """Get environment-specific configuration as dict."""
        return {
            "environment": self.environment.value,
            "debug": self.server.debug,
            "database_name": self.database.database,
            "cors_origins": self.server.cors_origins,
            "max_file_size": self.file_upload.max_file_size_mb,
        }


def get_environment_config() -> EnvironmentConfig:
    """Validate a local-only installation; hosted modes are unsupported."""
    config = EnvironmentConfig()
    if config.environment in (Environment.PRODUCTION, Environment.STAGING):
        raise RuntimeError("ClauseIQ supports local development/testing only, not hosted environments.")
    for origin in config.server.cors_origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or parsed.hostname not in
                ("localhost", "127.0.0.1", "::1") or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("CORS_ORIGINS must contain exact loopback browser origins only")
    return config
