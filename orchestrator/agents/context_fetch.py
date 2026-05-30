import dataclasses
import re
from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry


class ContextFetchAgent(BaseAgent):
    step_name = "context_fetch"

    async def run(self, context: dict) -> dict:
        bug_id = context.get("bug_id", "")
        source_id = context.get("source_id", "")

        try:
            connector = await ConnectorRegistry.get_connector(source_id)
            if not connector:
                connectors = await ConnectorRegistry.get_all_enabled()
                if connectors:
                    connector = connectors[0]
                    source_id = connector.source_id

            if not connector:
                context["primary_ticket"] = None
                context["keywords"] = []
                context["components"] = []
                return context

            ticket = await connector.get(bug_id)

            if not ticket:
                context["primary_ticket"] = None
                context["keywords"] = []
                context["components"] = []
                return context

            ticket_dict = dataclasses.asdict(ticket)

            stop_words = {
                "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
                "and", "or", "with", "this", "that", "was", "has", "are", "not",
                "bug", "error", "issue", "fail", "failed", "when", "using",
                "after", "during", "while", "cannot", "does", "have", "been",
                "from", "will", "would", "could", "should", "but", "its", "it",
                "as", "by", "be", "if", "no", "null", "new", "java", "python",
            }
            text = f"{ticket.title} {ticket.description or ''} {ticket.error_excerpt or ''}"
            words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9]{3,}\b', text)
            keywords = []
            seen = set()
            for w in words:
                wl = w.lower()
                if wl not in stop_words and wl not in seen:
                    seen.add(wl)
                    keywords.append(wl)
                if len(keywords) >= 15:
                    break

            components = [ticket.component] if ticket.component else []

            context["primary_ticket"] = ticket_dict
            context["keywords"] = keywords
            context["components"] = components
            context["source_id"] = source_id

        except Exception:
            context["primary_ticket"] = None
            context["keywords"] = []
            context["components"] = []

        return context
