import os
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "HPEBugTriageSecret2026XYZ")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/hpe_bugtriage")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TTL_BUGLIST_SECONDS = int(os.getenv("REDIS_TTL_BUGLIST_SECONDS", 120))
REDIS_TTL_PANEL_SECONDS = int(os.getenv("REDIS_TTL_PANEL_SECONDS", 120))
REDIS_TTL_CASE_SECONDS = int(os.getenv("REDIS_TTL_CASE_SECONDS", 120))
REDIS_TTL_TICKET_SECONDS = int(os.getenv("REDIS_TTL_TICKET_SECONDS", 120))
REDIS_TTL_RELATED_SECONDS = int(os.getenv("REDIS_TTL_RELATED_SECONDS", 1800))

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_TRIAGE_REQUESTS = os.getenv("KAFKA_TOPIC_TRIAGE_REQUESTS", "triage.requests")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "bugtriage-orchestrator")

ENABLE_LOCAL_PIPELINE_FALLBACK = os.getenv("ENABLE_LOCAL_PIPELINE_FALLBACK", "true").lower() == "true"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
