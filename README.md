# HPE Bug Triage System

Agentic bug triage system with multi-source connectors and AI pipeline.

## Setup

1. Copy environment template and fill in your values:
   Create a .env file with these variables:

   GROQ_API_KEY=get from console.groq.com
   APACHE_SPARK_GITHUB_TOKEN=GitHub PAT with public_repo scope
   APACHE_KAFKA_GITHUB_TOKEN=same GitHub PAT
   JWT_SECRET=any long random string
   POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hpe_bugtriage
   REDIS_URL=redis://localhost:6379/0
   KAFKA_BOOTSTRAP_SERVERS=localhost:9092
   ENABLE_LOCAL_PIPELINE_FALLBACK=true
   GROQ_MODEL=llama-3.3-70b-versatile

2. Start infrastructure:
   docker-compose -f docker-compose.dev.yml up -d

3. Install and initialize:
   pip install -r requirements.txt
   python -m scripts.init_db

4. Run backend:
   uvicorn api_gateway.main:app --reload --host 0.0.0.0 --port 8000

5. Run frontend:
   cd frontend && npm install && npm run dev

## Tech Stack
- Backend: FastAPI, PostgreSQL, Redis, Kafka, Groq LLM
- Frontend: React, Vite
- Connectors: Apache Spark JIRA, Apache Spark GitHub, 
              Apache Kafka JIRA, Apache Kafka GitHub, 
              Mozilla Firefox Bugzilla
