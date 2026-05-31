import httpx
from .base_connector import BaseConnector
from ..models.ticket import TicketData, ChangeEvent


class CustomerPortalConnector(BaseConnector):
    """
    HPE Customer Portal connector.
    Returns customer-reported cases related to a bug by keywords.
    POC uses mock internal endpoint at http://localhost:8000/mock/customer-portal
    """

    async def get_cases_for_bug(self, keywords: list[str]) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{self.base_url}/cases",
                    params={"bug_keywords": ",".join(keywords[:5]), "limit": 3},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    return []
                return resp.json().get("cases", [])
        except Exception:
            return []

    async def search(self, query: str, max_results: int = 5, **kwargs) -> list[TicketData]:
        return []

    async def get(self, ticket_id: str) -> TicketData | None:
        return None

    async def get_linked_items(self, ticket_id: str) -> list[dict]:
        return []

    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        return []
