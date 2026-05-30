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

        if not primary_ticket:
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        # ── STEP A: LLM decides the best search query ────────────────────────
        search_query = await self._llm_decide_query(groq_client, model, primary_ticket)
        log.info("CrossSystemFetch: generated query", query=search_query)

        # ── STEP B: search ALL other connectors in parallel ──────────────────
        all_connectors = await ConnectorRegistry.get_all_enabled()

        other_connectors = [
            c for c in all_connectors
            if c.source_id != source_id and c.system_type != "confluence"
        ]

        if not other_connectors:
            context["related_tickets"] = []
            context["sources_queried"] = []
            return context

        sources_queried = [c.source_id for c in other_connectors]

        async def safe_search(connector):
            try:
                results = await asyncio.wait_for(
                    connector.search(search_query, max_results=5),
                    timeout=10.0,
                )
                return results or []
            except Exception as e:
                log.warning("CrossSystemFetch: connector search failed",
                            source=connector.source_id, error=str(e))
                return []

        search_results = await asyncio.gather(
            *[safe_search(c) for c in other_connectors],
            return_exceptions=False,
        )

        candidates = []
        for batch in search_results:
            candidates.extend(batch)

        log.info("CrossSystemFetch: candidates found",
                 count=len(candidates), sources=sources_queried)

        if not candidates:
            context["related_tickets"] = []
            context["sources_queried"] = sources_queried
            return context

        # ── STEP C: LLM scores every candidate against ALL fields ─────────────
        scored = await self._llm_score(groq_client, model, primary_ticket, candidates)

        log.info("CrossSystemFetch: scored results",
                 total=len(scored),
                 above_threshold=len([s for s in scored if s.get("similarity_score", 0) >= 0.50]))

        # ── STEP D: filter < 0.50, sort descending ───────────────────────────
        filtered = [s for s in scored if s.get("similarity_score", 0) >= 0.50]
        filtered.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)

        context["related_tickets"] = filtered[:8]
        context["sources_queried"] = sources_queried
        return context

    # ─────────────────────────────────────────────────────────────────────────

    async def _llm_decide_query(self, client, model: str, ticket: dict) -> str:
        """Step A: LLM reads all ticket fields and decides the best search query."""
        title = ticket.get("title", "")
        component = ticket.get("component", "") or ""
        description = (ticket.get("description") or "")[:400]
        error_excerpt = (ticket.get("error_excerpt") or "")[:300]
        keywords = ticket.get("keywords", [])
        steps = (ticket.get("steps_to_reproduce") or "")[:200]

        prompt = f"""You are deciding the best search query to find related bugs
in other tracking systems (JIRA, Bugzilla, GitHub Issues).

Primary bug:
  Title:       {title}
  Component:   {component}
  Description: {description}
  Error:       {error_excerpt if error_excerpt else 'not available'}
  Keywords:    {', '.join(keywords[:8]) if keywords else 'none'}
  Steps:       {steps if steps else 'not available'}

Generate ONE search query (maximum 10 words) that will find
semantically related bugs even if they use different vocabulary.
Focus on the core technical concept, not the surface words.
Think about what the underlying technical issue is and search for that.

Examples:
- Bug about "NullPointerException in StorageController" → "storage controller null pointer concurrent thread safety"
- Bug about "DataFrame methods behind is_remote_only()" → "spark connect remote only dataframe static evaluation"
- Bug about "DSv2 streaming SupportsMetadataColumns" → "structured streaming metadata columns schema source"

Return the search query string ONLY. No explanation. No quotes."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=30,
                temperature=0.0,
            )
            query = response.choices[0].message.content.strip().strip('"\'').split('\n')[0].strip()
            return query if query else title[:60]
        except Exception as e:
            log.warning("CrossSystemFetch: LLM query generation failed", error=str(e))
            return " ".join(title.split()[:6])

    # ─────────────────────────────────────────────────────────────────────────

    async def _llm_score(self, client, model: str, primary: dict, candidates: list) -> list[dict]:
        """Step C: LLM scores every candidate against ALL fields of primary in one call."""
        primary_text = f"""PRIMARY BUG:
  Title:           {primary.get('title', '')}
  Component:       {primary.get('component', '') or 'not specified'}
  Description:     {(primary.get('description') or '')[:400]}
  Keywords/Tags:   {', '.join(primary.get('keywords', [])[:8])}
  Severity:        {primary.get('severity', '') or 'unknown'}
  Status:          {primary.get('status', '')}
  Customer impact: {primary.get('customer_impact', '') or 'not specified'}
  Steps to repro:  {(primary.get('steps_to_reproduce') or 'not provided')[:200]}
  Workaround:      {primary.get('workaround', '') or 'none'}
  Error excerpt:   {(primary.get('error_excerpt') or 'not provided')[:250]}
  Comments:        {' | '.join((primary.get('engineer_comments') or primary.get('recent_comments') or [])[:3])}"""

        candidates_text = ""
        capped = candidates[:10]
        for i, c in enumerate(capped):
            try:
                c_dict = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else c
            except Exception:
                c_dict = {}
            candidates_text += f"""
