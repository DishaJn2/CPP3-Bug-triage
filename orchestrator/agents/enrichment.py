import os
import structlog
from groq import AsyncGroq
from .base import BaseAgent

log = structlog.get_logger()


class EnrichmentAgent(BaseAgent):
    step_name = "enrichment"

    async def run(self, context: dict) -> dict:
        primary_ticket = context.get("primary_ticket", {})
        keywords = context.get("keywords", [])
        components = context.get("components", [])
        source_id = context.get("source_id", "")

        title = primary_ticket.get("title", "") if primary_ticket else ""
        description = (primary_ticket.get("description") or "")[:300]
        error_excerpt = (primary_ticket.get("error_excerpt") or "")[:200]

        print(f"[Enrichment] Starting for: {title[:60]}", flush=True)

        from orchestrator.db.session import AsyncSessionLocal
        from orchestrator.db.repositories.kb_articles import search_kb_articles

        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        all_articles = {}  # id -> article dict
        react_trace = []

        # Round 1: search by top LLM-extracted keywords
        query1 = " ".join(keywords[:3]) if keywords else title[:50]
        react_trace.append(f"Thought: Search KB for technical keywords: '{query1}'")
        try:
            async with AsyncSessionLocal() as db:
                results1 = await search_kb_articles(db, query1, limit=3)
            react_trace.append(f"Observation: Found {len(results1)} articles")
            for a in results1:
                if a.id not in all_articles:
                    all_articles[a.id] = self._format_article(a, keywords)
        except Exception as e:
            react_trace.append(f"Error: {str(e)[:50]}")

        # Round 2: search by component name
        if components:
            query2 = components[0]
            react_trace.append(f"Thought: Search KB for component: '{query2}'")
            try:
                async with AsyncSessionLocal() as db:
                    results2 = await search_kb_articles(db, query2, limit=3)
                react_trace.append(f"Observation: Found {len(results2)} articles")
                for a in results2:
                    if a.id not in all_articles:
                        all_articles[a.id] = self._format_article(a, keywords)
            except Exception as e:
                react_trace.append(f"Error: {str(e)[:50]}")

        # Round 3: search by significant words from bug title
        stop = {
            "the", "a", "an", "is", "in", "on", "at", "to", "for", "of", "and", "or",
            "failure", "error", "issue", "bug", "not", "with", "this", "that",
        }
        error_words = [w for w in title.split() if len(w) > 4 and w.lower() not in stop][:3]
        if error_words:
            query3 = " ".join(error_words)
            react_trace.append(f"Thought: Search KB for error terms: '{query3}'")
            try:
                async with AsyncSessionLocal() as db:
                    results3 = await search_kb_articles(db, query3, limit=3)
                react_trace.append(f"Observation: Found {len(results3)} articles")
                for a in results3:
                    if a.id not in all_articles:
                        all_articles[a.id] = self._format_article(a, keywords)
            except Exception as e:
                react_trace.append(f"Error: {str(e)[:50]}")

        # Round 4: also query ConfluenceConnector for real Confluence pages
        try:
            import asyncio
            from orchestrator.connectors.registry import ConnectorRegistry
            conf_connector = await ConnectorRegistry.get_by_type("confluence")
            if conf_connector and keywords:
                conf_query = " ".join(keywords[:3])
                conf_results = await asyncio.wait_for(
                    conf_connector.search(conf_query, max_results=3),
                    timeout=8.0,
                )
                react_trace.append(f"Thought: Query Confluence for: '{conf_query}'")
                react_trace.append(f"Observation: Found {len(conf_results)} Confluence pages")
                for ticket in conf_results:
                    if ticket.ticket_id not in all_articles:
                        kw_hits = sum(1 for k in keywords[:8] if k.lower() in ticket.title.lower())
                        all_articles[ticket.ticket_id] = {
                            "title": ticket.title,
                            "url": ticket.url or "#",
                            "excerpt": (ticket.description or "")[:200],
                            "relevance": "High" if any(k.lower() in ticket.title.lower() for k in keywords[:3]) else "Medium",
                            "space": "Confluence",
                            "component": ticket.component or "",
                            "last_modified": "",
                            "keyword_hits": kw_hits,
                            "is_answered": True,
                            "score": max(kw_hits, 1),
                        }
        except Exception:
            pass

        kb_articles = list(all_articles.values())
        print(f"[Enrichment] Found {len(kb_articles)} unique KB articles", flush=True)

        if not kb_articles:
            kb_articles = self._get_fallback_articles(source_id, keywords)
            print(f"[Enrichment] Using {len(kb_articles)} fallback articles", flush=True)

        relevance_order = {"High": 0, "Medium": 1, "Low": 2}
        kb_articles.sort(
            key=lambda x: (relevance_order.get(x.get("relevance", "Low"), 2), -x.get("keyword_hits", 0))
        )
        kb_articles = kb_articles[:4]

        kb_reasoning = ""
        try:
            articles_text = "\n".join([
                f"- {a['title']} ({a.get('relevance','?')} relevance): {a.get('excerpt','')[:80]}"
                for a in kb_articles
            ]) if kb_articles else "No articles found."

            resp = await groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": f"""Bug: {title}
