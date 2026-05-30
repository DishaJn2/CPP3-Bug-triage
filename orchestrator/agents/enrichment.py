import os
import html as html_module
import structlog
from groq import AsyncGroq
from .base import BaseAgent

log = structlog.get_logger()


class EnrichmentAgent(BaseAgent):
    step_name = "enrichment"

    async def run(self, context: dict) -> dict:
        import httpx

        primary_ticket = context.get("primary_ticket", {})
        keywords = context.get("keywords", [])
        components = context.get("components", [])
        title = primary_ticket.get("title", "")
        description = (primary_ticket.get("description") or "")[:300]
        source_id = context.get("source_id", "")

        tag_map = {
            "apache-spark": "apache-spark",
            "spark":        "apache-spark",
            "apache-kafka": "apache-kafka",
            "kafka":        "apache-kafka",
            "firefox":      "firefox",
            "mozilla":      "firefox",
            "pyspark":      "pyspark",
        }

        so_tag = "apache-spark"
        source_lower = source_id.lower()
        component_lower = (components[0] if components else "").lower()

        for key, tag in tag_map.items():
            if key in source_lower or key in component_lower:
                so_tag = tag
                break

        keyword_str = " ".join(keywords).lower()
        if "kafka" in keyword_str and "spark" not in keyword_str:
            so_tag = "apache-kafka"
        elif "pyspark" in keyword_str:
            so_tag = "pyspark"
        elif "firefox" in keyword_str or "mozilla" in keyword_str:
            so_tag = "firefox"

        stop_words = {
            "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
            "and", "or", "with", "this", "that", "was", "has", "are", "not",
            "bug", "error", "issue", "fail", "failed", "when", "using",
            "after", "during", "while", "cannot", "does", "not", "null", "java",
        }

        title_words = [
            w for w in title.split()
            if len(w) > 4
            and w.lower() not in stop_words
            and w.isalpha()
        ][:4]

        search_query = " ".join(title_words) if title_words else " ".join(keywords[:3])

        kb_articles = []
        react_trace = []

        # ReAct Round 1 — search Stack Overflow with title terms + tag
        try:
            react_trace.append(f"Thought: Search Stack Overflow for '{search_query}' tagged [{so_tag}]")

            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    "https://api.stackexchange.com/2.3/search/advanced",
                    params={
                        "order":    "desc",
                        "sort":     "relevance",
                        "q":        search_query,
                        "tagged":   so_tag,
                        "site":     "stackoverflow",
                        "pagesize": 5,
                        "filter":   "default",
                    },
                )

                if resp.status_code != 200:
                    log.warning("SO API error", status=resp.status_code, body=resp.text[:200])
                    react_trace.append(f"Observation: SO API error {resp.status_code}")
                else:
                    data = resp.json()
                    items = data.get("items", [])
                    log.info("EnrichmentAgent SO response",
                             status=resp.status_code,
                             items_count=len(items),
                             query=search_query,
                             tag=so_tag)
                    react_trace.append(f"Observation: found {len(items)} Stack Overflow results")

                    for item in items:
                        score = item.get("score", 0)
                        answer_count = item.get("answer_count", 0)
                        is_answered = item.get("is_answered", False)

                        title_lower = item.get("title", "").lower()
                        keyword_hits = sum(
                            1 for k in keywords[:6] if k.lower() in title_lower
                        )

                        if is_answered and score >= 5:
                            relevance = "High"
                        elif is_answered or score >= 2:
                            relevance = "Medium"
                        else:
                            relevance = "Low"

                        if keyword_hits >= 2:
                            relevance = "High"

                        tags = item.get("tags", [])

                        kb_articles.append({
                            "title":         html_module.unescape(item.get("title", "")),
                            "url":           item.get("link", ""),
                            "excerpt":       f"Score: {score} · {answer_count} answer(s) · Tags: {', '.join(tags[:4])}",
                            "relevance":     relevance,
                            "space":         "Stack Overflow",
                            "component":     so_tag,
                            "last_modified": "",
                            "keyword_hits":  keyword_hits,
                            "is_answered":   is_answered,
                            "score":         score,
                            "tags":          tags[:6],
                        })
        except Exception as e:
            react_trace.append(f"Error in Round 1: {str(e)[:100]}")

        # ReAct Round 2 — if fewer than 3 results, try broader search without tag
        if len(kb_articles) < 3 and keywords:
            try:
                broader_query = " ".join(keywords[:4])
                react_trace.append(f"Thought: Round 1 insufficient, trying broader search '{broader_query}'")

                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                    resp = await client.get(
                        "https://api.stackexchange.com/2.3/search/advanced",
                        params={
                            "order":    "desc",
                            "sort":     "relevance",
                            "q":        broader_query,
                            "site":     "stackoverflow",
                            "pagesize": 3,
                            "filter":   "default",
                        },
                    )

                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        react_trace.append(f"Observation: broader search found {len(items)} results")

                        existing_urls = {a["url"] for a in kb_articles}
                        for item in items:
                            if item.get("link") not in existing_urls:
                                kb_articles.append({
                                    "title":         html_module.unescape(item.get("title", "")),
                                    "url":           item.get("link", ""),
                                    "excerpt":       f"Score: {item.get('score', 0)} · {item.get('answer_count', 0)} answer(s)",
                                    "relevance":     "Medium",
                                    "space":         "Stack Overflow",
                                    "component":     "general",
                                    "last_modified": "",
                                    "keyword_hits":  0,
                                    "is_answered":   item.get("is_answered", False),
                                    "score":         item.get("score", 0),
                                    "tags":          item.get("tags", [])[:6],
                                })
            except Exception as e:
                react_trace.append(f"Error in Round 2: {str(e)[:100]}")

        # DB fallback if Stack Overflow returned nothing
        if not kb_articles:
            try:
                from orchestrator.db.session import AsyncSessionLocal
                from orchestrator.db.repositories.kb_articles import search_kb_articles

                async with AsyncSessionLocal() as db:
                    query = " ".join(keywords[:3])
                    db_articles = await search_kb_articles(db, query, limit=3)
                    for a in db_articles:
                        kb_articles.append({
                            "title":         a.title,
                            "url":           a.url,
                            "excerpt":       a.content[:200],
                            "relevance":     "Medium",
                            "space":         a.space_key,
                            "component":     a.component or "",
                            "last_modified": a.last_modified,
                            "keyword_hits":  0,
                            "is_answered":   False,
                            "score":         0,
                            "tags":          [],
                        })
            except Exception:
                pass

        # Static fallback — always returns at least 3 articles if SO + DB both failed
        if not kb_articles:
            log.info("EnrichmentAgent: SO returned nothing, using static fallback KB")
            src_lower = source_id.lower()
            if "spark" in src_lower:
                kb_articles = [
                    {
                        "title": "Spark SQL Performance Tuning — Official Docs",
                        "url": "https://spark.apache.org/docs/latest/sql-performance-tuning.html",
                        "excerpt": "Covers AQE, broadcast joins, partition pruning, memory configuration, and common SQL errors including NullPointerException handling and CTE optimization.",
                        "relevance": "High", "space": "Apache Spark Docs", "component": "SQL",
                        "last_modified": "2024-11-15", "is_answered": True, "score": 10, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "PySpark DataFrame API Troubleshooting",
                        "url": "https://spark.apache.org/docs/latest/api/python/getting_started/quickstart_df.html",
                        "excerpt": "Common PySpark errors: AnalysisException column not found, NullPointerException in UDFs, Py4JJavaError heap space, is_remote_only() in Connect mode, schema mismatch on union.",
                        "relevance": "High", "space": "Apache Spark Docs", "component": "PySpark",
                        "last_modified": "2024-10-22", "is_answered": True, "score": 8, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "Structured Streaming Programming Guide",
                        "url": "https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html",
                        "excerpt": "Fault tolerance via checkpointing, Kafka source recovery, RocksDB state store, trigger intervals, SupportsMetadataColumns for Kafka and file sources.",
                        "relevance": "Medium", "space": "Apache Spark Docs", "component": "Streaming",
                        "last_modified": "2024-09-30", "is_answered": True, "score": 7, "keyword_hits": 0, "tags": [],
                    },
                ]
            elif "kafka" in src_lower:
                kb_articles = [
                    {
                        "title": "Kafka Producer Configuration — Delivery Guarantees",
                        "url": "https://kafka.apache.org/documentation/#producerconfigs",
                        "excerpt": "acks=all for exactly-once, idempotence, batching with linger.ms, RecordTooLargeException fix, TimeoutException causes, NotLeaderForPartitionException handling.",
                        "relevance": "High", "space": "Apache Kafka Docs", "component": "Producer",
                        "last_modified": "2024-11-01", "is_answered": True, "score": 9, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "Kafka Consumer Group Rebalancing Guide",
                        "url": "https://kafka.apache.org/documentation/#consumerconfigs",
                        "excerpt": "CooperativeStickyAssignor for incremental rebalance, session.timeout.ms tuning, max.poll.interval.ms for slow processing, static group membership with group.instance.id.",
                        "relevance": "High", "space": "Apache Kafka Docs", "component": "Consumer",
                        "last_modified": "2024-10-10", "is_answered": True, "score": 8, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "Kafka Streams State Store and RocksDB",
                        "url": "https://kafka.apache.org/documentation/streams/",
                        "excerpt": "RocksDB tuning for Kafka Streams, standby replicas, interactive queries, lock file issues on restart, log compaction on changelog topics.",
                        "relevance": "Medium", "space": "Apache Kafka Docs", "component": "Streams",
                        "last_modified": "2024-09-18", "is_answered": True, "score": 7, "keyword_hits": 0, "tags": [],
                    },
                ]
            elif "firefox" in src_lower or "bugzilla" in src_lower:
                kb_articles = [
                    {
                        "title": "Firefox SpiderMonkey JIT Engine — Memory Issues",
                        "url": "https://firefox-source-docs.mozilla.org/js/",
                        "excerpt": "JIT compilation tiers, memory leaks via uncleaned event listeners, heap OOM crashes via about:crashes, WebAssembly SharedArrayBuffer threading.",
                        "relevance": "High", "space": "Mozilla Docs", "component": "JavaScript Engine",
                        "last_modified": "2024-11-05", "is_answered": True, "score": 9, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "Firefox WebRender Graphics Pipeline",
                        "url": "https://firefox-source-docs.mozilla.org/gfx/",
                        "excerpt": "WebRender GPU-accelerated compositor, WebGL context lost errors, WebGPU via dom.webgpu.enabled, HiDPI display scaling, OffscreenCanvas for worker-thread rendering.",
                        "relevance": "High", "space": "Mozilla Docs", "component": "Graphics",
                        "last_modified": "2024-10-20", "is_answered": True, "score": 8, "keyword_hits": 0, "tags": [],
                    },
                    {
                        "title": "Firefox DOM and CSS Layout Bugs",
                        "url": "https://firefox-source-docs.mozilla.org/dom/",
                        "excerpt": "position:sticky with overflow:hidden ancestors, Custom Elements Shadow DOM, pointer events vs mouse events, WeakRef for DOM node memory management.",
                        "relevance": "Medium", "space": "Mozilla Docs", "component": "DOM",
                        "last_modified": "2024-09-12", "is_answered": True, "score": 7, "keyword_hits": 0, "tags": [],
                    },
                ]
            else:
                kb_articles = [
                    {
                        "title": "Stack Overflow — Search for related issues",
                        "url": f"https://stackoverflow.com/search?q={'+'.join(keywords[:3])}",
                        "excerpt": f"Search Stack Overflow for: {' '.join(keywords[:5])}",
                        "relevance": "Medium", "space": "Stack Overflow", "component": "",
                        "last_modified": "", "is_answered": False, "score": 0, "keyword_hits": 0, "tags": [],
                    },
                ]

        # Sort: High first, then by SO score
        relevance_order = {"High": 0, "Medium": 1, "Low": 2}
        kb_articles.sort(
            key=lambda x: (relevance_order.get(x["relevance"], 3), -x.get("score", 0))
        )
        kb_articles = kb_articles[:5]

        # Groq reasoning about the found articles
        kb_reasoning = ""
        try:
            groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))

            articles_text = "\n".join([
                f"- {a['title']} (SO score: {a.get('score', 0)}, answered: {a.get('is_answered', False)})"
                for a in kb_articles
            ]) if kb_articles else "No relevant articles found."

            prompt = f"""Bug being triaged:
Title: {title}
Component: {components[0] if components else 'Unknown'}
Keywords: {', '.join(keywords[:5])}

Stack Overflow articles found:
{articles_text}

In 2 sentences, explain which article is most relevant to this \
bug and what the engineer should specifically look for in it.
Be technical and precise."""

            resp = await groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=0.3,
            )
            kb_reasoning = resp.choices[0].message.content.strip()
        except Exception:
            kb_reasoning = f"Found {len(kb_articles)} relevant Stack Overflow discussions."

        context["kb_articles"] = kb_articles
        context["kb_reasoning"] = kb_reasoning
        context["kb_react_trace"] = react_trace
        context["customer_cases"] = []
        return context
