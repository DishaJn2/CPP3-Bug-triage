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
