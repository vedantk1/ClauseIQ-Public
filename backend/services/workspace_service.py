"""Settings and credentials for the local installation, separate from documents."""
import logging
from datetime import datetime, timezone

from ai_models.models import AIModelConfig
from database.factory import DatabaseFactory
from database.service import get_document_service
from services.encryption_service import get_encryption_service, decrypt_legacy_api_key
from workspace import WORKSPACE_ID

logger = logging.getLogger(__name__)


class WorkspaceService:
    async def _credentials(self):
        db = await DatabaseFactory.get_database()
        return db._get_collection("workspace_credentials")

    async def initialize_credentials(self, legacy_user_id: str | None) -> None:
        """Import one proven legacy owner's key without deleting original data."""
        collection = await self._credentials()
        record = await collection.find_one({"id": WORKSPACE_ID})
        if record and not record.get("legacy_import_pending"):
            return
        encrypted = None
        if legacy_user_id:
            db = await DatabaseFactory.get_database()
            user = await db._get_collection("users").find_one({"id": legacy_user_id})
            if user and user.get("openai_api_key_set"):
                encrypted = user.get("openai_api_key_encrypted")
        if encrypted:
            try:
                await self.set_api_key(decrypt_legacy_api_key(encrypted))
                return
            except ValueError:
                logger.warning("Legacy API key needs re-entry in Settings; original data was preserved")
                await collection.update_one({"id": WORKSPACE_ID}, {"$set": {
                    "legacy_import_pending": True,
                }}, upsert=True)
                return
        await collection.update_one({"id": WORKSPACE_ID}, {"$set": {
            "legacy_import_pending": False,
        }}, upsert=True)

    async def get_api_key(self) -> str | None:
        record = await (await self._credentials()).find_one({"id": WORKSPACE_ID})
        encrypted = record.get("encrypted_key") if record else None
        if not encrypted:
            return None
        try:
            return get_encryption_service().decrypt(encrypted)
        except ValueError:
            return None

    async def has_api_key(self) -> bool:
        return bool(await self.get_api_key())

    async def set_api_key(self, api_key: str) -> None:
        if not api_key.startswith("sk-") or any(char.isspace() for char in api_key) or len(api_key) > 512:
            raise ValueError("Enter a valid OpenAI API key")
        encrypted = get_encryption_service().encrypt(api_key)
        await (await self._credentials()).update_one({"id": WORKSPACE_ID}, {"$set": {
            "encrypted_key": encrypted,
            "legacy_import_pending": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}, upsert=True)

    async def delete_api_key(self) -> None:
        # A tombstone prevents startup resurrecting a deliberately removed key.
        await (await self._credentials()).update_one({"id": WORKSPACE_ID}, {
            "$unset": {"encrypted_key": ""},
            "$set": {"legacy_import_pending": False,
                     "updated_at": datetime.now(timezone.utc).isoformat()},
        }, upsert=True)

    async def get_settings(self) -> dict:
        documents = get_document_service()
        retention = await documents.get_auto_delete_config()
        ui = await documents.get_ui_settings()
        record = await (await self._credentials()).find_one({"id": WORKSPACE_ID})
        has_key = await self.has_api_key()
        return {
            "has_api_key": has_key,
            "api_key_needs_reentry": bool(record and not has_key and
                (record.get("encrypted_key") or record.get("legacy_import_pending"))),
            "model_id": await documents.get_system_ai_model(),
            "query_gate_model_id": await documents.get_query_gate_model(),
            "available_models": AIModelConfig.get_models_for_api(),
            "retention_days": retention["days"] if retention.get("enabled") else 0,
            "toast_notifications_enabled": ui["toast_notifications_enabled"],
        }

    async def update_settings(self, settings: dict) -> dict:
        documents = get_document_service()
        actions = {
            "model_id": documents.set_system_ai_model,
            "query_gate_model_id": documents.set_query_gate_model,
            "retention_days": documents.set_auto_delete_config,
        }
        for field, method in actions.items():
            if field in settings and not await method(settings[field], WORKSPACE_ID):
                raise RuntimeError("Could not save workspace settings")
        if "toast_notifications_enabled" in settings:
            if not await documents.set_ui_settings({
                "toast_notifications_enabled": settings["toast_notifications_enabled"],
            }, WORKSPACE_ID):
                raise RuntimeError("Could not save workspace settings")
        return await self.get_settings()


_service = WorkspaceService()


def get_workspace_service() -> WorkspaceService:
    return _service
