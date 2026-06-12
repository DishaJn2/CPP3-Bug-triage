"""Initialize the database and seed all data sources, CMDB, SLA config, users, and customer cases."""
import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.db.base import Base
from orchestrator.db.session import engine, AsyncSessionLocal, ensure_runtime_schema
from orchestrator.db.models import (
    Base, SourceRegistry, CMDBTeamRegistry, SLAConfig, UserRole, CustomerCase,
    SystemGroupRegistry, BugGroupMapping
)
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
        "enabled": False,
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
        "enabled": False,
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
        "enabled": False,
    },
    {
        "source_id": "apache-flink-github",
        "display_name": "Apache Flink — GitHub Issues",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_type": "pat",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "apache/flink",
        "ticket_prefix": "FGH",
        "enabled": False,
    },
    {
        "source_id": "apache-hadoop-jira",
        "display_name": "Apache Hadoop — Apache JIRA",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "HADOOP",
        "ticket_prefix": "HADOOP",
        "enabled": False,
    },
    {
        "source_id": "apache-hive-jira",
        "display_name": "Apache Hive — Apache JIRA",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "HIVE",
        "ticket_prefix": "HIVE",
        "enabled": False,
    },
    {
        "source_id": "kubernetes-github",
        "display_name": "Kubernetes — GitHub Issues",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_type": "pat",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "kubernetes/kubernetes",
        "ticket_prefix": "K8S",
        "enabled": False,
    },
    {
        "source_id": "vscode-github",
        "display_name": "VS Code — GitHub Issues",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_type": "pat",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "microsoft/vscode",
        "ticket_prefix": "VGH",
        "enabled": False,
    },
    {
        "source_id": "apache-flink-jira",
        "display_name": "Apache Flink — Apache JIRA",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_type": "bearer_token",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "FLINK",
        "ticket_prefix": "FLINK",
        "enabled": False,
    },
    {
        "source_id":       "hpe-confluence",
        "display_name":    "HPE Engineering KB (Confluence)",
        "system_type":     "confluence",
        "base_url":        "https://cpp3-hpe.atlassian.net/wiki",
        "auth_type":       "basic",
        "auth_secret_ref": "CONFLUENCE_API_TOKEN",
        "project_key":     "HPEKB",
        "ticket_prefix":   "CONF",
        "enabled": False,
    },
    {
        "source_id": "hpe-customer-portal",
        "display_name": "HPE Customer Portal (Cases)",
        "system_type": "customer_portal",
        "base_url": "http://localhost:8000/mock/customer-portal",
        "auth_type": "none",
        "auth_secret_ref": "",
        "project_key": "",
        "ticket_prefix": "CASE",
        "enabled": False,
    },
]

