"""
🚀 FOUNDATIONAL LOGGING CONFIGURATION
Centralized, robust logging for the entire ClauseIQ backend.
"""
import logging
import logging.handlers
import os
import re
import sys


class FoundationalLogger:
    """
    🎯 FOUNDATIONAL: Single source of truth for all application logging.
    No more scattered basicConfig calls - everything goes through here!
    """

    _configured = False

    @classmethod
    def configure(cls, log_level: str = "INFO", log_dir: str = "logs"):
        """Configure logging for the entire application."""
        if cls._configured:
            return

        # Create logs directory
        os.makedirs(log_dir, exist_ok=True)

        # Root logger configuration
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))

        # Clear any existing handlers
        root_logger.handlers.clear()

        # Console handler with colored output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
        app_file_handler.setLevel(logging.DEBUG)
        app_file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
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
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(app_file_formatter)
        root_logger.addHandler(error_file_handler)

        # Configure specific loggers
        cls._configure_chat_logger(log_dir)
        cls._configure_api_logger(log_dir)

        cls._configured = True

        # Log the configuration
        logger = logging.getLogger("foundational.logging")
        logger.info("Foundational logging configuration complete")
        logger.info("Log level configured: %s", log_level.upper())
        logger.info("Application and error log handlers configured")

    @classmethod
    def _configure_chat_logger(cls, log_dir: str):
        """Configure dedicated chat logger."""
        chat_logger = logging.getLogger("chat")
        chat_logger.setLevel(logging.DEBUG)

        # Chat-specific file handler
        chat_log_file = os.path.join(log_dir, "chat.log")
        chat_file_handler = logging.handlers.RotatingFileHandler(
            chat_log_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        chat_file_handler.setLevel(logging.DEBUG)
        chat_formatter = logging.Formatter(
            '%(asctime)s - CHAT - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        chat_file_handler.setFormatter(chat_formatter)
        chat_logger.addHandler(chat_file_handler)

        # Allow propagation to also log to main app.log
        chat_logger.propagate = True

    @classmethod
    def _configure_api_logger(cls, log_dir: str):
        """Configure dedicated API request/response logger."""
        api_logger = logging.getLogger("clauseiq_api")
        api_logger.setLevel(logging.INFO)

        # API-specific file handler
        api_log_file = os.path.join(log_dir, "api.log")
        api_file_handler = logging.handlers.RotatingFileHandler(
            api_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        api_file_handler.setLevel(logging.INFO)
        api_formatter = logging.Formatter(
            '%(asctime)s - API - %(levelname)s - %(message)s'
        )
        api_file_handler.setFormatter(api_formatter)
        api_logger.addHandler(api_file_handler)

        # Allow propagation
        api_logger.propagate = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with proper configuration."""
        if not cls._configured:
            cls.configure()
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
    """
    🚀 FOUNDATIONAL: Get a properly configured logger.
    Use this instead of logging.getLogger() throughout the app.
    """
    return FoundationalLogger.get_logger(name)


def log_exception(
    logger: logging.Logger,
    operation: str,
    exc: Exception,
) -> None:
    """Log content-safe exception metadata for a named operation."""
    FoundationalLogger.log_exception(logger, operation, exc)
