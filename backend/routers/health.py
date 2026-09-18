"""
Local service health endpoints.
"""
from fastapi import APIRouter, Request
from middleware.api_standardization import APIResponse, create_success_response, create_error_response
from middleware.versioning import versioned_response
from database.factory import get_database_factory
import asyncio


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/", response_model=APIResponse[dict])
async def basic_health(request: Request):
    """Basic health check endpoint."""
    correlation_id = getattr(request.state, 'correlation_id', None)
    return create_success_response(
        data={"status": "healthy", "service": "ClauseIQ Legal AI Backend"},
        correlation_id=correlation_id
    )


@router.get("/database", response_model=APIResponse[dict])
@versioned_response
async def database_health(request: Request):
    """Check database connection health and pool status."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        db_factory = get_database_factory()
        # Test database connection with timeout
        health_result = await asyncio.wait_for(db_factory.health_check(), timeout=5)

        if health_result:
            return create_success_response(
                data={
                    "status": "healthy",
                    "connection_pool": "operational",
                },
                correlation_id=correlation_id
            )
        else:
            return create_error_response(
                message="Database health check failed",
                code="DATABASE_UNHEALTHY",
                correlation_id=correlation_id
            )

    except asyncio.TimeoutError:
        return create_error_response(
            message="Database health check timed out",
            code="DATABASE_TIMEOUT",
            correlation_id=correlation_id
        )
    except Exception:
        return create_error_response(
            message="Database health check failed",
            code="DATABASE_ERROR",
            correlation_id=correlation_id
        )
