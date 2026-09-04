"""
Document Cleanup Service.

Handles automatic cleanup of expired documents based on admin-configured retention period.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DocumentCleanupService:
    """Service for managing automatic document cleanup."""

    def __init__(self):
        self._is_running = False
        self._last_run: Optional[str] = None
        self._last_result: Optional[Dict[str, Any]] = None

    async def run_cleanup(self) -> Dict[str, Any]:
        """
        Run the document cleanup process.

        Returns:
            Dict with cleanup results
        """
        if self._is_running:
            logger.warning("Cleanup is already running, skipping...")
            return {
                "skipped": True,
                "reason": "Cleanup already in progress",
                "run_at": datetime.now().isoformat()
            }

        self._is_running = True

        try:
            from database.service import get_document_service

            service = get_document_service()
            result = await service.cleanup_expired_documents()

            self._last_run = datetime.now().isoformat()
            self._last_result = result

            if result.get("skipped"):
                logger.info(f"Cleanup skipped: {result.get('reason', 'Unknown reason')}")
            else:
                logger.info(
                    f"Document cleanup completed: "
                    f"{result.get('deleted_count', 0)} deleted, "
                    f"{result.get('failed_count', 0)} failed"
                )

            return result

        except Exception as e:
            logger.error("Document cleanup failed: %s", type(e).__name__)
            return {
                "deleted_count": 0,
                "failed_count": 0,
                "errors": ["Document cleanup failed"],
                "run_at": datetime.now().isoformat()
            }
        finally:
            self._is_running = False

    def get_status(self) -> Dict[str, Any]:
        """Get the status of the cleanup service."""
        return {
            "is_running": self._is_running,
            "last_run": self._last_run,
            "last_result": self._last_result
        }


# Global singleton instance
_cleanup_service: Optional[DocumentCleanupService] = None


def get_cleanup_service() -> DocumentCleanupService:
    """Get the cleanup service singleton."""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = DocumentCleanupService()
    return _cleanup_service


async def run_startup_cleanup():
    """
    Run document cleanup on application startup.

    This is a fire-and-forget background task that runs once at startup.
    """
    try:
        # Small delay to allow other startup tasks to complete
        await asyncio.sleep(5)

        logger.info("Running startup document cleanup...")

        service = get_cleanup_service()
        result = await service.run_cleanup()

        if result.get("skipped"):
            logger.info(f"Startup cleanup skipped: {result.get('reason')}")
        else:
            logger.info(
                f"Startup cleanup completed: "
                f"{result.get('deleted_count', 0)} documents deleted"
            )

    except Exception as e:
        logger.error("Startup document cleanup failed: %s", type(e).__name__)