Component: {components[0] if components else 'Unknown'}
Keywords: {', '.join(keywords[:5])}

KB Articles found (simulated Confluence search):
{articles_text}

In exactly 2 sentences, tell the engineer which article is most \
relevant and what specific section to look at. Be technical."""}],
                max_tokens=100,
                temperature=0.3,
            )
            kb_reasoning = resp.choices[0].message.content.strip()
        except Exception as e:
            kb_reasoning = f"Found {len(kb_articles)} relevant knowledge base articles for this issue."

        print(f"[Enrichment] KB reasoning generated", flush=True)

        context["kb_articles"] = kb_articles
        context["kb_reasoning"] = kb_reasoning
        context["kb_react_trace"] = react_trace
        context["customer_cases"] = []
        return context

    def _format_article(self, article, keywords: list) -> dict:
        content_lower = (article.title + " " + article.content).lower()
        keyword_hits = sum(1 for k in keywords[:8] if k.lower() in content_lower)

        if keyword_hits >= 3:
            relevance = "High"
        elif keyword_hits >= 1:
            relevance = "Medium"
        else:
            relevance = "Low"

        excerpt = article.content[:200]
        for kw in keywords[:3]:
            idx = article.content.lower().find(kw.lower())
            if idx != -1:
                start = max(0, idx - 30)
                end = min(len(article.content), idx + 170)
                excerpt = article.content[start:end]
                break

        return {
            "title": article.title,
            "url": article.url,
            "excerpt": excerpt,
            "relevance": relevance,
            "space": article.space_key,
            "component": article.component or "",
            "last_modified": article.last_modified,
            "keyword_hits": keyword_hits,
            "is_answered": True,
            "score": keyword_hits,
        }

    def _get_fallback_articles(self, source_id: str, keywords: list) -> list:
        source_lower = source_id.lower()
        if "spark" in source_lower:
            return [
                {
                    "title": "Spark SQL Performance Tuning — Official Docs",
                    "url": "https://spark.apache.org/docs/latest/sql-performance-tuning.html",
                    "excerpt": "Covers AQE, broadcast joins, partition pruning, CTE optimization, and NullPointerException handling in SQL operations.",
                    "relevance": "High", "space": "Apache Spark Docs",
                    "component": "SQL", "last_modified": "2024-11-15",
                    "keyword_hits": 2, "is_answered": True, "score": 2,
                },
                {
                    "title": "PySpark DataFrame API Troubleshooting",
                    "url": "https://spark.apache.org/docs/latest/api/python/getting_started/quickstart_df.html",
                    "excerpt": "Common errors: is_remote_only() in Connect mode, AnalysisException column not found, schema mismatch, UDF null handling.",
                    "relevance": "Medium", "space": "Apache Spark Docs",
                    "component": "PySpark", "last_modified": "2024-10-22",
                    "keyword_hits": 1, "is_answered": True, "score": 1,
                },
            ]
        elif "kafka" in source_lower:
            return [
                {
                    "title": "Kafka Producer Configuration — Delivery Guarantees",
                    "url": "https://kafka.apache.org/documentation/#producerconfigs",
                    "excerpt": "acks=all, idempotence, batching, RecordTooLargeException, TimeoutException causes.",
                    "relevance": "High", "space": "Apache Kafka Docs",
                    "component": "Producer", "last_modified": "2024-11-01",
                    "keyword_hits": 2, "is_answered": True, "score": 2,
                },
            ]
        else:
            return [
                {
                    "title": "Firefox Source Documentation",
                    "url": "https://firefox-source-docs.mozilla.org/",
                    "excerpt": "Firefox SpiderMonkey JIT, WebRender graphics, DOM layout, memory management.",
                    "relevance": "Medium", "space": "Mozilla Docs",
                    "component": "Core", "last_modified": "2024-11-05",
                    "keyword_hits": 1, "is_answered": True, "score": 1,
                },
            ]
