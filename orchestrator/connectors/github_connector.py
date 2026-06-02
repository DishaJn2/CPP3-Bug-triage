import re
import httpx
from .base_connector import BaseConnector
from ..models.ticket import TicketData, ChangeEvent


SEVERITY_LABEL_MAP = {
    "priority:blocker": "P0",
    "priority:critical": "P0",
    "priority:high": "P1",
    "priority:medium": "P2",
    "priority:low": "P3",
    "bug": "P2",
    "enhancement": "P3",
}

SKIP_LABELS = {
    "bug", "enhancement", "question", "good first issue",
    "help wanted", "wontfix", "duplicate", "invalid",
}


class GithubConnector(BaseConnector):
    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _repo(self) -> str:
        return self.project_key

    def _normalise(self, raw: dict) -> TicketData:
        labels = [lbl.get("name", "") for lbl in raw.get("labels", [])]

        severity = "Unknown"
        for lbl in labels:
            lbl_lower = lbl.lower()
            if lbl_lower in SEVERITY_LABEL_MAP:
                severity = SEVERITY_LABEL_MAP[lbl_lower]
                break
        if severity == "Unknown":
            for lbl in labels:
                lbl_lower = lbl.lower()
                for key, val in SEVERITY_LABEL_MAP.items():
                    if key in lbl_lower:
                        severity = val
                        break
                if severity != "Unknown":
                    break

        component = ""
        for lbl in labels:
            if lbl.lower() not in SKIP_LABELS:
                component = lbl
                break

        body = raw.get("body") or ""
        linked = re.findall(r"#(\d+)", body)
        linked_items = [{"id": num, "type": "issue_ref", "title": ""} for num in linked[:10]]

        return TicketData(
            ticket_id=str(raw.get("number", "")),
            title=raw.get("title", ""),
            description=body[:2000],
            severity=severity,
            status="Open" if raw.get("state") == "open" else "Closed",
            component=component,
            assignee=((raw.get("assignee") or {}).get("login") or ""),
            reporter=((raw.get("user") or {}).get("login") or ""),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
            source_id=self.source_id,
            system_type=self.system_type,
            url=raw.get("html_url", ""),
            labels=labels,
            linked_items=linked_items,
        )

    async def get(self, ticket_id: str) -> TicketData | None:
        url = f"{self.base_url}/repos/{self._repo()}/issues/{ticket_id}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return self._normalise(resp.json())
        except Exception:
            return None

    async def search(self, query: str, max_results: int = 300, page: int = 1) -> list[TicketData]:
        if query:
            url = f"https://api.github.com/search/issues"
            params = {"q": f"{query}+repo:{self._repo()}+is:issue+is:open", "per_page": min(max_results, 100), "page": page}
        else:
            url = f"https://api.github.com/repos/{self._repo()}/issues"
            params = {"state": "open", "per_page": min(max_results, 100), "page": page, "sort": "updated", "direction": "desc"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                items = data.get("items", data) if query else data
                if not isinstance(items, list):
                    return []
                return [self._normalise(i) for i in items if i.get("pull_request") is None]
        except Exception:
            return []

    async def get_linked_items(self, ticket_id: str) -> list[dict]:
        ticket = await self.get(ticket_id)
        if ticket:
            return ticket.linked_items
        return []

    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        url = f"{self.base_url}/repos/{self._repo()}/issues/{ticket_id}/events"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                events = resp.json()
                changes = []
                for ev in events:
                    created = ev.get("created_at", "")
                    if since and created <= since:
                        continue
                    changes.append(ChangeEvent(
                        field=ev.get("event", ""),
                        old_value="",
                        new_value=str(ev.get("label", {}).get("name", "") if ev.get("label") else ""),
                        changed_at=created,
                        changed_by=(ev.get("actor") or {}).get("login", ""),
                    ))
                return changes
        except Exception:
            return []
