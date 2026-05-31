import asyncio
import json
import os
import dataclasses
import structlog
from groq import AsyncGroq
from .base import BaseAgent
from orchestrator.connectors.registry import ConnectorRegistry

log = structlog.get_logger()


class CrossSystemFetchAgent(BaseAgent):
    step_name = "cross_system_fetch"

    async def run(self, context: dict) -> dict:
        primary_ticket = context.get("primary_ticket")
        source_id = context.get("source_id", "")
        keywords = context.get("keywords", [])

        if not primary_ticket:
            print("[CrossSystemFetch] No primary ticket in context", flush=True)
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        # Step A: LLM generates optimal search query
        search_query = await self._generate_query(groq_client, model, primary_ticket, keywords)
        print(f"[CrossSystemFetch] Query: '{search_query}'", flush=True)

        # Step B: Search ALL other connectors in parallel
        all_connectors = await ConnectorRegistry.get_all_enabled()
        other_connectors = [
            c for c in all_connectors
            if c.source_id != source_id and c.system_type not in ("confluence",)
        ]

        print(f"[CrossSystemFetch] Searching {len(other_connectors)} other connectors: {[c.source_id for c in other_connectors]}", flush=True)

        if not other_connectors:
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        sources_queried = [c.source_id for c in other_connectors]

        async def safe_search(connector):
            try:
                results = await asyncio.wait_for(
                    connector.search(search_query, max_results=5),
                    timeout=12.0,
                )
                print(f"[CrossSystemFetch] {connector.source_id}: {len(results or [])} results", flush=True)
                return results or []
            except asyncio.TimeoutError:
                print(f"[CrossSystemFetch] {connector.source_id}: TIMEOUT", flush=True)
                return []
            except Exception as e:
                print(f"[CrossSystemFetch] {connector.source_id}: ERROR {str(e)[:80]}", flush=True)
                return []

        search_results = await asyncio.gather(*[safe_search(c) for c in other_connectors])

        candidates = []
        for batch in search_results:
            if batch:
                candidates.extend(batch)

        print(f"[CrossSystemFetch] Total candidates: {len(candidates)}", flush=True)

        if not candidates:
            context["related_tickets"] = []
            context["sources_queried"] = sources_queried
            return context

        # Step C: LLM scores candidates
        scored = await self._score_candidates(groq_client, model, primary_ticket, candidates)
        print(f"[CrossSystemFetch] Scored: {len(scored)}", flush=True)

        # Step D: Filter below 0.25, sort descending
        filtered = [s for s in scored if s.get("similarity_score", 0) >= 0.25]

        # If LLM scoring returned nothing, try keyword-based simple scoring
        if not filtered and candidates:
            try:
                simple_scored = await self._simple_score(candidates, primary_ticket)
                filtered = [s for s in simple_scored if s.get("similarity_score", 0) >= 0.25]
            except Exception as e:
                print(f"[CrossSystemFetch] Simple scoring failed: {e}", flush=True)

        filtered.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        print(f"[CrossSystemFetch] Final related tickets: {len(filtered[:8])}", flush=True)

        context["related_tickets"] = filtered[:8]
        context["sources_queried"] = sources_queried
        return context

    async def _simple_score(self, candidates, primary):
        primary_keywords = primary.get("keywords", [])
        primary_title_words = set(primary.get("title", "").lower().split())
        result = []
        for c in candidates:
            try:
                cd = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else c
                candidate_title = cd.get("title", "").lower()
                candidate_desc = (cd.get("description") or "").lower()

                keyword_hits = sum(
                    1 for kw in primary_keywords
                    if kw.lower() in candidate_title or kw.lower() in candidate_desc
                )
                title_word_hits = len(primary_title_words & set(candidate_title.split()))
                score = min(0.9, (keyword_hits * 0.15) + (title_word_hits * 0.10))

                if score >= 0.25:
                    label = "Good Match" if score >= 0.60 else "Fair Match" if score >= 0.40 else "Possible Match"
                    result.append({
                        **cd,
                        "similarity_score": round(score, 2),
                        "similarity_label": label,
                        "similarity_reason": f"Keyword overlap: {keyword_hits} matching terms found",
                        "similarity_matching_fields": ["title", "description"],
                    })
            except Exception:
                pass
        result.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        return result[:5]

    async def _generate_query(self, client, model, ticket, keywords):
        title = ticket.get("title", "")
        description = (ticket.get("description") or "")[:300]
        component = ticket.get("component") or ""
        error_excerpt = (ticket.get("error_excerpt") or "")[:200]

        prompt = f"""Generate a 3-5 keyword search query for finding related bugs in JIRA and Bugzilla.

Bug: {title}
Component: {component}
Keywords already extracted: {', '.join(keywords[:5])}
Error/Description snippet: {error_excerpt or description[:150]}

Rules:
- Use specific technical terms that appear in the bug title/description
- These exact words should appear in related bug titles
- 3-5 keywords maximum
- No generic words: error, bug, issue, fail, crash, fix, problem

Examples:
"Optimizer failure: NormalizeCTEIds brakes CTE references for queries with nested CTEs"
→ NormalizeCTEIds CTE InlineCTE optimizer

"PySpark DataFrame methods behind is_remote_only() statically evaluate to Union"
→ is_remote_only DataFrame static Union

"DSv2 streaming doesn't support SupportsMetadataColumns"
→ SupportsMetadataColumns DSv2 streaming metadata

Return ONLY the keywords separated by spaces. Nothing else."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=25,
                temperature=0.0,
            )
            query = response.choices[0].message.content.strip().strip('"\'').split('\n')[0]
            return query if query else " ".join(keywords[:3])
        except Exception as e:
            print(f"[CrossSystemFetch] Query generation failed: {e}", flush=True)
            return " ".join(keywords[:4]) if keywords else title[:50]

    async def _score_candidates(self, client, model, primary, candidates):
        primary_text = f"""PRIMARY BUG:
