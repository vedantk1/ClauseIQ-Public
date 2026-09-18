"""Server-owned namespace for a single local library, not a synthetic account."""

WORKSPACE_ID = "local"


async def get_workspace_id() -> str:
    """Routes never accept a workspace identifier supplied by the browser."""
    return WORKSPACE_ID
