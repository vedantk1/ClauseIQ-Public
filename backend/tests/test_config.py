"""
Tests for configuration models in config/environments.py.
These tests ensure environment variable parsing and validation work correctly.
"""
import pytest
import sys
from pathlib import Path
from pydantic import ValidationError

# Add the backend directory to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from config.environments import (
    DatabaseConfig,
    ServerConfig,
    AIConfig,
    QdrantConfig,
    FileUploadConfig,
    Environment
)


def test_database_default_matches_new_install_example_and_compose(monkeypatch):
    from dotenv import dotenv_values
    from config.environments import EnvironmentConfig
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    config = EnvironmentConfig(_env_file=None)
    example = dotenv_values(backend_dir / ".env.example")
    assert config.mongodb_database == example["MONGODB_DATABASE"] == "clauseiq"
    # Compose must honor the env_file instead of overriding an existing store.
    compose = (backend_dir.parent / "docker-compose.yml").read_text()
    assert "- MONGODB_DATABASE=" not in compose


def test_env_file_is_backend_relative_not_launch_directory(monkeypatch, tmp_path):
    from config.environments import EnvironmentConfig
    expected = backend_dir / ".env"
    assert EnvironmentConfig.model_config["env_file"] == expected
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MONGODB_DATABASE=unrelated_workspace\n")
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    # Use an isolated stand-in at the configured absolute path in this test.
    intended = tmp_path / "backend.env"
    intended.write_text("MONGODB_DATABASE=existing_workspace\n")
    monkeypatch.setitem(EnvironmentConfig.model_config, "env_file", intended)
    assert EnvironmentConfig().mongodb_database == "existing_workspace"
    monkeypatch.setenv("MONGODB_DATABASE", "explicit_workspace")
    assert EnvironmentConfig().mongodb_database == "explicit_workspace"


class TestDatabaseConfig:
    """Test DatabaseConfig validation."""

    def test_database_config_valid_data(self):
        """Test DatabaseConfig creation with valid data."""
        config_data = {
            "uri": "mongodb://localhost:27017/",
            "database": "test_db"
        }

        config = DatabaseConfig(**config_data)

        assert config.uri == "mongodb://localhost:27017/"
        assert config.database == "test_db"
        assert config.collection == "documents"  # default value
        assert config.max_pool_size == 20  # default value

    def test_database_config_mongodb_srv_uri(self):
        """Test that mongodb+srv:// URIs are accepted."""
        config_data = {
            "uri": "mongodb+srv://cluster.example.test/",
            "database": "prod_db"
        }

        config = DatabaseConfig(**config_data)
        assert config.uri.startswith("mongodb+srv://")

    def test_database_config_invalid_uri(self):
        """Test that invalid MongoDB URIs are rejected."""
        invalid_data = {
            "uri": "mysql://localhost:3306/",  # Wrong protocol
            "database": "test_db"
        }

        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(**invalid_data)

        error_str = str(exc_info.value)
        assert "MongoDB URI must start with mongodb://" in error_str

    def test_database_config_pool_size_validation(self):
        """Test that pool sizes are validated within reasonable ranges."""
        # Test maximum pool size validation
        invalid_data = {
            "uri": "mongodb://localhost:27017/",
            "database": "test_db",
            "max_pool_size": 150  # Too high
        }

        with pytest.raises(ValidationError):
            DatabaseConfig(**invalid_data)

        # Test minimum pool size validation - min should not exceed max
        invalid_data["max_pool_size"] = 50
        invalid_data["min_pool_size"] = 60  # Min > Max

        # This should raise a ValidationError because min > max
        with pytest.raises(ValidationError):
            DatabaseConfig(**invalid_data)


class TestServerConfig:
    """Test ServerConfig validation."""

    def test_server_config_defaults(self):
        """Test ServerConfig with default values."""
        config = ServerConfig()

        assert config.host == "localhost"
        assert config.port == 8000
        assert config.cors_origins == []
        assert config.debug is False

    def test_server_config_custom_values(self):
        """Test ServerConfig with custom values."""
        config_data = {
            "host": "0.0.0.0",
            "port": 3001,
            "cors_origins": ["http://localhost:3000", "https://example.com"],
            "debug": True
        }

        config = ServerConfig(**config_data)

        assert config.host == "0.0.0.0"
        assert config.port == 3001
        assert len(config.cors_origins) == 2
        assert config.debug is True

    def test_server_config_cors_origins_string_parsing(self):
        """Test that CORS origins can be parsed from comma-separated string."""
        config_data = {
            "cors_origins": "http://localhost:3000, https://example.com, https://app.com"
        }

        config = ServerConfig(**config_data)

        assert len(config.cors_origins) == 3
        assert "http://localhost:3000" in config.cors_origins
        assert "https://example.com" in config.cors_origins
        assert "https://app.com" in config.cors_origins

    def test_server_config_invalid_port(self):
        """Test that invalid port numbers are rejected."""
        invalid_data = {
            "port": 70000  # Port too high
        }

        with pytest.raises(ValidationError):
            ServerConfig(**invalid_data)

        invalid_data["port"] = 0  # Port too low

        with pytest.raises(ValidationError):
            ServerConfig(**invalid_data)



