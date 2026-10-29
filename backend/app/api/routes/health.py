import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_health_checker
from app.services.protocols import HealthCheckerProtocol

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
HealthCheckerDependency = Annotated[HealthCheckerProtocol, Depends(get_health_checker)]


@router.get("/health")
async def health(checker: HealthCheckerDependency) -> dict[str, str]:
    try:
        return await checker.check()
    except Exception as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from exc
