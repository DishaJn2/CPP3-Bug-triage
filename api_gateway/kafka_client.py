import json
import structlog
from contextlib import asynccontextmanager
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError
from fastapi import FastAPI
from .config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_TRIAGE_REQUESTS

log = structlog.get_logger()


@asynccontextmanager
async def kafka_lifespan(app: FastAPI):
    producer = None
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        app.state.kafka_producer = producer
        log.info("Kafka producer started")
    except Exception as e:
        log.warning("Kafka unavailable, running without producer", error=str(e))
        app.state.kafka_producer = None

    yield

    if producer:
        try:
            await producer.stop()
        except Exception:
            pass


async def publish_triage_request(
    producer: AIOKafkaProducer | None,
    case_id: str,
    bug_id: str,
    source_id: str,
    engineer_id: str,
) -> bool:
    if producer is None:
        return False
    try:
        payload = {
            "case_id": case_id,
            "bug_id": bug_id,
            "source_id": source_id,
            "engineer_id": engineer_id,
        }
        await producer.send_and_wait(KAFKA_TOPIC_TRIAGE_REQUESTS, payload)
        return True
    except Exception as e:
        log.warning("Failed to publish triage request", error=str(e))
        return False
