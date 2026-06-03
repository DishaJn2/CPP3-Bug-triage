import asyncio
import json
import math
import os
import time
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry

log = structlog.get_logger()

MAX_REACT_ITERS = 4

SYSTEM_PROMPT = """You are an elite triage assistant in a strict
ReAct loop. Find the most relevant troubleshooting runbooks or
workarounds for the reported bug.

You have access to:
Action: search_confluence
Action Input: <2-4 word architectural concept query>

Rules:
- Think abstractly about the UNDERLYING engineering concept
- Strip ALL line numbers, hex addresses, thread IDs
- Examples of good queries:
  "CTE optimizer incorrect results"
  "consumer group rebalancing timeout"
  "OOMKilled memory limit configuration"
  "StorageController concurrent allocation"
  "WebGL context lost recovery"
- If first search returns nothing, try a broader concept
- Maximum 4 searches total

Output format:
Thought: <reasoning>
Action: search_confluence
Action Input: <query>

OR when done:
Final Answer: [{"title":"...","url":"...","excerpt":"...","relevance":"high|medium|low"}]

Always provide Final Answer as JSON array even if empty."""


class EnrichmentAgent(BaseAgent):
    step_name = "enrichment"

    async def run(self, context: dict) -> dict:
        primary = context.get("primary_ticket") or {}

        # Use full ticket data — NOT keywords (they are gone)
        title         = (primary.get("title") or "")
        component     = (primary.get("component") or "")
        description   = (primary.get("description") or "")[:400]
        error_excerpt = (primary.get("error_excerpt") or "")[:300]
        status        = (primary.get("status") or "")

        groq_api_key   = os.getenv("GROQ_API_KEY", "")
        # Use fast 8b model for enrichment as per spec
        enrichment_model = "llama-3.1-8b-instant"

        kb_articles = []

        if not groq_api_key:
            context["kb_articles"] = []
            return context

        client = AsyncGroq(api_key=groq_api_key)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Find knowledge base articles for this bug:\n"
                    f"Title: {title}\n"
                    f"Component: {component}\n"
                    f"Description: {description}\n"
                    f"Error: {error_excerpt}\n\n"
                    f"Search for the underlying engineering concept "
                    f"not the literal error words."
                ),
            },
        ]

        for iteration in range(MAX_REACT_ITERS):
            try:
                resp = await client.chat.completions.create(
                    model=enrichment_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=512,
                )
                reply = (resp.choices[0].message.content or "")
                messages.append(
                    {"role": "assistant", "content": reply})

                if "Final Answer:" in reply:
                    raw = reply.split("Final Answer:")[-1].strip()
                    raw = raw.strip("```json").strip("```").strip()
                    try:
                        parsed = json.loads(raw)
                        kb_articles = (parsed
                                       if isinstance(parsed, list)
                                       else [])
                    except Exception:
                        kb_articles = []
                    break

                if ("Action: search_confluence" in reply
                        and "Action Input:" in reply):
                    query = (reply.split("Action Input:")[-1]
                             .strip()
                             .split("\n")[0]
                             .strip()
                             .strip('"\''))

                    log.info("Enrichment searching",
                             query=query,
                             iteration=iteration)

                    results = await self._search_confluence(
                        query, context)

                    if not results:
                        obs = (
                            "No results found. Try a broader "
                            "architectural concept — remove "
                            "specific version numbers or "
                            "class paths.")
                    else:
                        obs = json.dumps(results)

                    messages.append({
                        "role": "user",
                        "content": f"Observation: {obs}",
                    })

            except Exception as e:
                log.warning("Enrichment iteration failed",
                            error=str(e),
                            iteration=iteration)
                break

        context["kb_articles"] = kb_articles[:5]
        log.info("Enrichment complete",
                 articles=len(kb_articles))
        return context

    async def _search_confluence(self, query: str,
                                  context: dict = None) -> list[dict]:
        try:
            try:
                # Primary: use get_all_by_type
                connectors = await ConnectorRegistry.get_all_by_type(
                    "confluence")
            except AttributeError:
                # Fallback: filter manually from get_all_enabled
                all_c = await ConnectorRegistry.get_all_enabled()
                connectors = [
                    c for c in all_c
                    if (c.system_type or "").lower() == "confluence"
                    or "confluence" in type(c).__name__.lower()
                ]

            if not connectors:
                log.warning("No confluence connectors found",
                            hint="Check registry SYSTEM_TYPE_TO_CLASS "
                                 "has confluence key")
                return []

            log.info("Enrichment: confluence connectors loaded",
                     count=len(connectors),
                     sources=[c.source_id for c in connectors])

            all_results = []
            seen_titles: set = set()

            primary = (context or {}).get("primary_ticket") or {}
            bug_text = (
                f"{primary.get('title','')} "
                f"{primary.get('component','')} "
                f"{primary.get('error_excerpt','')[:200]}"
            ).strip()

            for connector in connectors:
                try:
                    results = await asyncio.wait_for(
                        connector.search(query, max_results=5),
                        timeout=15.0)

                    for t in results:
                        if t.title in seen_titles:
                            continue
                        seen_titles.add(t.title)

                        article_text = t.description or ""
                        chunks = self._slice_and_score(
                            article_text, bug_text, 0)
                        excerpt = " ... ".join(chunks)[:400]

                        # Use the connector's own base_url
                        # for the article link
                        article_url = self._make_article_url(
                            connector, t.url)

                        all_results.append({
                            "title":     t.title,
                            "url":       article_url,
                            "excerpt":   excerpt,
                            "relevance": "medium",
                            "source":    connector.source_id,
                        })

                    log.info("Confluence result",
                             source=connector.source_id,
                             query=query,
                             found=len(results))

                except asyncio.TimeoutError:
                    log.warning("Confluence timeout",
                                source=connector.source_id)
                except Exception as e:
                    log.warning("Confluence error",
                                source=connector.source_id,
                                error=str(e))

            # Sort: articles with query words in title first
            q_lower = query.lower()
            all_results.sort(
                key=lambda x: q_lower in x.get(
                    "title", "").lower(),
                reverse=True)

            return all_results[:5]

        except Exception as e:
            log.warning("_search_confluence error", error=str(e))
            return []

    def _make_article_url(self, connector, raw_url: str) -> str:
        """
        Build correct article URL using the connector's
        own base_url — not a hardcoded domain.
        Sanitize localhost/mock domains only.
        """
        bad_domains = [
            "confluence.example.com",
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "example.com",
        ]

        # If it is already a good absolute URL, return it
        if raw_url and raw_url.startswith("http"):
            for bad in bad_domains:
                if bad in raw_url:
                    break
            else:
                return raw_url  # URL is clean, use as-is

        # Extract path and rebuild using connector's base_url
        base = connector.base_url.rstrip("/")
        if not raw_url:
            return base

        path = raw_url
        if raw_url.startswith("http"):
            try:
                from urllib.parse import urlparse
                path = urlparse(raw_url).path
            except Exception:
                path = "/"

        if not path.startswith("/"):
            path = "/" + path

        # Remove duplicate /wiki if present
        if "/confluence" in base and path.startswith("/wiki"):
            return f"{base}{path[5:]}"
        return f"{base}{path}"

    def _slice_and_score(self, article_text: str,
                          bug_text: str,
                          last_modified_epoch: float = 0
                          ) -> list[str]:
        paragraphs = [
            p.strip()
            for p in article_text.split("\n\n")
            if len(p.strip()) > 30
        ]
        if not paragraphs:
            return [article_text[:500]]

        if last_modified_epoch and last_modified_epoch > 0:
            delta = ((time.time() - last_modified_epoch)
                     / (365 * 24 * 3600))
            decay = math.exp(-0.15 * delta)
        else:
            decay = 0.9

        bug_words = set(bug_text.lower().split())
        scored = []
        for chunk in paragraphs:
            cwords = set(chunk.lower().split())
            if not cwords:
                continue
            overlap = (len(bug_words & cwords)
                       / len(bug_words | cwords))
            adjusted = overlap * decay
            has_signal = any(
                kw in chunk.lower()
                for kw in ("workaround", "patch", "fix",
                           "resolution", "solution", "error",
                           "exception", "failed"))
            if adjusted >= 0.08 or has_signal:
                scored.append((adjusted, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c in scored[:3]]
        return top if top else [article_text[:500]]
