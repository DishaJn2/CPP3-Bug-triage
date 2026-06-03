import asyncio
import dataclasses
import os
import json
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from ..connectors.registry import ConnectorRegistry
from ..models.synthesis import CandidateScore

log = structlog.get_logger()


class CrossSystemFetchAgent(BaseAgent):
    step_name = "cross_system_fetch"

    async def run(self, context: dict) -> dict:
        primary = context.get("primary_ticket") or {}
        primary_source = context.get("source_id", "")

        if not primary:
            self._add_error(context, "No primary ticket in context")
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        groq_api_key = os.getenv("GROQ_API_KEY", "")
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        # Step A: Generate platform-specific queries using LLM
        query_map = await self._generate_platform_queries(
            primary, groq_api_key, groq_model
        )
        log.info("CrossSystem queries generated", queries=query_map)

        # Step B: Select target connectors
        all_connectors = await ConnectorRegistry.get_all_enabled()
        targets = self._select_targets(all_connectors, primary_source)
        log.info("CrossSystem targets", targets=[c.source_id for c in targets])

        if not targets:
            log.warning("No target connectors", primary_source=primary_source)
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        # Step C: Fire parallel searches with platform-specific queries
        async def search_one(connector):
            ctype     = type(connector).__name__.lower()
            source_id = connector.source_id

            # Sisters get specific query; related get broad query
            is_sister = (
                self._get_family(source_id) ==
                self._get_family(primary_source))

            if "jira" in ctype:
                query = (query_map.get("jira_query", "")
                         if is_sister
                         else query_map.get("broad_query", ""))
            elif "github" in ctype:
                query = (query_map.get("github_query", "")
                         if is_sister
                         else query_map.get("broad_query", ""))
            elif "bugzilla" in ctype:
                query = (query_map.get("bugzilla_query", "")
                         if is_sister
                         else query_map.get("broad_query", ""))
            else:
                query = query_map.get("broad_query", "")

            if not query:
                return source_id, []

            try:
                results = await asyncio.wait_for(
                    connector.search(query, max_results=8),
                    timeout=12.0)
                log.info("CrossSystem result",
                         source=source_id,
                         query=query,
                         sister=is_sister,
                         count=len(results))
                return source_id, results
            except asyncio.TimeoutError:
                log.warning("CrossSystem timeout",
                            source=source_id)
                return source_id, []
            except Exception as e:
                log.warning("CrossSystem error",
                            source=source_id, error=str(e))
                return source_id, []

        gathered = await asyncio.gather(*[search_one(c) for c in targets])

        candidates = []
        sources_queried = []
        for source_id, tickets in gathered:
            sources_queried.append(source_id)
            for t in tickets:
                candidates.append(dataclasses.asdict(t))

        log.info("CrossSystem candidates", total=len(candidates))

        # Tier 2 fallback: if 0 candidates, try broader query
        if not candidates and primary:
            title = primary.get("title", "")
            component = primary.get("component", "") or ""
            # Extract just the first meaningful word from title
            words = [w for w in title.split()
                     if len(w) > 5
                     and w.lower() not in {
                         "cannot", "failed", "unable", "invalid",
                         "exception", "error", "failure", "issue"}]
            fallback_term = words[0] if words else component

            if fallback_term:
                fallback_queries = {
                    "jira_query": fallback_term,
                    "github_query": fallback_term,
                    "bugzilla_query": fallback_term,
                }
                log.info("CrossSystem Tier2 fallback",
                         term=fallback_term)

                async def search_fallback(connector):
                    ctype = type(connector).__name__.lower()
                    if "jira" in ctype:
                        q = fallback_queries["jira_query"]
                    elif "github" in ctype:
                        q = fallback_queries["github_query"]
                    else:
                        q = fallback_queries["bugzilla_query"]
                    try:
                        r = await asyncio.wait_for(
                            connector.search(q, max_results=8),
                            timeout=12.0)
                        return connector.source_id, r
                    except Exception:
                        return connector.source_id, []

                fb_gathered = await asyncio.gather(
                    *[search_fallback(c) for c in targets])
                for sid, tickets in fb_gathered:
                    for t in tickets:
                        candidates.append(dataclasses.asdict(t))

        # Add co-references from ContextFetchAgent as
        # deterministic links (score = 1.0, bypass threshold)
        co_refs = context.get("co_references") or []
        direct_hits = []
        if co_refs:
            all_enabled = await ConnectorRegistry.get_all_enabled()
            for ref in co_refs[:5]:
                for c in all_enabled:
                    if (c.source_id != primary_source
                            and c.system_type not in
                            {"confluence", "customer_portal"}):
                        try:
                            t = await asyncio.wait_for(
                                c.get(ref["raw_id"]),
                                timeout=8.0)
                            if t:
                                td = dataclasses.asdict(t)
                                td["similarity_score"] = 1.0
                                td["similarity_label"] = "Identical"
                                td["similarity_reason"] = (
                                    "Explicit cross-reference "
                                    "found in bug text")
                                td["similarity_matching_fields"] = [
                                    "direct_reference"]
                                direct_hits.append(td)
                                log.info(
                                    "CrossSystem direct hit",
                                    ref=ref["raw_id"],
                                    source=c.source_id)
                                break
                        except Exception:
                            pass

        # Direct hits bypass scoring (already score 1.0)
        scored = direct_hits + await self._batch_score(
            primary, candidates, groq_api_key, groq_model)

        # Deduplicate by ticket_id
        seen_ids = set()
        deduped = []
        for item in scored:
            tid = item.get("ticket_id", "")
            if tid not in seen_ids:
                seen_ids.add(tid)
                deduped.append(item)
        scored = deduped

        log.info("CrossSystem scored", results=len(scored))

        context["related_tickets"] = scored
        context["sources_queried"] = sources_queried
        return context

    async def _generate_platform_queries(
            self, primary: dict,
            api_key: str, model: str) -> dict:
        title         = (primary.get("title") or "")
        component     = (primary.get("component") or "")
        error_excerpt = (primary.get("error_excerpt") or "")[:300]
        description   = (primary.get("description") or "")[:200]

        fallback = self._deterministic_fallback(title, component)

        if not api_key:
            return {**fallback, "broad_query": component or fallback["jira_query"]}

        prompt = f"""You are an expert systems engineer finding
duplicate bugs across different issue trackers.

Bug:
Title: {title}
Component: {component}
Error: {error_excerpt}

Generate TWO sets of search terms:
1. SPECIFIC: 1-2 exact technical identifiers (class names,
   exception types, method names) for searching the same
   project's sister system
2. BROAD: 1-2 general technical terms for searching related
   projects in the same ecosystem

Rules:
- Strip ALL line numbers, hex addresses, thread IDs
- No generic words: bug, issue, error, fail, problem
- Examples:
  specific: "NormalizeCTEIds" or "StorageController NPE"
  broad: "SQL optimizer" or "storage allocation"

Output JSON only:
{{
  "jira_query":    "specific 1-2 terms",
  "github_query":  "specific 1-2 terms",
  "bugzilla_query":"specific 1-2 terms",
  "broad_query":   "broad 1-2 terms for related projects"
}}"""

        try:
            client = AsyncGroq(api_key=api_key)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=120,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)

            result = {
                "jira_query":    str(parsed.get(
                    "jira_query", "")).strip()[:60],
                "github_query":  str(parsed.get(
                    "github_query", "")).strip()[:60],
                "bugzilla_query":str(parsed.get(
                    "bugzilla_query", "")).strip()[:60],
                "broad_query":   str(parsed.get(
                    "broad_query", "")).strip()[:60],
            }

            # Validate — fall back if generic
            generic = {"bug", "issue", "error", "fix",
                       "failure", "problem", "exception",
                       "crash", "null", ""}
            for key in ["jira_query", "github_query",
                        "bugzilla_query"]:
                first = result[key].split()[0].lower() \
                    if result[key] else ""
                if not result[key] or first in generic:
                    result[key] = fallback.get(key, "")
            if not result["broad_query"]:
                result["broad_query"] = component or \
                    fallback["jira_query"]

            return result

        except Exception as e:
            log.warning("Query generation failed", error=str(e))
            return {**fallback,
                    "broad_query": component or
                    fallback["jira_query"]}

    def _deterministic_fallback(self, title: str, component: str) -> dict:
        import re
        # Prefer CamelCase identifiers (class/method names)
        camel = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', title)
        if camel:
            term = camel[0]
        else:
            # Fallback: longest word > 6 chars from title
            words = [w for w in re.findall(r'\b\w+\b', title)
                     if len(w) > 6 and not w.lower() in
                     {'exception', 'failure', 'problem', 'cannot', 'invalid'}]
            term = words[0] if words else (component or title.split()[0])

        return {
            "jira_query": term[:50],
            "github_query": term[:50],
            "bugzilla_query": term[:50],
        }

    def _get_family(self, source_id: str) -> str:
        s = source_id.lower()
        for p in ["apache-", "mozilla-", "microsoft-",
                  "kubernetes-", "facebook-", "nodejs-"]:
            s = s.replace(p, "")
        for sx in ["-jira", "-github", "-bugzilla",
                   "-gitlab", "-flink", "-github"]:
            s = s.replace(sx, "")
        return s.strip("-")

    def _select_targets(self, all_connectors: list, primary_source_id: str) -> list:
        excluded = {"confluence", "customer_portal"}
        candidates = [
            c for c in all_connectors
            if c.source_id != primary_source_id
            and c.system_type not in excluded
        ]

        if not candidates:
            return []

        def family(sid: str) -> str:
            s = sid.lower()
            for p in ["apache-", "mozilla-", "microsoft-",
                      "kubernetes-", "facebook-", "nodejs-"]:
                s = s.replace(p, "")
            for sx in ["-jira", "-github", "-bugzilla", "-gitlab"]:
                s = s.replace(sx, "")
            return s

        pf = family(primary_source_id)
        apache = {"spark", "kafka", "hadoop", "hive", "flink", "hbase",
                  "cassandra", "airflow", "zookeeper"}

        sisters = [c for c in candidates if family(c.source_id) == pf]
        related = [c for c in candidates
                   if family(c.source_id) in apache
                   and family(c.source_id) != pf
                   and c not in sisters]

        seen = {c.system_type for c in sisters + related}
        others = []
        for c in candidates:
            if c not in sisters and c not in related and c.system_type not in seen:
                others.append(c)
                seen.add(c.system_type)

        return (sisters + related[:3] + others[:2])[:6]

    async def _batch_score(self, primary: dict, candidates: list,
                           api_key: str, model: str) -> list:
        if not candidates:
            return []

        if not api_key:
            for c in candidates:
                c["similarity_score"] = 0.4
                c["similarity_label"] = "Possible"
                c["similarity_reason"] = "No AI scoring available"
                c["similarity_matching_fields"] = []
            return candidates

        primary_str = (
            f"Title: {primary.get('title', '')}\n"
            f"Component: {primary.get('component', '')}\n"
            f"Severity: {primary.get('severity', '')}\n"
            f"Error: {(primary.get('error_excerpt') or '')[:300]}\n"
            f"Description: {(primary.get('description') or '')[:300]}"
        )

        cands_str = ""
        for i, c in enumerate(candidates[:12]):
            cands_str += (
                f"\n[{i}] id={c.get('ticket_id')} "
                f"source={c.get('source_id')}\n"
                f"Title: {c.get('title', '')}\n"
                f"Component: {c.get('component', '')}\n"
                f"Description: {(c.get('description') or '')[:200]}\n"
            )

        prompt = (
            f"Score how related each candidate bug is to the primary bug.\n"
            f"Focus on: same root cause, same component, same exception, "
            f"same failing code path.\n\n"
            f"Primary:\n{primary_str}\n\n"
            f"Candidates:{cands_str}\n\n"
            f"Return a JSON object with key 'results' as array. Each item:\n"
            f"index, ticket_id, similarity_score (0.0-1.0), "
            f"similarity_label (Identical/Very Similar/Similar/Possible/Unrelated),\n"
            f"similarity_reason (one sentence), "
            f"similarity_matching_fields (array).\n"
            f"Scoring: 0.9+ same root cause, 0.7 same component+error, "
            f"0.5 same component, 0.3 related area, 0.1 unrelated.\n"
            f"Return JSON only."
        )

        try:
            client = AsyncGroq(api_key=api_key)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=1500,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)

            scores_list = (
                parsed.get("results")
                or parsed.get("scores")
                or parsed.get("candidates")
                or (parsed if isinstance(parsed, list) else [])
            )

            score_map = {}
            for s in scores_list:
                try:
                    validated = CandidateScore(**s)
                    score_map[str(validated.ticket_id)] = validated
                except Exception:
                    continue

            for c in candidates[:12]:
                tid = str(c.get("ticket_id", ""))
                if tid in score_map:
                    v = score_map[tid]
                    c["similarity_score"] = v.similarity_score
                    c["similarity_label"] = v.similarity_label
                    c["similarity_reason"] = v.similarity_reason
                    c["similarity_matching_fields"] = v.similarity_matching_fields
                else:
                    c["similarity_score"] = 0.25
                    c["similarity_label"] = "Possible"
                    c["similarity_reason"] = "Not scored"
                    c["similarity_matching_fields"] = []

        except Exception as e:
            log.warning("Batch scoring failed", error=str(e))
            for c in candidates:
                c["similarity_score"] = 0.25
                c["similarity_label"] = "Possible"
                c["similarity_reason"] = "Scoring unavailable"
                c["similarity_matching_fields"] = []

        result = [c for c in candidates[:12]
                  if c.get("similarity_score", 0) >= 0.50
                  or c.get("similarity_label") == "Identical"]
        result.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        return result
