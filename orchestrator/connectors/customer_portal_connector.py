import asyncio
import html
import re

import httpx

from .base_connector import BaseConnector
from ..models.ticket import TicketData, ChangeEvent


HN_ENDPOINT = "https://hn.algolia.com/api/v1/search"
STACK_ENDPOINT = "https://api.stackexchange.com/2.3/search/advanced"


class CustomerPortalConnector(BaseConnector):
    """Public customer-signal connector for open-source demo data."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_error: dict = {}

    async def search(
            self,
            query: str,
            max_results: int = 5,
            **kwargs) -> list[TicketData]:
        self.last_error = {}
        primary_ticket = kwargs.get("primary_ticket") or {}
        terms = self._build_query(query, primary_ticket)
        if not terms:
            return []

        try:
            hn_task = self._search_hacker_news(terms, max_results)
            so_task = self._search_stackoverflow(terms, max_results)
            gathered = await asyncio.gather(
                hn_task, so_task, return_exceptions=True)
        except Exception as e:
            self.last_error = {
                "source": self.source_id,
                "error": str(e)[:300],
            }
            return []

        signals: list[TicketData] = []
        errors = []
        for item in gathered:
            if isinstance(item, Exception):
                errors.append(str(item)[:300])
                continue
            signals.extend(item)

        if errors:
            self.last_error = {
                "source": self.source_id,
                "error": "; ".join(errors)[:300],
            }

        seen: set[str] = set()
        unique: list[TicketData] = []
        for ticket in sorted(
                signals,
                key=lambda t: getattr(t, "signal_score", 0.0),
                reverse=True):
            if ticket.ticket_id in seen:
                continue
            seen.add(ticket.ticket_id)
            unique.append(ticket)
            if len(unique) >= max_results:
                break
        return unique

    async def get(self, ticket_id: str) -> TicketData | None:
        return None

    async def get_linked_items(self, ticket_id: str) -> list[dict]:
        return []

    async def get_changelog(self, ticket_id: str, since: str = "") -> list[ChangeEvent]:
        return []

    async def get_lightweight(self, ticket_id: str) -> dict:
        return {}

    def extract_links(self, raw_payload: dict) -> list[dict]:
        return []

    def _build_query(self, query: str, primary_ticket: dict) -> str:
        text_parts = [
            query or "",
            primary_ticket.get("title", ""),
            primary_ticket.get("component", ""),
            primary_ticket.get("error_excerpt", ""),
            " ".join(primary_ticket.get("keywords") or []),
            primary_ticket.get("description", "")[:1000],
        ]
        words = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", " ".join(text_parts))
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "into",
            "error", "issue", "bug", "failed", "failure", "cannot", "able",
            "when", "while", "using", "update", "fix", "add", "remove",
        }
        selected = []
        for word in words:
            clean = word.strip(".,()[]{}").lower()
            if clean in stop or clean.isdigit():
                continue
            if clean not in selected:
                selected.append(clean)
            if len(selected) >= 8:
                break
        return " ".join(selected)

    async def _search_hacker_news(
            self, query: str, max_results: int) -> list[TicketData]:
        params = {
            "query": query,
            "tags": "story,comment",
            "hitsPerPage": str(max_results),
        }
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(HN_ENDPOINT, params=params)
            response.raise_for_status()
            payload = response.json()

        tickets = []
        for hit in payload.get("hits", [])[:max_results]:
            title = (
                hit.get("title")
                or hit.get("story_title")
                or self._clean_html(hit.get("comment_text", ""))[:100]
                or "Hacker News discussion"
            )
            points = int(hit.get("points") or 0)
            comments = int(hit.get("num_comments") or 0)
            severity = self._hn_severity(points, comments)
            score = self._score_hn(points, comments)
            url = hit.get("url") or hit.get("story_url") or (
                f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            )
            summary = self._clean_html(
                hit.get("comment_text") or hit.get("story_text") or title)
            tickets.append(self._ticket(
                case_id=f"HN-{hit.get('objectID')}",
                source="Hacker News",
                customer_name=hit.get("author") or "HN user",
                severity=severity,
                status="discussion",
                summary=title,
                impact=(
                    f"Developer discussion with {points} points and "
                    f"{comments} comments. {summary[:180]}").strip(),
                url=url,
                linked_ticket_id=hit.get("story_id") or hit.get("objectID"),
                signal_score=score,
            ))
        return tickets

    async def _search_stackoverflow(
            self, query: str, max_results: int) -> list[TicketData]:
        params = {
            "order": "desc",
            "sort": "relevance",
            "q": query,
            "site": "stackoverflow",
            "filter": "withbody",
            "pagesize": str(max_results),
        }
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(STACK_ENDPOINT, params=params)
            response.raise_for_status()
            payload = response.json()

        tickets = []
        for item in payload.get("items", [])[:max_results]:
            score = int(item.get("score") or 0)
            views = int(item.get("view_count") or 0)
            severity = self._so_severity(views, score)
            signal_score = self._score_so(views, score)
            owner = item.get("owner") or {}
            summary = self._clean_html(item.get("body", ""))
            tickets.append(self._ticket(
                case_id=f"SO-{item.get('question_id')}",
                source="Stack Overflow",
                customer_name=owner.get("display_name") or "StackOverflow user",
                severity=severity,
                status="answered" if item.get("is_answered") else "open",
                summary=self._clean_html(item.get("title", "")),
                impact=(
                    f"Question has {views} views and score {score}. "
                    f"{summary[:180]}").strip(),
                url=item.get("link", ""),
                linked_ticket_id=item.get("question_id"),
                signal_score=signal_score,
            ))
        return tickets

    def _ticket(
            self,
            case_id: str,
            source: str,
            customer_name: str,
            severity: str,
            status: str,
            summary: str,
            impact: str,
            url: str,
            linked_ticket_id,
            signal_score: float) -> TicketData:
        ticket = TicketData(
            ticket_id=case_id,
            title=summary or source,
            description=impact or "",
            severity=severity,
            status=status,
            component="",
            assignee="",
            reporter=customer_name,
            created_at="",
            updated_at="",
            source_id=self.source_id,
            system_type=self.system_type,
            url=url,
        )
        metadata = {
            "case_id": case_id,
            "source": source,
            "customer_name": customer_name,
            "customer": customer_name,
            "severity": severity,
            "status": status,
            "summary": summary or source,
            "title": summary or source,
            "impact": impact or "",
            "url": url,
            "linked_ticket_id": str(linked_ticket_id or ""),
            "signal_score": round(max(0.0, min(signal_score, 1.0)), 2),
        }
        setattr(ticket, "signal_metadata", metadata)
        setattr(ticket, "signal_score", metadata["signal_score"])
        return ticket

    def _hn_severity(self, points: int, comments: int) -> str:
        if points > 100 or comments > 50:
            return "P1"
        if points > 30 or comments > 15:
            return "P2"
        return "P3"

    def _so_severity(self, views: int, score: int) -> str:
        if views > 1000 or score > 10:
            return "P1"
        if views > 300 or score > 3:
            return "P2"
        return "P3"

    def _score_hn(self, points: int, comments: int) -> float:
        return min(1.0, (points / 120.0) + (comments / 80.0))

    def _score_so(self, views: int, score: int) -> float:
        return min(1.0, (views / 1200.0) + (score / 15.0))

    def _clean_html(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()
