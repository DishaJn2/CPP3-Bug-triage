import asyncio
import os
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry

log = structlog.get_logger()


class EnrichmentAgent(BaseAgent):
    step_name = "enrichment"

    async def run(self, context: dict) -> dict:
        primary_ticket = context.get("primary_ticket", {})
        keywords = context.get("keywords", [])
        components = context.get("components", [])
        source_id = context.get("source_id", "")

        title = (primary_ticket.get("title") or "") if primary_ticket else ""

        print(f"[Enrichment] Starting for: {title[:60]}", flush=True)

        conf_connector = await ConnectorRegistry.get_by_type("confluence")

        if not conf_connector:
            print("[Enrichment] No Confluence connector found, using DB fallback", flush=True)
            kb_articles = await self._db_fallback(keywords, source_id)
            context["kb_articles"] = kb_articles
            context["kb_reasoning"] = f"Found {len(kb_articles)} relevant articles."
            context["customer_cases"] = []
            return context

        # Build 3 ReAct-style search rounds
        stop = {
            "the", "a", "an", "is", "in", "on", "at", "to", "for", "of", "and", "or",
            "failure", "error", "issue", "bug", "not", "with", "this", "that",
            "was", "has", "are", "does",
        }
        title_words = [w for w in title.split() if len(w) > 4 and w.lower() not in stop][:3]

        search_rounds = []
        if keywords:
            search_rounds.append((" ".join(keywords[:3]), "keywords"))
        if components:
            search_rounds.append((components[0], "component"))
        if title_words:
            search_rounds.append((" ".join(title_words), "title_terms"))

        all_articles: dict = {}

        for query, round_name in search_rounds:
            if not query.strip():
                continue

            print(
                f"[Enrichment] Round {round_name}: searching Confluence for '{query}'",
                flush=True,
            )

            try:
                results = await asyncio.wait_for(
                    conf_connector.search(query, max_results=3),
                    timeout=10.0,
                )
                print(
                    f"[Enrichment] Round {round_name}: got {len(results)} results",
                    flush=True,
                )

                for ticket in results:
                    if ticket.ticket_id in all_articles:
                        continue

                    content_lower = (ticket.title + " " + ticket.description).lower()
                    keyword_hits = sum(
                        1 for k in keywords[:8] if k.lower() in content_lower
                    )

                    if keyword_hits >= 3:
                        relevance = "High"
                    elif keyword_hits >= 1:
                        relevance = "Medium"
                    else:
                        relevance = "Low"

                    all_articles[ticket.ticket_id] = {
                        "title": ticket.title,
                        "url": ticket.url or "#",
                        "excerpt": ticket.description[:250] if ticket.description else "",
                        "relevance": relevance,
                        "space": "Confluence — HPE Engineering KB",
                        "component": ticket.component or "",
                        "last_modified": ticket.updated_at or "",
                        "keyword_hits": keyword_hits,
                        "is_answered": True,
                        "score": keyword_hits + 3,
                    }

            except asyncio.TimeoutError:
                print(f"[Enrichment] Round {round_name}: Confluence timeout", flush=True)
            except Exception as e:
                print(f"[Enrichment] Round {round_name}: error {e}", flush=True)

        kb_articles = list(all_articles.values())
        print(f"[Enrichment] Found {len(kb_articles)} unique Confluence articles", flush=True)

        if not kb_articles:
            print("[Enrichment] Confluence returned nothing, using DB fallback", flush=True)
            kb_articles = await self._db_fallback(keywords, source_id)

        relevance_order = {"High": 0, "Medium": 1, "Low": 2}
        kb_articles.sort(
            key=lambda x: (
                relevance_order.get(x.get("relevance", "Low"), 2),
                -x.get("keyword_hits", 0),
            )
        )
        kb_articles = kb_articles[:4]

        kb_reasoning = ""
        try:
            groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

            articles_text = (
                "\n".join(
                    f"- {a['title']} ({a['relevance']} relevance): {a['excerpt'][:80]}"
                    for a in kb_articles
                )
                if kb_articles
                else "No Confluence articles found."
            )

            resp = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Bug: {title}\n"
                                f"Keywords: {', '.join(keywords[:5])}\n"
                                f"Component: {components[0] if components else 'Unknown'}\n\n"
                                f"Confluence KB articles found:\n{articles_text}\n\n"
                                "In exactly 2 sentences, tell the engineer which article is most "
                                "relevant and what specific section to look at. Be technical and precise."
                            ),
                        }
                    ],
                    max_tokens=120,
                    temperature=0.3,
                ),
                timeout=10.0,
            )
            kb_reasoning = resp.choices[0].message.content.strip()
        except Exception as e:
            kb_reasoning = f"Found {len(kb_articles)} relevant Confluence articles."

        context["kb_articles"] = kb_articles
        context["kb_reasoning"] = kb_reasoning
        context["customer_cases"] = []
        return context

    async def _db_fallback(self, keywords: list, source_id: str) -> list:
        """Fall back to local kb_articles DB if Confluence is unavailable."""
        try:
            from ..db.session import AsyncSessionLocal
            from ..db.repositories.kb_articles import search_kb_articles

            query = " ".join(keywords[:3]) if keywords else ""
            if not query:
                return []
            async with AsyncSessionLocal() as db:
                articles = await search_kb_articles(db, query, limit=3)
            return [
                {
                    "title": a.title,
                    "url": a.url,
                    "excerpt": a.content[:200],
                    "relevance": "Medium",
                    "space": a.space_key,
                    "component": a.component or "",
                    "last_modified": a.last_modified,
                    "keyword_hits": 1,
                    "is_answered": True,
                    "score": 3,
                }
                for a in articles
            ]
        except Exception:
            return []