class TestAIConfig:
    """Test AI model and generation configuration."""

    def test_ai_config_defaults_without_server_credentials(self):
        """AI configuration must not carry a server-wide API key."""
        config = AIConfig()

        assert "openai_api_key" not in config.model_dump()
        assert config.default_model == "gpt-6-sol"
        assert config.max_tokens == 4000
        assert config.temperature == 0.7

    def test_ai_config_temperature_validation(self):
        """Test temperature range validation."""
        config = AIConfig(temperature=1.0)
        assert config.temperature == 1.0

        with pytest.raises(ValidationError):
            AIConfig(temperature=3.0)

    def test_ai_config_conversation_settings(self):
        """Test conversation context settings."""
        config = AIConfig(
            conversation_history_window=20,
            gate_model="gpt-3.5-turbo",
            rewrite_model="gpt-3.5-turbo"
        )

        assert config.conversation_history_window == 20
        assert config.gate_model == "gpt-3.5-turbo"
        assert config.rewrite_model == "gpt-3.5-turbo"


class TestQdrantConfig:
    """Test QdrantConfig validation."""

    def test_qdrant_config_defaults(self):
        """Test QdrantConfig with default values."""
        config = QdrantConfig()

        assert config.host == "localhost"
        assert config.port == 6333
        assert config.grpc_port == 6334
        assert config.collection_name == "clauseiq-vectors"
        assert config.api_key is None

    def test_qdrant_config_custom_values(self):
        """Test QdrantConfig with custom values."""
        config_data = {
            "host": "qdrant-server",
            "port": 6333,
            "grpc_port": 6334,
            "collection_name": "my-vectors",
            "api_key": "my-api-key"
        }

        config = QdrantConfig(**config_data)

        assert config.host == "qdrant-server"
        assert config.collection_name == "my-vectors"
        assert config.api_key == "my-api-key"

    def test_qdrant_config_docker_host(self):
        """Test QdrantConfig with Docker container hostname."""
        config_data = {
            "host": "qdrant",
            "port": 6333
        }

        config = QdrantConfig(**config_data)
        assert config.host == "qdrant"


class TestFileUploadConfig:
    """Test FileUploadConfig validation."""

    def test_file_upload_config_defaults(self):
        """Test FileUploadConfig with default values."""
        config = FileUploadConfig()

        assert config.max_file_size_mb == 10
        assert config.allowed_file_types == [".pdf"]
        assert config.storage_dir == "./documents_storage"

    def test_file_upload_config_custom_values(self):
        """Test FileUploadConfig with custom values."""
        config_data = {
            "max_file_size_mb": 25,
            "allowed_file_types": [".pdf", ".docx", ".txt"],
            "storage_dir": "/var/uploads"
        }

        config = FileUploadConfig(**config_data)

        assert config.max_file_size_mb == 25
        assert len(config.allowed_file_types) == 3
        assert ".docx" in config.allowed_file_types

    def test_file_upload_config_file_types_string_parsing(self):
        """Test that file types can be parsed from comma-separated string."""
        config_data = {
            "allowed_file_types": ".pdf, .docx, .txt"
        }

        config = FileUploadConfig(**config_data)

        assert len(config.allowed_file_types) == 3
        assert ".pdf" in config.allowed_file_types
        assert ".docx" in config.allowed_file_types
        assert ".txt" in config.allowed_file_types



class TestEnvironmentEnum:
    """Test the Environment enum."""

    def test_environment_values(self):
        """Test that Environment enum has expected values."""
        assert Environment.DEVELOPMENT == "development"
        assert Environment.STAGING == "staging"
        assert Environment.PRODUCTION == "production"
        assert Environment.TESTING == "testing"

        # Ensure all values are strings
        for env in Environment:
            assert isinstance(env.value, str)
