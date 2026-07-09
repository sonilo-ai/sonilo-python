from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo


class Account:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def services(self) -> Dict[str, Any]:
        return self._client._get_json("/v1/account/services")

    def usage(self, *, days: Optional[int] = None) -> Dict[str, Any]:
        params = {"days": days} if days is not None else None
        return self._client._get_json("/v1/account/usage", params=params)


class AsyncAccount:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def services(self) -> Dict[str, Any]:
        return await self._client._get_json("/v1/account/services")

    async def usage(self, *, days: Optional[int] = None) -> Dict[str, Any]:
        params = {"days": days} if days is not None else None
        return await self._client._get_json("/v1/account/usage", params=params)
