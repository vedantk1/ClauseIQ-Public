"""Response-only cleanup for account metadata retained by workspace migration."""


def without_legacy_owner_fields(value):
    """Omit obsolete owner IDs without changing stored records or note/message text."""
    if isinstance(value, dict):
        return {
            key: without_legacy_owner_fields(child)
            for key, child in value.items()
            if key != "user_id"
        }
    if isinstance(value, list):
        return [without_legacy_owner_fields(child) for child in value]
    return value
