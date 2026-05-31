"""Seed real KB articles (Apache Spark, Kafka, Firefox, Hadoop, Flink, K8s) into the database."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

REAL_KB_ARTICLES = [
    {
        "article_id": "SPARK-KB-001",
        "title": "Spark SQL Performance Tuning Guide",
        "content": """Apache Spark SQL performance tuning involves several strategies.
        AQE (Adaptive Query Execution): enable with spark.sql.adaptive.enabled=true.
        NormalizeCTEIds is an internal Spark SQL optimizer step that assigns unique IDs
        to Common Table Expressions (CTEs). Failures in NormalizeCTEIds indicate a query
        planning bug, typically triggered by deeply nested CTEs or CTEs referenced multiple
        times. The broken CTE relation is introduced by NormalizeCTEIds when WithCTE nodes
        are nested. Workaround: materialize intermediate CTEs as temp views using
        createOrReplaceTempView(). InlineCTE rule may crash when CTERelationRefs are broken.
        Broadcast Hash Join: use when one table fits in memory.
        NullPointerException in SQL functions indicates null values in non-nullable columns.""",
        "url": "https://spark.apache.org/docs/latest/sql-performance-tuning.html",
        "space_key": "SPARK", "component": "SQL",
        "tags": ["sql", "cte", "optimizer", "normalizecteids", "inlinecte", "performance", "withcte"],
        "last_modified": "2024-11-15",
    },
    {
        "article_id": "SPARK-KB-002",
        "title": "PySpark DataFrame API Common Errors and Fixes",
        "content": """Common PySpark DataFrame errors and resolutions.
        is_remote_only() TypeError: occurs in Spark Connect mode when using legacy
        RDD-based APIs not supported in client mode. DataFrame methods behind
        is_remote_only() statically evaluate to Union type because of __getattr__
        property — the static typechecker cannot evaluate is_remote_only() which makes
        type annotation of relevant DataFrame methods be a Union of the property method
        or a Column. This causes typechecking failures. Check spark.conf.get('spark.remote')
        to detect Connect mode. AnalysisException column not found: alias DataFrames with
        .alias() and reference columns as F.col('df1.column_name'). NullPointerException
        in UDFs: check for None. Py4JJavaError heap space: increase spark.executor.memory.
        schema mismatch on union: use .unionByName(df, allowMissingColumns=True).""",
        "url": "https://spark.apache.org/docs/latest/api/python/getting_started/quickstart_df.html",
        "space_key": "SPARK", "component": "PySpark",
        "tags": ["pyspark", "is_remote_only", "connect", "dataframe", "typechecking", "union", "static"],
        "last_modified": "2024-10-22",
    },
    {
        "article_id": "SPARK-KB-003",
        "title": "Spark Structured Streaming Fault Tolerance and Checkpointing",
        "content": """Spark Structured Streaming fault tolerance and checkpointing guide.
        Checkpoint Location: always set checkpointLocation for production streaming jobs.
        SupportsMetadataColumns: Kafka and file sources expose metadata columns (_topic,
        _partition, _offset, _timestamp). DSv2 (Data Source V2) streaming sources must
        implement SupportsMetadataColumns interface to expose metadata. If DSv2 source
        does not implement SupportsMetadataColumns, accessing metadata columns throws
        AnalysisException. Kafka source recovery: reads committed Kafka offset from checkpoint.
        RocksDB state store: use for better streaming performance.
        StreamingQueryException: caused by schema evolution or Kafka partition rebalancing.""",
        "url": "https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html",
        "space_key": "SPARK", "component": "Streaming",
        "tags": ["streaming", "kafka", "checkpoint", "dsv2", "supportsmetadatacolumns", "metadata"],
        "last_modified": "2024-09-30",
    },
    {
        "article_id": "SPARK-KB-004",
        "title": "MLlib Model Training Failures and Memory Management",
        "content": """Apache Spark MLlib troubleshooting for training and inference.
        OutOfMemoryError during training: increase spark.driver.memory.
        inferSchema in Pipelines: specify schema explicitly when reading data for inference.
        Digit strings as integers: common data loading issue where '01234' is parsed as
        integer 1234. Use schema with StringType for ID columns, or set inferSchema=False.
        inferSchema should not infer digit strings that start with 0 as integer — this is
        a known MLlib bug. Use schema definition to force StringType for such columns.
        Cross-Validation memory: reduce parallelism with parallelism=1 if OOM.""",
        "url": "https://spark.apache.org/docs/latest/ml-guide.html",
        "space_key": "SPARK", "component": "MLlib",
        "tags": ["mllib", "ml", "training", "oom", "inference", "inferschema", "digit", "integer"],
        "last_modified": "2024-08-14",
    },
    {
        "article_id": "SPARK-KB-005",
        "title": "Spark Core RDD Task Scheduling and Optimizer Troubleshooting",
        "content": """Spark Core task scheduling, RDD lineage, and optimizer issues.
        NormalizeCTEIds: internal Spark SQL optimizer step assigning unique IDs to CTEs.
        Failures indicate query planning bugs triggered by deeply nested CTEs or CTEs
        referenced multiple times. InlineCTE optimizer rule crashes when CTERelationRefs
        are broken by NormalizeCTEIds. WithCTE nodes nesting causes broken CTE relations.
        Workaround: materialize intermediate CTEs as temp views with createOrReplaceTempView.
        Task not serializable: all variables in lambdas must be serializable.
        Skewed partitions: one task much longer — use AQE skew join optimization.
        FetchFailedException: executor killed mid-shuffle — increase executor memory.
        PushPredicateThroughNonJoin: optimizer rule that pushes filter predicates through
        non-join operations. AssertionError in PushPredicateThroughNonJoin when using
        Hive view with Project on Union — known optimizer bug.""",
        "url": "https://spark.apache.org/docs/latest/rdd-programming-guide.html",
        "space_key": "SPARK", "component": "Core",
        "tags": ["rdd", "cte", "normalizecteids", "inlinecte", "optimizer", "scheduling",
                 "pushpredicate", "union", "hive", "withcte"],
        "last_modified": "2024-07-05",
    },
    {
        "article_id": "SPARK-KB-006",
        "title": "Spark Declarative Pipelines and Primary Key Expectations",
        "content": """Spark Declarative Pipelines (formerly Delta Live Tables style) guide.
        Primary key check expectations: use expect() or expect_or_drop() to validate
        primary key uniqueness. enable primary key check as expectation using
        @dlt.expect_all() decorator. Declarative Pipelines enable primary key constraint
        checking as a pipeline expectation rather than post-hoc validation.
        inferSchema for streaming sources in declarative pipelines should be set carefully.
        Pipeline execution: each pipeline stage is a streaming or batch transformation.""",
        "url": "https://spark.apache.org/docs/latest/",
        "space_key": "SPARK", "component": "SQL",
        "tags": ["declarative", "pipelines", "primary-key", "expectation", "delta", "streaming"],
        "last_modified": "2024-06-10",
    },
    {
        "article_id": "KAFKA-KB-001",
        "title": "Kafka Producer Configuration and Delivery Guarantees",
        "content": """Apache Kafka producer configuration for reliability and performance.
        Delivery guarantees: at-most-once (acks=0), at-least-once (acks=1 or acks=all),
        exactly-once (enable.idempotence=true). acks=all: leader waits for all in-sync
        replicas. retries=Integer.MAX_VALUE with delivery.timeout.ms for bounded retry.
        Batching: batch.size=65536, linger.ms=20, compression.type=lz4.
        RecordTooLargeException: message.max.bytes must be >= max.request.size.
        TimeoutException: check network connectivity and request.timeout.ms.
        NotLeaderForPartitionException: transient during leader election.""",
        "url": "https://kafka.apache.org/documentation/#producerconfigs",
        "space_key": "KAFKA", "component": "Producer",
        "tags": ["kafka", "producer", "acks", "idempotence", "batching", "delivery", "timeout"],
        "last_modified": "2024-11-01",
    },
    {
        "article_id": "KAFKA-KB-002",
        "title": "Kafka Consumer Group Rebalancing and Lag",
        "content": """Kafka consumer group rebalancing causes and mitigation.
        CooperativeStickyAssignor: incremental cooperative rebalancing in Kafka 2.4+.
        session.timeout.ms=45000, heartbeat.interval.ms=15000, max.poll.interval.ms=600000.
        Static group membership: assign group.instance.id to avoid rebalance on restart.
        Consumer lag monitoring: kafka.consumer:type=consumer-fetch-manager-metrics.
        max.poll.records=100: reduce if each record takes long to process.
        Rebalance triggered by: consumer joins/leaves, session timeout exceeded,
        max.poll.interval.ms exceeded, partition count change.""",
        "url": "https://kafka.apache.org/documentation/#consumerconfigs",
        "space_key": "KAFKA", "component": "Consumer",
        "tags": ["kafka", "consumer", "rebalance", "lag", "session", "heartbeat", "sticky"],
        "last_modified": "2024-10-10",
    },
    {
        "article_id": "KAFKA-KB-003",
        "title": "Kafka Streams State Store and RocksDB Configuration",
        "content": """Kafka Streams state store and RocksDB optimization guide.
        RocksDB config: setMaxWriteBufferNumber(4), setWriteBufferSize(64MB).
        Standby replicas: num.standby.replicas=1 for fast recovery.
        Interactive queries: QueryableStoreTypes.keyValueStore() for global stores.
        RocksDB lock file issue: only one process can open a RocksDB store.
        State store too large: enable log compaction on changelog topics.
        Versioned state stores: Kafka 3.5+, supports time-travel queries.""",
        "url": "https://kafka.apache.org/documentation/streams/",
        "space_key": "KAFKA", "component": "Streams",
        "tags": ["kafka", "streams", "rocksdb", "state-store", "standby", "interactive"],
        "last_modified": "2024-09-18",
    },
    {
        "article_id": "KAFKA-KB-004",
        "title": "Kafka Network Replication and Under-Replicated Partitions",
        "content": """Kafka broker networking and replication troubleshooting.
        Under-Replicated Partitions: use kafka-topics.sh --under-replicated-partitions.
        Caused by slow follower, network partition, broker overload, disk I/O bottleneck.
        replica.lag.time.max.ms: increase for slow networks (default 30s).
        Unclean leader election: unclean.leader.election.enable=false recommended.
        num.network.threads=8, num.io.threads=16 for high-throughput brokers.
        SSL/TLS: use OpenSSL engine for better TLS throughput vs Java SSLEngine.
        MirrorMaker2 for multi-datacenter replication.""",
        "url": "https://kafka.apache.org/documentation/#brokerconfigs",
        "space_key": "KAFKA", "component": "Replication",
        "tags": ["kafka", "replication", "network", "urp", "ssl", "leader", "broker", "mirror"],
        "last_modified": "2024-08-28",
    },
    {
        "article_id": "FIREFOX-KB-001",
        "title": "Firefox SpiderMonkey JIT Engine Memory and Performance",
        "content": """Firefox SpiderMonkey JIT engine troubleshooting and optimization.
        JIT tiers: Interpreter, Baseline JIT, Ion JIT, Warp (FF 83+).
        Memory leaks: event listeners not removed, closure references to DOM nodes,
        forgotten timers, circular references. Use about:memory for heap snapshots.
        Heap OOM: javascript.options.mem.max limits JS heap (default ~1GB on 64-bit).
        WebAssembly: SharedArrayBuffer + Atomics for multi-threaded Wasm requires
        COOP/COEP headers. DOM rendering: avoid layout thrashing, use requestAnimationFrame.
        Compositor thread handles CSS transforms without main thread involvement.""",
        "url": "https://firefox-source-docs.mozilla.org/js/",
        "space_key": "FIREFOX", "component": "JavaScript Engine",
        "tags": ["firefox", "javascript", "jit", "spidermonkey", "memory", "wasm", "dom", "oom"],
        "last_modified": "2024-11-05",
    },
    {
        "article_id": "FIREFOX-KB-002",
        "title": "Firefox WebRender Graphics Pipeline and WebGL Issues",
        "content": """Firefox graphics subsystem troubleshooting and WebGL/WebGPU guide.
        WebRender: GPU-accelerated compositor, default on most platforms.
        WebGL: context lost (GPU reset, OOM), shader compilation failure (driver bug).
        WebGPU: enable via dom.webgpu.enabled in about:config. Uses Wgpu (Rust) backend.
        HiDPI: layout.css.devPixelsPerPx overrides system DPI.
        OffscreenCanvas: transferControlToOffscreen() moves rendering to worker thread.
        Graphics crashes: set MOZ_DISABLE_CONTENT_SANDBOX=1 to isolate GPU process.
        Disable hardware acceleration in Settings > Performance as workaround.""",
        "url": "https://firefox-source-docs.mozilla.org/gfx/",
        "space_key": "FIREFOX", "component": "Graphics",
        "tags": ["firefox", "graphics", "webgl", "webgpu", "webrender", "gpu", "canvas", "hiDPI"],
        "last_modified": "2024-10-20",
    },
    {
        "article_id": "FIREFOX-KB-003",
        "title": "Firefox DOM CSS Layout Bugs and Web Compatibility",
        "content": """Firefox DOM, CSS layout engine Gecko, and web compatibility issues.
        CSS Grid and Flexbox: strong standards compliance in Firefox.
        Position Sticky: requires overflow:hidden not set on any ancestor.
        Custom Elements Shadow DOM: Firefox supports Web Components v1 fully.
        Declarative Shadow DOM requires Firefox 123+.
        Event handling: Firefox fires pointercancel on scroll unlike Chrome.
        WeakRef and FinalizationRegistry: ES2021 weak references to DOM nodes.
        Scroll restoration: history.scrollRestoration = 'manual' for SPAs.
        DOMContentLoaded fires when HTML parsed, load when all resources loaded.""",
        "url": "https://firefox-source-docs.mozilla.org/dom/",
        "space_key": "FIREFOX", "component": "DOM",
        "tags": ["firefox", "dom", "css", "layout", "gecko", "shadow-dom", "events", "scroll"],
        "last_modified": "2024-09-12",
    },
    {
        "article_id": "HADOOP-KB-001",
        "title": "Apache Hadoop YARN ResourceManager and NodeManager Issues",
        "content": """Apache Hadoop YARN resource management troubleshooting.
        ResourceManager HA: use ZooKeeper for active/standby failover.
        NodeManager disk health: yarn.nodemanager.disk-health-checker.min-healthy-disks.
        Container launch failures: check nodemanager logs for OOM killer.
        YARN queue scheduling: CapacityScheduler vs FairScheduler configuration.
        Application timeout: yarn.resourcemanager.application.expiry.interval.
        Log aggregation: yarn.log-aggregation-enable=true for post-job log access.
        Memory: yarn.nodemanager.resource.memory-mb must match container allocation.""",
        "url": "https://hadoop.apache.org/docs/current/hadoop-yarn/hadoop-yarn-site/",
        "space_key": "HADOOP", "component": "YARN",
        "tags": ["hadoop", "yarn", "resourcemanager", "nodemanager", "container", "oom", "queue"],
        "last_modified": "2024-10-05",
    },
    {
        "article_id": "FLINK-KB-001",
        "title": "Apache Flink Checkpointing and State Backend Configuration",
        "content": """Apache Flink checkpointing, state backends, and fault tolerance.
        Checkpoint interval: env.enableCheckpointing(60000) for 1-minute intervals.
        RocksDB state backend: use for large state beyond JVM heap.
        Incremental checkpoints: reduce checkpoint size for large state.
        Exactly-once semantics: requires barriers to align across all input channels.
        Backpressure: monitor via Flink Web UI, indicates slow operators.
        Savepoints: manually triggered checkpoints for migration and upgrades.
        RestartStrategy: fixed-delay or exponential-backoff for fault tolerance.
        Watermarks: event-time processing requires proper watermark strategy.""",
        "url": "https://nightlies.apache.org/flink/flink-docs-master/",
        "space_key": "FLINK", "component": "Runtime",
        "tags": ["flink", "checkpoint", "rocksdb", "state", "exactly-once", "watermark", "backpressure"],
        "last_modified": "2024-09-25",
    },
    {
        "article_id": "K8S-KB-001",
        "title": "Kubernetes Pod Scheduling and Resource Management",
        "content": """Kubernetes pod scheduling, resource limits, and troubleshooting.
        OOMKilled: container exceeded memory limit — increase resources.limits.memory.
        CrashLoopBackOff: pod repeatedly crashing — check logs with kubectl logs.
        Pending pods: insufficient cluster resources or node affinity mismatch.
        Resource requests vs limits: always set both for proper scheduling.
        Node affinity: nodeSelector or affinity rules for pod placement.
        Taints and tolerations: prevent pods from scheduling on certain nodes.
        PodDisruptionBudget: ensure availability during node maintenance.
        HorizontalPodAutoscaler: scale based on CPU/memory or custom metrics.""",
        "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/",
        "space_key": "K8S", "component": "Scheduler",
        "tags": ["kubernetes", "k8s", "pod", "scheduling", "oom", "crashloop", "resources", "affinity"],
        "last_modified": "2024-11-10",
    },
]


async def seed_kb():
    from orchestrator.db.session import init_db, AsyncSessionLocal
    from orchestrator.db.repositories.kb_articles import insert_kb_article, get_all_kb_articles
    from sqlalchemy import select, func
    from orchestrator.db.models import KBArticle

    await init_db()
    async with AsyncSessionLocal() as session:
        inserted = 0
        for article in REAL_KB_ARTICLES:
            result = await insert_kb_article(session, article)
            if result:
                inserted += 1
                print(f"  + {article['article_id']} — {article['title'][:50]}")
            else:
                print(f"  ~ {article['article_id']} (already exists)")
        await session.commit()

        total = await session.scalar(select(func.count()).select_from(KBArticle))

    print(f"\nInserted {inserted} new KB articles.")
    print(f"Total KB articles in DB: {total}")


if __name__ == "__main__":
    asyncio.run(seed_kb())