DEMO_CMDB = [
    {"component_name": "SQL",          "team_name": "Apache Spark",   "source_id": "apache-spark-jira"},
    {"component_name": "Core",         "team_name": "Apache Spark",   "source_id": "apache-spark-jira"},
    {"component_name": "MLlib",        "team_name": "Apache Spark",   "source_id": "apache-spark-jira"},
    {"component_name": "Streaming",    "team_name": "Apache Spark",   "source_id": "apache-spark-jira"},
    {"component_name": "PySpark",      "team_name": "Apache Spark",   "source_id": "apache-spark-github"},
    {"component_name": "Network",      "team_name": "Apache Kafka",   "source_id": "apache-kafka-jira"},
    {"component_name": "Replication",  "team_name": "Apache Kafka",   "source_id": "apache-kafka-jira"},
    {"component_name": "Streams",      "team_name": "Apache Kafka",   "source_id": "apache-kafka-jira"},
    {"component_name": "DOM",          "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
    {"component_name": "JavaScript Engine", "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
    {"component_name": "Graphics",     "team_name": "Mozilla Firefox", "source_id": "mozilla-firefox-bugzilla"},
    {"component_name": "YARN",         "team_name": "Hadoop YARN",    "source_id": "apache-hadoop-jira", "escalation_contact": "dev@hadoop.apache.org"},
    {"component_name": "Runtime",      "team_name": "Flink Runtime",  "source_id": "apache-flink-jira", "escalation_contact": "dev@flink.apache.org"},
    {"component_name": "Scheduler",    "team_name": "Kubernetes SIG", "source_id": "kubernetes-github", "escalation_contact": "sig-scheduling@kubernetes.io"},
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

DEMO_USERS = [
    {"email": "disha@hpe.com",     "password": "password123", "role": "engineer",  "display_name": "Disha Jain"},
    {"email": "admin@hpe.com",     "password": "admin123",    "role": "admin",     "display_name": "Admin User"},
    {"email": "customer@acme.com", "password": "customer123", "role": "customer",  "display_name": "Acme Customer"},
    {"email": "exec@hpe.com",      "password": "exec123",     "role": "executive", "display_name": "HPE Executive"},
]
MOCK_CUSTOMER_CASES = [
    {
        "case_id": "CASE-10041",
        "customer": "Acme Corporation",
        "severity": "Critical",
        "title": "CTE query optimizer crash blocking production ETL pipeline",
        "related_bug_keywords": ["NormalizeCTEIds", "InlineCTE", "CTE", "optimizer"],
        "impact": "Production ETL pipeline down. 3 data engineers blocked. Revenue reporting delayed.",
        "opened_at": datetime(2026, 5, 28, 9, 0, 0, tzinfo=timezone.utc),
        "status": "Open",
    },
    {
        "case_id": "CASE-10038",
        "customer": "GlobalTech Industries",
        "severity": "High",
        "title": "PySpark DataFrame type annotation failures in CI pipeline",
        "related_bug_keywords": ["is_remote_only", "DataFrame", "typechecking", "Union"],
        "impact": "CI/CD blocked for 2 teams. 15 engineers unable to merge PRs.",
        "opened_at": datetime(2026, 5, 27, 14, 0, 0, tzinfo=timezone.utc),
        "status": "Open",
    },
    {
        "case_id": "CASE-10035",
        "customer": "DataStream Analytics",
        "severity": "High",
        "title": "Structured streaming metadata columns not accessible from DSv2 source",
        "related_bug_keywords": ["SupportsMetadataColumns", "DSv2", "streaming", "metadata"],
        "impact": "Real-time analytics dashboard missing metadata. Customer SLA at risk.",
        "opened_at": datetime(2026, 5, 26, 11, 0, 0, tzinfo=timezone.utc),
        "status": "Open",
    },
    {
        "case_id": "CASE-10029",
        "customer": "FinTech Solutions",
        "severity": "Medium",
        "title": "Kafka consumer group rebalancing causing processing delays",
        "related_bug_keywords": ["consumer", "rebalance", "kafka", "session"],
        "impact": "Payment processing latency increased 3x during rebalance events.",
        "opened_at": datetime(2026, 5, 24, 8, 0, 0, tzinfo=timezone.utc),
        "status": "Open",
    },
    {
        "case_id": "CASE-10021",
        "customer": "CloudBase Corp",
        "severity": "Medium",
        "title": "Firefox WebGL context lost on GPU-intensive dashboards",
        "related_bug_keywords": ["WebGL", "context", "GPU", "firefox", "graphics"],
        "impact": "Analytics dashboards crash on Firefox. 200 users affected.",
        "opened_at": datetime(2026, 5, 22, 16, 0, 0, tzinfo=timezone.utc),
        "status": "In Progress",
    },
]

ADDITIONAL_SOURCES = [
    # More Apache JIRA projects — zero new code
    {
        "source_id": "apache-zookeeper-jira",
        "display_name": "Apache ZooKeeper (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "ZOOKEEPER",
        "ticket_prefix": "ZOOKEEPER",
        "enabled": False,
    },
    {
        "source_id": "apache-cassandra-jira",
        "display_name": "Apache Cassandra (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "CASSANDRA",
        "ticket_prefix": "CASSANDRA",
        "enabled": False,
    },
    {
        "source_id": "apache-beam-jira",
        "display_name": "Apache Beam (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "project_key": "BEAM",
        "ticket_prefix": "BEAM",
        "enabled": False,
    },
    
    # Jenkins JIRA — zero new code, same connector
    {
        "source_id": "jenkins-jira",
        "display_name": "Jenkins (JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.jenkins.io",
        "auth_secret_ref": "",
        "project_key": "JENKINS",
        "ticket_prefix": "JENKINS",
        "enabled": False,
    },
    
    # Red Hat JIRA — zero new code
    {
        "source_id": "redhat-jira-wildfly",
        "display_name": "WildFly / JBoss (Red Hat JIRA)",
        "system_type": "jira_apache",
        "base_url": "https://issues.redhat.com",
        "auth_secret_ref": "",
        "project_key": "WFLY",
        "ticket_prefix": "WFLY",
        "enabled": False,
    },
    
    # Linux Kernel Bugzilla — zero new code, same BugzillaConnector
    {
        "source_id": "linux-kernel-bugzilla",
        "display_name": "Linux Kernel (Bugzilla)",
        "system_type": "bugzilla",
        "base_url": "https://bugzilla.kernel.org",
        "auth_secret_ref": "",
        "project_key": "Drivers",
        "ticket_prefix": "BUG",
        "enabled": False,
    },
    
    # More GitHub repos — zero new code, same GithubConnector
    {
        "source_id": "elastic-elasticsearch-github",
        "display_name": "Elasticsearch (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "elastic/elasticsearch",
        "ticket_prefix": "ES",
        "enabled": False,
    },
    {
        "source_id": "netty-github",
        "display_name": "Netty (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "netty/netty",
        "ticket_prefix": "NGH",
        "enabled": False,
    },
    {
        "source_id": "grpc-java-github",
        "display_name": "gRPC Java (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "grpc/grpc-java",
        "ticket_prefix": "GRPC",
        "enabled": False,
    },
    {
        "source_id": "prometheus-github",
        "display_name": "Prometheus (GitHub)",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "project_key": "prometheus/prometheus",
        "ticket_prefix": "PGH",
        "enabled": False,
    },
]
async def init():
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_runtime_schema()
    print("Tables created.")

    async with AsyncSessionLocal() as db:
        print("\nSeeding data sources...")
        for src_data in DEMO_SOURCES + ADDITIONAL_SOURCES:
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

        print("\nSeeding demo users...")
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        user_count_result = await db.execute(select(UserRole))
        existing_users = list(user_count_result.scalars().all())
        if not existing_users:
            for u in DEMO_USERS:
                user = UserRole(
                    user_id=u["email"],
                    role=u["role"],
                    password_hash=pwd_ctx.hash(u["password"]),
                    display_name=u["display_name"],
                )
                db.add(user)
                print(f"  + {u['email']} ({u['role']})")
            await db.commit()
        else:
            print(f"  ~ {len(existing_users)} users already exist, skipping seed")

        print("\nSeeding customer cases...")
        for case_data in MOCK_CUSTOMER_CASES:
            existing = await db.execute(
                select(CustomerCase).where(CustomerCase.case_id == case_data["case_id"])
            )
            if existing.scalar_one_or_none() is None:
                db.add(CustomerCase(**case_data))
                print(f"  + {case_data['case_id']} — {case_data['customer']}")
            else:
                print(f"  ~ {case_data['case_id']} (already exists)")
        await db.commit()

    print("\nDatabase initialization complete.")


if __name__ == "__main__":
    asyncio.run(init())
