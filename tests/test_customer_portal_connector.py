import httpx

from orchestrator.connectors import customer_portal_connector as portal_module
from orchestrator.connectors.customer_portal_connector import CustomerPortalConnector


def make_connector():
    return CustomerPortalConnector(
        source_id="public-signals",
        system_type="customer_portal",
        base_url="",
        project_key="",
        ticket_prefix="",
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_customer_portal_returns_no_fake_cases_when_api_unavailable(monkeypatch):
    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("network unavailable")

    monkeypatch.setattr(portal_module.httpx, "AsyncClient", FailingClient)

    connector = make_connector()
    results = __import__("asyncio").run(connector.search(
        "StorageController NPE",
        primary_ticket={"title": "StorageController NPE"},
    ))

    assert results == []
    assert "CASE-2891" not in [item.ticket_id for item in results]
    assert connector.last_error


def test_customer_signal_results_normalize_into_expected_shape(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            if "algolia" in url:
                return FakeResponse({
                    "hits": [{
                        "objectID": "42",
                        "title": "StorageController NPE discussion",
                        "author": "hn-dev",
                        "points": 130,
                        "num_comments": 12,
                        "url": "https://news.ycombinator.com/item?id=42",
                    }]
                })
            return FakeResponse({
                "items": [{
                    "question_id": 99,
                    "title": "StorageController allocate throws NPE",
                    "owner": {"display_name": "so-dev"},
                    "score": 4,
                    "view_count": 500,
                    "is_answered": True,
                    "body": "<p>Provisioning fails for users.</p>",
                    "link": "https://stackoverflow.com/questions/99",
                }]
            })

    monkeypatch.setattr(portal_module.httpx, "AsyncClient", FakeClient)

    connector = make_connector()
    results = __import__("asyncio").run(connector.search(
        "StorageController NPE",
        max_results=5,
        primary_ticket={
            "title": "StorageController NPE during provisioning",
            "component": "StorageController",
        },
    ))
    signals = [item.signal_metadata for item in results]

    assert {signal["source"] for signal in signals} == {
        "Hacker News", "Stack Overflow"}
    hn = next(signal for signal in signals if signal["source"] == "Hacker News")
    so = next(signal for signal in signals if signal["source"] == "Stack Overflow")
    assert hn["severity"] == "P1"
    assert so["severity"] == "P2"
    assert hn["customer_name"] == "hn-dev"
    assert so["status"] == "answered"
    assert 0.0 <= hn["signal_score"] <= 1.0
