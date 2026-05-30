"""Initialize the database and seed all data sources, CMDB, and SLA config."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.db.base import Base
from orchestrator.db.session import engine, AsyncSessionLocal
from orchestrator.db.models import SourceRegistry, CMDBTeamRegistry, SLAConfig
from sqlalchemy import select

DEMO_SOURCES = [
    {
        "source_id": "apache-spark-github",
        "display_name": "Apache Spark (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "apache/spark",
        "ticket_prefix": "SGH",
        "enabled": True,
    },
    {
        "source_id": "apache-spark-jira",
        "display_name": "Apache Spark (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "SPARK",
        "ticket_prefix": "SPARK",
        "enabled": True,
    },
    {
        "source_id": "apache-kafka-github",
        "display_name": "Apache Kafka (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_KAFKA_GITHUB_TOKEN",
        "project_key": "apache/kafka",
        "ticket_prefix": "KGH",
        "enabled": True,
    },
    {
        "source_id": "apache-kafka-jira",
        "display_name": "Apache Kafka (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_KAFKA_JIRA_TOKEN",
        "project_key": "KAFKA",
        "ticket_prefix": "KAFKA",
        "enabled": True,
    },
    {
        "source_id": "mozilla-firefox-bugzilla",
        "display_name": "Mozilla Firefox (Bugzilla)",
        "system_type": "bugzilla",
        "base_url": "https://bugzilla.mozilla.org",
        "auth_type": "bearer_token",
        "auth_secret_ref": "MOZILLA_FIREFOX_BUGZILLA_TOKEN",
        "project_key": "Firefox",
        "ticket_prefix": "BUG",
        "enabled": True,
    },
]

DEMO_CMDB = [
    {"component_name": "SQL", "team_name": "Apache Spark", "source_id": "apache-spark-jira"},
    {"component_name": "Core", "team_name": "Apache Spark", "source_id": "apache-spark-jira"},
    {"component_name": "MLlib", "team_name": "Apache Spark", "source_id": "apache-spark-jira"},
    {"component_name": "Streaming", "team_name": "Apache Spark", "source_id": "apache-spark-jira"},
    {"component_name": "PySpark", "team_name": "Apache Spark", "source_id": "apache-spark-github"},
    {"component_name": "Network", "team_name": "Apache Kafka", "source_id": "apache-kafka-jira"},
    {"component_name": "Replication", "team_name": "Apache Kafka", "source_id": "apache-kafka-jira"},
    {"component_name": "Streams", "team_name": "Apache Kafka", "source_id": "apache-kafka-jira"},
    {"component_name": "DOM", "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
    {"component_name": "JavaScript Engine", "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
    {"component_name": "Graphics", "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
]

DEMO_SLA = [
    {
        "tier_name": "standard",
        "p0_resolution_hours": 96,
        "p1_resolution_hours": 168,
        "p2_resolution_hours": 336,
        "p3_resolution_hours": 720,
        "at_risk_threshold_pct": 20,
    },
    {
        "tier_name": "premium",
        "p0_resolution_hours": 48,
        "p1_resolution_hours": 96,
        "p2_resolution_hours": 168,
        "p3_resolution_hours": 336,
        "at_risk_threshold_pct": 15,
    },
]


async def init():
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")

    async with AsyncSessionLocal() as db:
        print("\nSeeding data sources...")
        for src_data in DEMO_SOURCES:
            existing = await db.execute(
                select(SourceRegistry).where(SourceRegistry.source_id == src_data["source_id"])
            )
            if existing.scalar_one_or_none() is None:
                db.add(SourceRegistry(**src_data))
                print(f"  + {src_data['source_id']}")
            else:
                print(f"  ~ {src_data['source_id']} (already exists)")
        await db.commit()

        print("\nSeeding CMDB entries...")
        for cmdb_data in DEMO_CMDB:
            existing = await db.execute(
                select(CMDBTeamRegistry).where(CMDBTeamRegistry.component_name == cmdb_data["component_name"])
            )
            if existing.scalar_one_or_none() is None:
                db.add(CMDBTeamRegistry(**cmdb_data))
                print(f"  + {cmdb_data['component_name']} -> {cmdb_data['team_name']}")
            else:
                print(f"  ~ {cmdb_data['component_name']} (already exists)")
        await db.commit()

        print("\nSeeding SLA configs...")
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        for sla_data in DEMO_SLA:
            stmt = pg_insert(SLAConfig).values(**sla_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["tier_name"],
                set_={k: v for k, v in sla_data.items() if k != "tier_name"},
            )
            await db.execute(stmt)
            print(f"  + {sla_data['tier_name']}")
        await db.commit()

    print("\nDatabase initialization complete.")


if __name__ == "__main__":
    asyncio.run(init())
