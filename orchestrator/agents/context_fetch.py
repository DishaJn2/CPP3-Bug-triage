import asyncio
import dataclasses
import os
import re
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry

log = structlog.get_logger()


class ContextFetchAgent(BaseAgent):
    step_name = "context_fetch"

    async def run(self, context: dict) -> dict:
        bug_id   = context.get("bug_id", "")
        source_id = context.get("source_id", "")

        print(f"[ContextFetch] Starting: bug_id={bug_id} source_id={source_id}", flush=True)

        all_connectors = await ConnectorRegistry.get_all_enabled()
        print(f"[ContextFetch] Connectors available: {[c.source_id for c in all_connectors]}", flush=True)

        connector = None
        for c in all_connectors:
            if c.source_id == source_id:
                connector = c
                break

        if not connector:
            print(f"[ContextFetch] No connector for {source_id}, trying prefix match", flush=True)
            for c in all_connectors:
                if c.ticket_prefix and bug_id.upper().startswith(c.ticket_prefix.upper() + "-"):
                    connector = c
                    source_id = c.source_id
                    context["source_id"] = source_id
                    break

        if not connector and all_connectors:
            # Last resort: first connector that isn't a pure KB/portal type
            for c in all_connectors:
                if c.system_type not in ("confluence", "customer_portal"):
                    connector = c
                    source_id = c.source_id
                    context["source_id"] = source_id
                    print(f"[ContextFetch] Fallback to: {source_id}", flush=True)
                    break

        if not connector:
            print("[ContextFetch] No connector available", flush=True)
            context.setdefault("errors", {})["context_fetch"] = "No connector available"
            context["primary_ticket"] = None
            context["keywords"] = []
            context["components"] = []
            context["customer_cases"] = []
            return context

        print(f"[ContextFetch] Using connector: {connector.source_id}", flush=True)

        # Fetch ticket with 15 s timeout
        try:
            ticket = await asyncio.wait_for(connector.get(bug_id), timeout=15.0)
        except asyncio.TimeoutError:
            print(f"[ContextFetch] Timeout fetching {bug_id}", flush=True)
            context.setdefault("errors", {})["context_fetch"] = f"Timeout fetching {bug_id}"
            ticket = None
        except Exception as e:
            print(f"[ContextFetch] Error fetching {bug_id}: {e}", flush=True)
            context.setdefault("errors", {})["context_fetch"] = str(e)
            ticket = None

        if not ticket:
            print(f"[ContextFetch] Ticket {bug_id} not found in {source_id}", flush=True)
            context.setdefault("errors", {})["context_fetch"] = f"Ticket {bug_id} not found"
            context["primary_ticket"] = None
            context["keywords"] = []
            context["components"] = []
            context["customer_cases"] = []
            return context

        print(f"[ContextFetch] Got ticket: {ticket.title[:60]}", flush=True)

        title         = ticket.title or ""
        description   = ticket.description or ""
        error_excerpt = ticket.error_excerpt or ""

        # Fetch linked items with timeout
        linked_items = []
        try:
            linked = await asyncio.wait_for(connector.get_linked_items(bug_id), timeout=8.0)
            linked_items = linked or []
            if linked_items:
                print(f"[ContextFetch] Found {len(linked_items)} linked items", flush=True)
        except Exception as e:
            print(f"[ContextFetch] Linked items failed: {e}", flush=True)

        # LLM keyword extraction
        keywords = []
        try:
            groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            resp = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": (
                            "Extract the 10 most important technical keywords from this bug report.\n"
                            "Focus on: class names, method names, exception types, component names, API names.\n"
                            "Avoid generic words like: error, bug, issue, fail, null, exception, problem.\n\n"
                            f"Bug title: {title}\n"
                            f"Component: {ticket.component or 'unknown'}\n"
                            f"Description: {description[:400]}\n"
                            f"Error: {error_excerpt[:200]}\n\n"
                            "Return ONLY a comma-separated list. No explanation.\n"
                            "Example: NormalizeCTEIds, InlineCTE, CTERelationRefs, optimizer, WithCTE"
                        ),
                    }],
                    max_tokens=80,
                    temperature=0.0,
                ),
                timeout=10.0,
            )
            raw = resp.choices[0].message.content.strip()
            keywords = [k.strip() for k in raw.split(",") if k.strip() and len(k.strip()) > 2][:10]
            print(f"[ContextFetch] LLM keywords: {keywords}", flush=True)
        except Exception as e:
            print(f"[ContextFetch] LLM keyword extraction failed: {e}, using regex", flush=True)
            stop = {
                "the","a","an","is","in","on","at","to","for","of","and","or",
                "with","this","that","was","has","are","not","bug","error","issue",
                "fail","failed","null","new","java","python","when","using","after",
                "during","while","cannot","does","have","been","from","will",
                "github","apache","spark","kafka","mozilla",
            }
            words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", f"{title} {description} {error_excerpt}")
            seen: set = set()
            for w in words:
                wl = w.lower()
                if wl not in stop and wl not in seen:
                    seen.add(wl)
                    keywords.append(wl)
                if len(keywords) >= 10:
                    break

        components = [ticket.component] if ticket.component else []

        ticket_dict = dataclasses.asdict(ticket)
        if linked_items:
            ticket_dict["linked_items"] = linked_items

        # Fetch related customer cases from HPE Customer Portal
        customer_cases = []
        try:
            portal_connector = await ConnectorRegistry.get_by_type("customer_portal")
            if portal_connector and keywords:
                customer_cases = await asyncio.wait_for(
                    portal_connector.get_cases_for_bug(keywords[:5]),
                    timeout=8.0,
                )
                print(f"[ContextFetch] Found {len(customer_cases)} customer cases", flush=True)
        except Exception:
            customer_cases = []

        context["primary_ticket"]  = ticket_dict
        context["keywords"]        = keywords
        context["components"]      = components
        context["source_id"]       = source_id
        context["customer_cases"]  = customer_cases

        print(f"[ContextFetch] Complete. Keywords: {keywords[:5]}", flush=True)
        return context