Title: {primary.get('title', '')}
Component: {primary.get('component', '') or 'unknown'}
Description: {(primary.get('description') or '')[:300]}
Error: {(primary.get('error_excerpt') or '')[:200]}
Keywords: {', '.join(primary.get('keywords', [])[:8])}
Severity: {primary.get('severity', '') or 'unknown'}"""

        candidates_text = ""
        capped = candidates[:8]
        for i, c in enumerate(capped):
            try:
                cd = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else (c if isinstance(c, dict) else {})
                candidates_text += f"""
CANDIDATE {i+1} (id={cd.get('ticket_id','?')}, source={cd.get('source_id','?')}):
  Title: {cd.get('title','')}
  Component: {cd.get('component','') or 'unknown'}
  Description: {(cd.get('description') or '')[:150]}
  Severity: {cd.get('severity','') or 'unknown'}
  Status: {cd.get('status','')}"""
            except Exception:
                candidates_text += f"\nCANDIDATE {i+1}: (parse error)"

        prompt = f"""{primary_text}
{candidates_text}

Score each candidate's similarity to the primary bug (0.0 to 1.0).
Consider: same error type, same component, same root cause, similar description.

Return a JSON object with this exact format:
{{
  "scores": [
    {{
      "ticket_id": "exact id from candidate",
      "similarity_score": 0.85,
      "similarity_label": "Good Match",
      "similarity_reason": "Same component and error type",
      "similarity_matching_fields": ["title", "component"]
    }}
  ]
}}

Labels: >=0.75 Excellent Match, >=0.50 Good Match, >=0.30 Fair Match, <0.30 Weak Match
Return valid JSON only."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            scores_list = parsed.get("scores", [])

            result = []
            for entry in scores_list:
                ticket_id = entry.get("ticket_id", "")
                original = None
                for c in capped:
                    try:
                        cid = c.ticket_id if hasattr(c, 'ticket_id') else c.get('ticket_id', '')
                        if str(cid) == str(ticket_id):
                            original = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else c
                            break
                    except Exception:
                        pass
                if original:
                    result.append({
                        **original,
                        "similarity_score": entry.get("similarity_score", 0),
                        "similarity_label": entry.get("similarity_label", "Fair Match"),
                        "similarity_reason": entry.get("similarity_reason", ""),
                        "similarity_matching_fields": entry.get("similarity_matching_fields", []),
                    })
            return result
        except Exception as e:
            print(f"[CrossSystemFetch] Scoring failed: {e}", flush=True)
            return []