CANDIDATE {i + 1} — {c_dict.get('ticket_id', '')} ({c_dict.get('source_id', '')}):
  Title:         {c_dict.get('title', '')}
  Component:     {c_dict.get('component', '') or 'not specified'}
  Description:   {(c_dict.get('description') or '')[:200]}
  Severity:      {c_dict.get('severity', '') or 'unknown'}
  Status:        {c_dict.get('status', '')}
  Error excerpt: {(c_dict.get('error_excerpt') or 'none')[:150]}
  Comments:      {' | '.join((c_dict.get('engineer_comments') or c_dict.get('recent_comments') or [])[:2])}"""

        prompt = f"""{primary_text}
{candidates_text}

Score each candidate's similarity to the primary bug.
Consider ALL of these factors:
  - Same error type, exception class, or crash signature
  - Same component, subsystem, or module
  - Overlapping occurrence timestamps
  - Similar steps to reproduce or trigger conditions
  - Same customer impact pattern
  - Matching workarounds or recent changes
  - Common keywords, tags, or error strings in comments

Scoring rules:
  >= 0.90 → "Excellent Match" — same root cause likely
  >= 0.75 → "Good Match" — strongly related
  >= 0.50 → "Fair Match" — worth reviewing
  <  0.50 → "Weak Match" — not relevant

Return a JSON array with one entry per candidate in the SAME ORDER:
[
  {{
    "ticket_id": "exact ticket_id from candidate",
    "similarity_score": 0.94,
    "similarity_label": "Excellent Match",
    "similarity_reason": "specific reason referencing actual field values",
    "similarity_matching_fields": ["title", "component", "error_excerpt"]
  }}
]

IMPORTANT: Return valid JSON array ONLY. No explanation. No markdown."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()

            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                scored_list = next(
                    (v for v in parsed.values() if isinstance(v, list)), []
                )
            elif isinstance(parsed, list):
                scored_list = parsed
            else:
                scored_list = []

            result = []
            for entry in scored_list:
                score = entry.get("similarity_score", 0)
                ticket_id = entry.get("ticket_id", "")

                original = None
                for c in capped:
                    try:
                        c_id = c.ticket_id if hasattr(c, 'ticket_id') else c.get('ticket_id', '')
                        if c_id == ticket_id:
                            original = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else c
                            break
                    except Exception:
                        pass

                if original:
                    result.append({
                        **original,
                        "similarity_score": score,
                        "similarity_label": entry.get("similarity_label", "Fair Match"),
                        "similarity_reason": entry.get("similarity_reason", ""),
                        "similarity_matching_fields": entry.get("similarity_matching_fields", []),
                    })

            return result

        except Exception as e:
            log.warning("CrossSystemFetch: LLM scoring failed", error=str(e))
            result = []
            for c in capped[:5]:
                try:
                    c_dict = dataclasses.asdict(c) if hasattr(c, '__dataclass_fields__') else c
                    result.append({
                        **c_dict,
                        "similarity_score": 0.50,
                        "similarity_label": "Fair Match",
                        "similarity_reason": "LLM scoring unavailable — keyword match",
                        "similarity_matching_fields": ["title"],
                    })
                except Exception:
                    pass
            return result
