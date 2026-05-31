import asyncio
import os
import re
import dataclasses
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from orchestrator.connectors.registry import ConnectorRegistry

log = structlog.get_logger()


class ContextFetchAgent(BaseAgent):
    step_name = "context_fetch"

    async def run(self, context: dict) -> dict:
        bug_id = context.get("bug_id", "")
        source_id = context.get("source_id", "")

        all_connectors = await ConnectorRegistry.get_all_enabled()
        print(f"[ContextFetch] Available connectors: {[c.source_id for c in all_connectors]}", flush=True)

        connector = None
        for c in all_connectors:
            if c.source_id == source_id:
                connector = c
                break

        if not connector and bug_id:
            prefix = bug_id.split("-")[0].upper() if "-" in bug_id else ""
            for c in all_connectors:
                if c.ticket_prefix and c.ticket_prefix.upper() == prefix:
                    connector = c
                    source_id = c.source_id
                    context["source_id"] = source_id
                    break

        if not connector and all_connectors:
            connector = all_connectors[0]
            source_id = connector.source_id
            context["source_id"] = source_id

        if not connector:
            print(f"[ContextFetch] No connector found for {source_id}", flush=True)
            context["primary_ticket"] = None
            context["keywords"] = []
            context["components"] = []
            return context

        print(f"[ContextFetch] Fetching bug {bug_id} from {connector.source_id}", flush=True)

        try:
            ticket = await asyncio.wait_for(connector.get(bug_id), timeout=15.0)
        except asyncio.TimeoutError:
            print(f"[ContextFetch] Timeout fetching {bug_id}", flush=True)
            ticket = None
        except Exception as e:
            print(f"[ContextFetch] Error fetching {bug_id}: {e}", flush=True)
            ticket = None

        if not ticket:
            print(f"[ContextFetch] Ticket {bug_id} not found", flush=True)
            context["primary_ticket"] = None
            context["keywords"] = []
            context["components"] = []
            return context

        ticket_dict = dataclasses.asdict(ticket)
        print(f"[ContextFetch] Got ticket: {ticket.title[:60]}", flush=True)

        try:
            linked = await asyncio.wait_for(
                connector.get_linked_items(bug_id),
                timeout=8.0,
            )
            if linked:
                ticket_dict["linked_items"] = linked[:5]
                print(f"[ContextFetch] Found {len(linked)} linked items", flush=True)
            else:
                ticket_dict["linked_items"] = []
        except Exception as e:
            print(f"[ContextFetch] Linked items fetch failed: {e}", flush=True)
            ticket_dict["linked_items"] = []

        keywords = []
        try:
            groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

            text = f"""Title: {ticket.title}
Component: {ticket.component or 'unknown'}
Description: {(ticket.description or '')[:500]}
Error: {(ticket.error_excerpt or '')[:200]}"""

            resp = await groq_client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": f"""Extract the 10 most important technical keywords from this bug report.
Focus on: class names, method names, exception types, component names, technical concepts.
Avoid generic words like: error, bug, issue, fail, null, exception.

{text}

Return ONLY a comma-separated list of keywords. Nothing else.
Example: NormalizeCTEIds, InlineCTE, optimizer, CTE, nested, WithCTE""",
                }],
                max_tokens=80,
                temperature=0.0,
            )
            raw_keywords = resp.choices[0].message.content.strip()
            keywords = [k.strip() for k in raw_keywords.split(",") if k.strip() and len(k.strip()) > 2][:10]
            print(f"[ContextFetch] LLM keywords: {keywords}", flush=True)
        except Exception as e:
            print(f"[ContextFetch] LLM keyword extraction failed: {e}, using fallback", flush=True)
            stop_words = {
                "the", "a", "an", "is", "in", "on", "at", "to", "for", "of", "and", "or",
                "with", "this", "that", "was", "has", "are", "not", "bug", "error", "issue",
                "fail", "failed", "null", "new", "java", "python", "when", "using", "after",
            }
            raw = f"{ticket.title} {ticket.description or ''} {ticket.error_excerpt or ''}"
            words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9]{3,}\b', raw)
            seen = set()
            for w in words:
                wl = w.lower()
                if wl not in stop_words and wl not in seen:
                    seen.add(wl)
                    keywords.append(wl)
                if len(keywords) >= 10:
                    break

        components = [ticket.component] if ticket.component else []

        context["primary_ticket"] = ticket_dict
        context["keywords"] = keywords
        context["components"] = components
        context["source_id"] = source_id
        context["customer_cases"] = []
        return context
