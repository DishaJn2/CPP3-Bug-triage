from abc import ABC, abstractmethod
from ..models.ticket import TicketData, ChangeEvent


class BaseConnector(ABC):
    def __init__(self, source_id: str, system_type: str, base_url: str,
                 project_key: str, ticket_prefix: str, token: str = ""):
        self.source_id = source_id
        self.system_type = system_type
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.ticket_prefix = ticket_prefix
        self.token = token

    @abstractmethod
    async def get(self, ticket_id: str) -> TicketData | None:
        pass

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[TicketData]:
        pass

    @abstractmethod
    async def get_linked_items(self, ticket_id: str) -> list[dict]:
        pass

    @abstractmethod
    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        pass
