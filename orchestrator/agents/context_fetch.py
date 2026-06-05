import asyncio
import dataclasses
import re
import structlog

from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry

log = structlog.get_logger()

MAX_DESC = 8000
MAX_ERR  = 3000


class ContextFetchAgent(BaseAgent):
    step_name = "context_fetch"

    async def run(self, context: dict) -> dict:
        bug_id    = context.get("bug_id", "")
        source_id = context.get("source_id", "")

        log.info("ContextFetch start",
                 bug_id=bug_id, source_id=source_id)

        connector = await self._resolve_connector(source_id, bug_id)

        if connector is None:
            log.error("ContextFetch: no connector found",
                      bug_id=bug_id, source_id=source_id)
            self._add_error(context,
                f"No connector resolved for bug_id={bug_id}")
            context["primary_ticket"]  = None
            context["bug_context"]     = self._empty_bug_context(
                bug_id=bug_id,
                source_id=source_id,
                error=context.get("errors", {}).get(self.step_name, ""),
            )
            context["linked_items"]    = []
            context["customer_cases"]  = []
            context["source_references"] = []
            context["components"]      = []
            return context

        log.info("ContextFetch: connector resolved",
                 connector=connector.source_id,
                 ctype=type(connector).__name__,
                 ticket_id=bug_id,
                 source_id=source_id)

        # ── Fetch primary ticket ──────────────────────────────────
        ticket = None
        try:
            ticket = await asyncio.wait_for(
                connector.get_ticket(bug_id), timeout=15.0)
        except asyncio.TimeoutError:
            log.error("ContextFetch: GET timed out", bug_id=bug_id)
            self._add_error(context, f"Timeout fetching {bug_id}")
        except Exception as e:
            log.error("ContextFetch: GET error",
                      bug_id=bug_id, err=str(e))
            self._add_error(context, str(e))

        if ticket is None:
            log.error("ContextFetch: ticket is None",
                      bug_id=bug_id, connector=connector.source_id)
            context["primary_ticket"]  = None
            context["bug_context"]     = self._empty_bug_context(
                bug_id=bug_id,
                source_id=connector.source_id,
                error=context.get("errors", {}).get(
                    self.step_name,
                    f"No ticket returned for {bug_id}",
                ),
            )
            context["linked_items"]    = []
            context["customer_cases"]  = []
            context["source_references"] = []
            context["components"]      = []
            return context

        log.info("ContextFetch: ticket OK",
                 id=ticket.ticket_id,
                 title=(ticket.title or "")[:60],
                 severity=ticket.severity,
                 component=ticket.component,
                 selected_connector_source_id=connector.source_id,
                 get_ticket_returned_title=bool(ticket.title))

        # ── Truncate oversized fields ─────────────────────────────
        desc = ticket.description or ""
        if len(desc) > MAX_DESC:
            lines = desc.splitlines()
            desc = ("\n".join(lines[:100])
                    + "\n\n[...truncated...]\n\n"
                    + "\n".join(lines[-100:]))

        err = ticket.error_excerpt or ""
        if len(err) > MAX_ERR:
            lines = err.splitlines()
            err = ("\n".join(lines[:50])
                   + "\n\n[...truncated...]\n\n"
                   + "\n".join(lines[-50:]))

        # ── Co-reference extraction from ticket text ──────────────
        # Deterministically extract explicit cross-system references
        # from the ticket body before doing any LLM search
        raw_text = f"{ticket.title} {desc} {err}"
        co_refs = self._extract_co_references(raw_text)
        if co_refs:
            log.info("ContextFetch: co-refs found",
                     count=len(co_refs), refs=co_refs[:3])

        # ── Fetch linked items ────────────────────────────────────
        linked_items = []
        try:
            linked_items = await asyncio.wait_for(
                connector.get_linked_items(bug_id),
                timeout=8.0)
            log.info("ContextFetch: linked items",
                     count=len(linked_items))
        except Exception as e:
            log.warning("ContextFetch: linked_items failed",
                        err=str(e))

        # ── Fetch customer cases ──────────────────────────────────
        customer_cases = []
        try:
            portals = await ConnectorRegistry.get_all_by_type(
                "customer_portal")
            if portals:
                q = (f"{ticket.title} "
                     f"{ticket.component or ''}").strip()
                gathered = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            portal.search(q, max_results=3),
                            timeout=5.0)
                        for portal in portals
                    ],
                    return_exceptions=True,
                )
                results = []
                for item in gathered:
                    if isinstance(item, Exception):
                        continue
                    results.extend(item)
                customer_cases = [
                    {
                        "case_id":  t.ticket_id,
                        "customer": t.reporter,
                        "title":    t.title,
                        "severity": t.severity,
                        "impact":   t.description,
                        "status":   t.status,
                    }
                    for t in results
                ]
                log.info("ContextFetch: customer cases",
                         count=len(customer_cases),
                         portals=len(portals))
        except Exception as e:
            log.warning("ContextFetch: portal failed", err=str(e))

        # ── Build context dict ────────────────────────────────────
        ticket_dict = self._normalize_ticket(
            ticket=ticket,
            connector=connector,
            description=desc,
            error_excerpt=err,
            linked_items=linked_items,
        )
        source_references = self._build_source_references(
            ticket=ticket,
            linked_items=linked_items,
            co_refs=co_refs,
        )
        bug_context = self._build_bug_context(
            ticket=ticket_dict,
            customer_cases=customer_cases,
            source_references=source_references,
            errors=context.get("errors") or {},
        )

        context["primary_ticket"]  = ticket_dict
        context["bug_context"]     = bug_context
        context["linked_items"]    = linked_items
        context["co_references"]   = co_refs
        context["customer_cases"]  = customer_cases
        context["source_references"] = source_references
        context["components"]      = (
            [ticket.component] if ticket.component else [])
        context["source_id"]       = connector.source_id
        context["direct_reference_links"] = getattr(ticket, "direct_reference_links", [])

        log.info("ContextFetch complete",
                 bug_id=bug_id,
                 has_ticket=True,
                 linked=len(linked_items),
                 cases=len(customer_cases),
                 co_refs=len(co_refs))
        return context

    # ── Connector resolution (longest-prefix-first) ───────────────
    async def _resolve_connector(self, source_id: str, bug_id: str):
        # 1. Direct source_id match
        if source_id:
            try:
                c = await ConnectorRegistry.get(source_id)
                if c:
                    return c
            except Exception:
                pass

        # 2. Registry-owned ticket prefix match
        try:
            connector = await ConnectorRegistry.get_by_ticket_id(bug_id)
            if connector:
                return connector
        except Exception as e:
            log.error("ContextFetch: registry failed", err=str(e))
            return None

        return None

    def _normalize_ticket(self,
                          ticket,
                          connector,
                          description: str,
                          error_excerpt: str,
                          linked_items: list) -> dict:
        ticket_dict = dataclasses.asdict(ticket)
        ticket_dict["description"] = description or ""
        ticket_dict["error_excerpt"] = error_excerpt or ""
        ticket_dict["steps_to_reproduce"] = (
            ticket_dict.get("steps_to_reproduce")
            or getattr(ticket, "steps_to_reproduce", "")
            or ""
        )
        ticket_dict["customer_impact"] = (
            ticket_dict.get("customer_impact")
            or getattr(ticket, "customer_impact", "")
            or ""
        )
        ticket_dict["recent_comments"] = self._recent_comments(
            ticket_dict.get("comments") or [])
        ticket_dict["linked_items"] = linked_items or (
            ticket_dict.get("linked_items") or [])
        ticket_dict["source_id"] = connector.source_id
        ticket_dict["source"] = (
            ticket_dict.get("system_type") or connector.system_type)
        ticket_dict["system_type"] = (
            ticket_dict.get("system_type") or connector.system_type)
        ticket_dict["source_name"] = getattr(
            connector, "display_name", connector.source_id)
        ticket_dict["id"] = ticket_dict.get("ticket_id", "")
        return ticket_dict

    def _build_bug_context(self,
                           ticket: dict,
                           customer_cases: list,
                           source_references: list,
                           errors: dict) -> dict:
        return {
            "ticket_id": ticket.get("ticket_id", ""),
            "source_id": ticket.get("source_id", ""),
            "source": ticket.get("source", ""),
            "source_name": ticket.get("source_name", ""),
            "system_type": ticket.get("system_type", ""),
            "title": ticket.get("title", ""),
            "severity": ticket.get("severity", ""),
            "status": ticket.get("status", ""),
            "component": ticket.get("component", ""),
            "assignee": ticket.get("assignee", ""),
            "reporter": ticket.get("reporter", ""),
            "created_at": ticket.get("created_at", ""),
            "updated_at": ticket.get("updated_at", ""),
            "description": ticket.get("description", ""),
            "steps_to_reproduce": ticket.get("steps_to_reproduce", ""),
            "error_excerpt": ticket.get("error_excerpt", ""),
            "customer_impact": ticket.get("customer_impact", ""),
            "recent_comments": ticket.get("recent_comments", []),
            "comments": ticket.get("comments", []),
            "linked_items": ticket.get("linked_items", []),
            "url": ticket.get("url", ""),
            "customer_cases": customer_cases or [],
            "source_references": source_references or [],
            "errors": errors or {},
        }

    def _empty_bug_context(self,
                           bug_id: str,
                           source_id: str = "",
                           error: str = "") -> dict:
        return {
            "ticket_id": bug_id or "",
            "source_id": source_id or "",
            "source": "",
            "source_name": "",
            "system_type": "",
            "title": "",
            "severity": "",
            "status": "",
            "component": "",
            "assignee": "",
            "reporter": "",
            "created_at": "",
            "updated_at": "",
            "description": "",
            "steps_to_reproduce": "",
            "error_excerpt": "",
            "customer_impact": "",
            "recent_comments": [],
            "comments": [],
            "linked_items": [],
            "url": "",
            "customer_cases": [],
            "source_references": [],
            "errors": {self.step_name: error} if error else {},
        }

    def _recent_comments(self, comments: list) -> list:
        if not isinstance(comments, list):
            return []
        return comments[-3:]

    def _build_source_references(self,
                                 ticket,
                                 linked_items: list,
                                 co_refs: list) -> list:
        references = []
        for item in linked_items or []:
            references.append({
                "type": item.get("type") or item.get("relationship") or "linked_item",
                "raw_id": item.get("raw_id") or item.get("ticket_id") or item.get("id") or "",
                "source": item.get("source") or item.get("system_type") or "",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
            })
        for item in getattr(ticket, "direct_reference_links", []) or []:
            references.append({
                "type": item.get("type") or item.get("relationship") or "direct_reference",
                "raw_id": item.get("raw_id") or item.get("ticket_id") or item.get("id") or "",
                "source": item.get("source") or item.get("system_type") or "",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
            })
        for item in co_refs or []:
            references.append({
                "type": item.get("type") or "co_reference",
                "raw_id": item.get("raw_id", ""),
                "source": item.get("source", ""),
                "title": "",
                "url": item.get("url", ""),
            })
        return references

    # ── Deterministic co-reference extractor ─────────────────────
    def _extract_co_references(self, text: str) -> list:
        refs = []
        words = text.replace("#", " PR-").replace(":", " ").split()
        for word in words:
            w = word.strip(".,()[]")
            # JIRA format: PROJECT-12345
            if "-" in w:
                parts = w.split("-")
                if (len(parts) == 2
                        and parts[0].isupper()
                        and len(parts[0]) >= 2
                        and parts[1].isdigit()
                        and len(parts[1]) >= 3):
                    refs.append({
                        "raw_id": w,
                        "source": "JIRA",
                        "type":   "co_reference"
                    })
            # GitHub PR/issue
            if w.upper().startswith(("PR-", "GH-")):
                parts = w.split("-")
                if len(parts) == 2 and parts[1].isdigit():
                    refs.append({
                        "raw_id": parts[1],
                        "source": "GitHub",
                        "type":   "co_reference"
                    })
        # Remove duplicates
        seen = set()
        unique = []
        for r in refs:
            k = r["raw_id"]
            if k not in seen:
                seen.add(k)
                unique.append(r)
        return unique
