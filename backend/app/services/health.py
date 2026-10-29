from typing import Any

from sqlalchemy import text


class DatabaseHealthChecker:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def check(self) -> dict[str, str]:
        await self._session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
