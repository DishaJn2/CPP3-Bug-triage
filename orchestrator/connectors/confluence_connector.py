import base64
import re
import os
import httpx
from .base_connector import BaseConnector
from ..models.ticket import TicketData, ChangeEvent


class ConfluenceConnector(BaseConnector):
    """
    Real Atlassian Confluence Cloud connector.
    Uses Basic auth: base64(email:api_token)
    API: Confluence Cloud REST API v1
    """

    def _headers(self) -> dict:
        email = os.getenv("CONFLUENCE_EMAIL", "")
        token = os.getenv("CONFLUENCE_API_TOKEN", "")
        if email and token:
            creds = base64.b64encode(f"{email}:{token}".encode()).decode()
            return {
                "Authorization": f"Basic {creds}",
                "Accept": "application/json",
            }
        return {"Accept": "application/json"}

    def _normalise(self, raw: dict) -> TicketData:
        body = raw.get("body", {})
        raw_content = (
            body.get("view", {}).get("value", "")
            or body.get("storage", {}).get("value", "")
        )
        clean_text = re.sub(r"<[^>]+>", " ", raw_content)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()[:1000]

        space = raw.get("space", {})
        space_key = space.get("key", "") if isinstance(space, dict) else ""

        links = raw.get("_links", {})
        base_url = links.get("base", self.base_url)
        web_ui = links.get("webui", "")
        full_url = f"{base_url}{web_ui}" if web_ui else ""

        version = raw.get("version", {})
        last_modified = version.get("when", "") if isinstance(version, dict) else ""

        return TicketData(
            ticket_id=f"CONF-{raw.get('id', '')}",
            title=raw.get("title", ""),
            description=clean_text,
            severity="Unknown",
            status=raw.get("status", "current"),
            component=space_key,
            assignee="",
            reporter="",
            created_at=last_modified,
            updated_at=last_modified,
            source_id=self.source_id,
            system_type=self.system_type,
            url=full_url,
            error_excerpt="",
            comments=[],
            linked_items=[],
            labels=[],
        )

    async def search(self, query: str, max_results: int = 5) -> list[TicketData]:
        """Search Confluence pages using CQL, trying multiple query forms."""
        space_key = os.getenv("CONFLUENCE_SPACE_KEY", self.project_key or "HPEKB")

        if query and query.strip():
            cql_queries = [
                f'type = "page" AND space = "{space_key}" AND text ~ "{query}"',
                f'type = "page" AND space = "{space_key}" AND title ~ "{query}"',
                f'type = "page" AND space = "{space_key}"',
            ]
        else:
            cql_queries = [f'type = "page" AND space = "{space_key}"']

        for cql in cql_queries:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=5.0)
                ) as client:
                    resp = await client.get(
                        f"{self.base_url}/rest/api/content/search",
                        params={
                            "cql": cql,
                            "limit": max_results,
                            "expand": "body.storage,body.view,space,version",
                        },
                        headers=self._headers(),
                    )

                    print(f"[ConfluenceConnector] CQL: {cql[:80]}", flush=True)
                    print(f"[ConfluenceConnector] Status: {resp.status_code}", flush=True)

                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        print(f"[ConfluenceConnector] Got {len(results)} results", flush=True)
                        if results:
                            return [self._normalise(item) for item in results]
                        continue
                    else:
                        print(f"[ConfluenceConnector] Error: {resp.text[:200]}", flush=True)
                        continue

            except Exception as e:
                print(f"[ConfluenceConnector] Exception: {e}", flush=True)
                continue

        return []

    async def get(self, ticket_id: str) -> TicketData | None:
        """Fetch a single Confluence page by ID."""
        page_id = ticket_id.replace("CONF-", "")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.base_url}/rest/api/content/{page_id}",
                    params={"expand": "body.view,body.storage,space,version"},
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return None
                return self._normalise(resp.json())
        except Exception:
            return None

    async def get_linked_items(self, ticket_id: str) -> list:
        return []

    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        return []
