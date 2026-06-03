import asyncio
import json
import os
import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from dotenv import load_dotenv
from .orchestrator import TaskOrchestrator

load_dotenv()
log = structlog.get_logger()


async def consume_triage_requests():
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC_TRIAGE_REQUESTS", "triage.requests")
    group_id = os.getenv("KAFKA_CONSUMER_GROUP", "bugtriage-orchestrator")

    orchestrator = TaskOrchestrator()

    while True:
        consumer = None
        try:
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=bootstrap,
                group_id=group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                session_timeout_ms=45000,
                heartbeat_interval_ms=10000,
                max_poll_interval_ms=300000,
            )
            await consumer.start()
            log.info("Kafka consumer started", topic=topic, group=group_id)

            async for msg in consumer:
                try:
                    payload = msg.value
                    case_id = payload.get("case_id", "")
                    bug_id = payload.get("bug_id", "")
                    source_id = payload.get("source_id", "")
                    engineer_id = payload.get("engineer_id", "")

                    log.info("Processing triage request", case_id=case_id, bug_id=bug_id)
                    await orchestrator.run(case_id, bug_id, source_id, engineer_id)
                    await consumer.commit()
                except Exception as e:
                    log.error("Error processing message", error=str(e), payload=str(msg.value))

        except KafkaError as e:
            log.warning("Kafka consumer error, retrying in 10s", error=str(e))
            await asyncio.sleep(10)
        except Exception as e:
            log.error("Unexpected consumer error", error=str(e))
            await asyncio.sleep(10)
        finally:
            if consumer:
                try:
                    await consumer.stop()
                except Exception:
                    pass
