"""Explicit application logging configuration with content-safe request IDs."""
import logging
import logging.handlers
import os
import re
import sys

from middleware.request_context import current_request_id


class RequestContextFilter(logging.Filter):
    """Attach the server-owned HTTP ID, never an arbitrary LogRecord extra."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.http_request_id = current_request_id() or "-"
        return True


class FoundationalLogger:
    """Configure application logging explicitly, independent of import order."""

    _configured = False
    _configuration: tuple[str, str] | None = None

    @classmethod
    def configure(cls, log_level: str = "INFO", log_dir: str = "logs"):
        """Configure logging for the entire application."""
        level = logging.getLevelNamesMapping().get(log_level.upper())
        if level is None:
            raise ValueError("Unsupported logging level")
        configuration = (log_level.upper(), os.path.abspath(log_dir))
        if cls._configured and cls._configuration == configuration:
            return

        # Create logs directory
        os.makedirs(log_dir, exist_ok=True)

        # Root logger configuration
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Close only owned handlers. Keep handlers installed by test runners or
        # host processes, including when explicitly changing the configuration.
        for name in ("", "chat", "clauseiq_api"):
            target = logging.getLogger(name)
            for handler in tuple(target.handlers):
                if getattr(handler, "_clauseiq_handler", False):
                    target.removeHandler(handler)
                    handler.close()

        console_handler = logging.StreamHandler(sys.stdout)
        cls._prepare_handler(console_handler, level)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - request_id=%(http_request_id)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

        # Application log file (rotating)
        app_log_file = os.path.join(log_dir, "app.log")
        app_file_handler = logging.handlers.RotatingFileHandler(
            app_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        cls._prepare_handler(app_file_handler, level)
        app_file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - request_id=%(http_request_id)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        app_file_handler.setFormatter(app_file_formatter)
        root_logger.addHandler(app_file_handler)

        # Error log file (only errors and critical)
        error_log_file = os.path.join(log_dir, "error.log")
        error_file_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3
        )
        cls._prepare_handler(error_file_handler, max(level, logging.ERROR))
        error_file_handler.setFormatter(app_file_formatter)
        root_logger.addHandler(error_file_handler)

        # Configure specific loggers
        cls._configure_chat_logger(log_dir, level)
        cls._configure_api_logger(log_dir, level)

        cls._configured = True
        cls._configuration = configuration

        # Log the configuration
        logger = logging.getLogger("foundational.logging")
        logger.info("Application logging configured: level=%s", log_level.upper())

    @staticmethod
    def _prepare_handler(handler: logging.Handler, level: int) -> None:
        handler._clauseiq_handler = True
        handler.setLevel(level)
        handler.addFilter(RequestContextFilter())

    @classmethod
    def _configure_chat_logger(cls, log_dir: str, level: int):
        """Configure dedicated chat logger."""
        chat_logger = logging.getLogger("chat")
        chat_logger.setLevel(level)

        # Chat-specific file handler
        chat_log_file = os.path.join(log_dir, "chat.log")
        chat_file_handler = logging.handlers.RotatingFileHandler(
            chat_log_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        cls._prepare_handler(chat_file_handler, level)
        chat_formatter = logging.Formatter(
            '%(asctime)s - CHAT - %(levelname)s - request_id=%(http_request_id)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        chat_file_handler.setFormatter(chat_formatter)
        chat_logger.addHandler(chat_file_handler)

        # Allow propagation to also log to main app.log
        chat_logger.propagate = True

    @classmethod
    def _configure_api_logger(cls, log_dir: str, level: int):
        """Configure dedicated API request/response logger."""
        api_logger = logging.getLogger("clauseiq_api")
        api_logger.setLevel(level)

        # API-specific file handler
        api_log_file = os.path.join(log_dir, "api.log")
        api_file_handler = logging.handlers.RotatingFileHandler(
            api_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        cls._prepare_handler(api_file_handler, level)
        api_formatter = logging.Formatter(
            '%(asctime)s - API - %(levelname)s - request_id=%(http_request_id)s - %(message)s'
        )
        api_file_handler.setFormatter(api_formatter)
        api_logger.addHandler(api_file_handler)

        # Allow propagation
        api_logger.propagate = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Retrieve a logger without changing configuration during imports."""
        return logging.getLogger(name)

    @classmethod
    def log_exception(
        cls,
        logger: logging.Logger,
        operation: str,
        exc: Exception,
    ) -> None:
        """Log a stable operation label and exception class only."""
        safe_operation = (
            operation
            if isinstance(operation, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", operation)
            else "operation"
        )
        logger.error(
            "Operation failed: operation=%s error_type=%s",
            safe_operation,
            exc.__class__.__name__,
        )


def get_foundational_logger(name: str) -> logging.Logger:
    """Retrieve an application logger; startup owns its configuration."""
    return FoundationalLogger.get_logger(name)


def log_exception(
    logger: logging.Logger,
    operation: str,
    exc: Exception,
) -> None:
    """Log content-safe exception metadata for a named operation."""
    FoundationalLogger.log_exception(logger, operation, exc)
