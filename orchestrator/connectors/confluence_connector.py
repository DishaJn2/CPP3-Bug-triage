import base64
import httpx
from .base_connector import BaseConnector
from ..models.ticket import TicketData, ChangeEvent


class ConfluenceConnector(BaseConnector):
    """
    Confluence connector that queries the mock internal Confluence endpoint.
    In production, base_url would point to real Confluence Cloud/Server.
    For POC: points to http://localhost:8000/mock/confluence
    """

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            encoded = base64.b64encode(
                f"demo@hpe.com:{self.token}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {encoded}"
        return headers

    async def search(self, query: str, max_results: int = 5, **kwargs) -> list[TicketData]:
        cql = f'text~"{query}" AND type=page' if query else "type=page"
        url = f"{self.base_url}/rest/api/content/search"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    url,
                    params={"cql": cql, "limit": max_results},
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                results = []
                for item in data.get("results", []):
                    body_text = (
                        item.get("body", {}).get("view", {}).get("value", "")
                    )
                    results.append(TicketData(
                        ticket_id=f"CONF-{item.get('id', '')}",
                        source_id=self.source_id,
                        title=item.get("title", ""),
                        description=body_text[:500],
                        status="Published",
                        severity="Unknown",
                        component=item.get("space", {}).get("key", ""),
                        assignee="",
                        reporter="",
                        created_at="",
                        updated_at="",
                        system_type=self.system_type,
                        url=item.get("_links", {}).get("webui", ""),
                    ))
                return results
        except Exception:
            return []

    async def get(self, ticket_id: str) -> TicketData | None:
        page_id = str(ticket_id).replace("CONF-", "")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/rest/api/content/{page_id}",
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return None
                item = resp.json()
                return TicketData(
                    ticket_id=f"CONF-{item.get('id', '')}",
                    source_id=self.source_id,
                    title=item.get("title", ""),
                    description="",
                    status="Published",
                    severity="Unknown",
                    component="",
                    assignee="",
                    reporter="",
                    created_at="",
                    updated_at="",
                    system_type=self.system_type,
                    url=item.get("_links", {}).get("webui", ""),
                )
        except Exception:
            return None

    async def get_linked_items(self, ticket_id: str) -> list[dict]:
        return []

    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        return []
