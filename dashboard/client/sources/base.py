from __future__ import annotations

from typing import Protocol

from dashboard.client.model import ClientData


class ClientSource(Protocol):
    def read(self, client: str, **kwargs) -> ClientData: ...
