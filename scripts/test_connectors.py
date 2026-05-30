"""Test each connector independently against real APIs."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.connectors.github_connector import GithubConnector
from orchestrator.connectors.jira_connector import JiraConnector
from orchestrator.connectors.bugzilla_connector import BugzillaConnector

DEMO_SOURCES = [
    {
        "source_id": "apache-spark-github",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "project_key": "apache/spark",
        "ticket_prefix": "SGH",
        "auth_secret_ref": "APACHE_SPARK_GITHUB_TOKEN",
        "connector_class": GithubConnector,
    },
    {
        "source_id": "apache-spark-jira",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "project_key": "SPARK",
        "ticket_prefix": "SPARK",
        "auth_secret_ref": "APACHE_SPARK_JIRA_TOKEN",
        "connector_class": JiraConnector,
    },
    {
        "source_id": "apache-kafka-github",
        "system_type": "github",
        "base_url": "https://api.github.com",
        "project_key": "apache/kafka",
        "ticket_prefix": "KGH",
        "auth_secret_ref": "APACHE_KAFKA_GITHUB_TOKEN",
        "connector_class": GithubConnector,
    },
    {
        "source_id": "apache-kafka-jira",
        "system_type": "jira_apache",
        "base_url": "https://issues.apache.org/jira",
        "project_key": "KAFKA",
        "ticket_prefix": "KAFKA",
        "auth_secret_ref": "APACHE_KAFKA_JIRA_TOKEN",
        "connector_class": JiraConnector,
    },
    {
        "source_id": "mozilla-firefox-bugzilla",
        "system_type": "bugzilla",
        "base_url": "https://bugzilla.mozilla.org",
        "project_key": "Firefox",
        "ticket_prefix": "BUG",
        "auth_secret_ref": "MOZILLA_FIREFOX_BUGZILLA_TOKEN",
        "connector_class": BugzillaConnector,
    },
]


async def test_connector(src: dict) -> tuple[bool, str]:
    cls = src["connector_class"]
    token = os.environ.get(src["auth_secret_ref"], "")
    connector = cls(
        source_id=src["source_id"],
        system_type=src["system_type"],
        base_url=src["base_url"],
        project_key=src["project_key"],
        ticket_prefix=src["ticket_prefix"],
        token=token,
    )

    print(f"\n[{src['source_id']}]")
    try:
        tickets = await connector.search("", max_results=3)
        if not tickets:
            return False, "search() returned 0 tickets"

        print(f"  Returned {len(tickets)} ticket(s)")
        for t in tickets:
            print(f"  - {t.ticket_id}: {t.title[:80]}")
        return True, f"{len(tickets)} tickets fetched"
    except Exception as e:
        return False, str(e)


async def main():
    print("=" * 60)
    print("HPE Bug Triage - Connector Test Suite")
    print("=" * 60)

    results = []
    for src in DEMO_SOURCES:
        ok, msg = await test_connector(src)
        results.append((src["source_id"], ok, msg))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    for source_id, ok, msg in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {source_id}: {msg}")

    print(f"\n{passed}/{len(DEMO_SOURCES)} connectors working", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
