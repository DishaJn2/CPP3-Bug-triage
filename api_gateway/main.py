import re
import time
import uuid
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from .kafka_client import kafka_lifespan
from .routes import auth_router, cases_router, triage_router, settings_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with kafka_lifespan(app):
        yield


app = FastAPI(
    title="HPE Bug Triage API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    request.state.trace_id = trace_id
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - start) * 1000)
    log.info(
        "request",
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(triage_router)
app.include_router(settings_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "HPE Bug Triage API"}


@app.get("/mock/confluence/rest/api/content/search")
async def mock_confluence_search(cql: str = "", limit: int = 5):
    """Simulates Confluence CQL search API for POC."""
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.repositories.kb_articles import search_kb_articles

    match = re.search(r'text[~=]\s*["\']?([^"\'&]+)["\']?', cql)
    query = match.group(1).strip() if match else cql[:50]

    async with AsyncSessionLocal() as db:
        articles = await search_kb_articles(db, query, limit=limit)

    return {
        "results": [
            {
                "id": str(a.id),
                "type": "page",
                "title": a.title,
                "space": {"key": a.space_key},
                "_links": {"webui": a.url},
                "body": {"view": {"value": a.content[:500]}},
                "metadata": {
                    "labels": {"results": [{"name": t} for t in (a.tags or [])]}
                },
                "version": {"when": a.last_modified},
            }
            for a in articles
        ],
        "size": len(articles),
        "limit": limit,
    }


@app.get("/mock/confluence/rest/api/content/{page_id}")
async def mock_confluence_get(page_id: str):
    """Simulates Confluence single-page fetch."""
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.models import KBArticle
    from sqlalchemy import select

    try:
        pid = int(page_id)
    except ValueError:
        return {}

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(KBArticle).where(KBArticle.id == pid))
        article = result.scalar_one_or_none()

    if not article:
        return {}
    return {
        "id": str(article.id),
        "type": "page",
        "title": article.title,
        "space": {"key": article.space_key},
        "_links": {"webui": article.url},
    }


@app.get("/mock/customer-portal/cases")
async def mock_customer_cases(bug_keywords: str = "", limit: int = 3):
    """Simulates HPE Customer Portal API — returns customer cases by bug keywords."""
    from orchestrator.db.session import AsyncSessionLocal
    from orchestrator.db.models import CustomerCase
    from sqlalchemy import select

    keywords = [k.strip().lower() for k in bug_keywords.split(",") if k.strip()]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CustomerCase))
        all_cases = result.scalars().all()

    matched = []
    for case in all_cases:
        case_keywords = [k.lower() for k in (case.related_bug_keywords or [])]
        if not keywords or any(k in case_keywords for k in keywords):
            matched.append(case)

    return {
        "cases": [
            {
                "case_id": c.case_id,
                "customer": c.customer,
                "severity": c.severity,
                "title": c.title,
                "impact": c.impact or "",
                "opened_at": c.opened_at.isoformat() if c.opened_at else "",
                "status": c.status,
            }
            for c in matched[:limit]
        ],
        "total": len(matched),
    }
