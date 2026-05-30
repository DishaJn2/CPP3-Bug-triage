"""Seed real KB articles (Apache Spark, Kafka, Firefox) into the database."""
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
        "content": """Apache Spark SQL performance tuning involves several key strategies.

        Adaptive Query Execution (AQE): Enable with spark.sql.adaptive.enabled=true. AQE dynamically
        coalesces shuffle partitions, converts sort-merge joins to broadcast joins, and optimizes
        skew joins at runtime based on actual data statistics.

        Broadcast Hash Join: Use when one table is small enough to fit in memory. Set
        spark.sql.autoBroadcastJoinThreshold (default 10MB). Force with /*+ BROADCAST(table) */ hint.

        Partition Pruning: Dynamic partition pruning is enabled by default in Spark 3.x via
        spark.sql.optimizer.dynamicPartitionPruning.enabled. Ensures only relevant partitions
        are scanned.

        Columnar Storage: Use Parquet or ORC formats. Enable dictionary encoding and predicate pushdown.

        Memory Configuration: spark.sql.shuffle.partitions (default 200, tune to 2-3x cluster cores).
        spark.executor.memory, spark.memory.fraction (default 0.6), spark.memory.storageFraction.

        Common Issues: NullPointerException in SQL functions usually indicates null values in
        non-nullable columns. Use .na.fill() or coalesce() to handle nulls before aggregations.""",
        "url": "https://spark.apache.org/docs/latest/sql-performance-tuning.html",
        "space_key": "SPARK",
        "component": "SQL",
        "tags": ["sql", "performance", "aqe", "join", "partition", "tuning"],
        "last_modified": "2024-11-15",
    },
    {
        "article_id": "SPARK-KB-002",
        "title": "PySpark DataFrame API — Common Errors and Fixes",
        "content": """Common PySpark DataFrame errors and their resolutions.

        AnalysisException 'Column not found': Occurs when referencing columns from different
        DataFrames in a join without aliasing. Fix: alias DataFrames with .alias('df1') and
        reference columns as F.col('df1.column_name').

        NullPointerException in UDFs: Python UDFs don't handle None values by default. Always
        check for None at the start of UDF body or use pandas UDFs with vectorized operations.

        Py4JJavaError / Java heap space: Caused by collect() on large DataFrames or insufficient
        executor memory. Fix: increase spark.executor.memory, avoid collect() on large data,
        use .show() or write to storage instead.

        is_remote_only() TypeError: Occurs in Spark Connect mode when using legacy RDD-based APIs
        not supported in client mode. These APIs require direct cluster access. Check with
        spark.conf.get('spark.remote') to detect Connect mode.

        DataFrame.toPandas() memory error: Use pandas-on-Spark (pyspark.pandas) for large datasets
        instead of converting the entire DataFrame.

        Schema mismatch on union(): DataFrames must have identical schema including nullability.
        Use .unionByName(df, allowMissingColumns=True) in Spark 3.1+.""",
        "url": "https://spark.apache.org/docs/latest/api/python/getting_started/quickstart_df.html",
        "space_key": "SPARK",
        "component": "PySpark",
        "tags": ["pyspark", "dataframe", "errors", "nullpointer", "udf", "connect"],
        "last_modified": "2024-10-22",
    },
    {
        "article_id": "SPARK-KB-003",
        "title": "Spark Streaming — Fault Tolerance and Checkpointing",
        "content": """Spark Structured Streaming fault tolerance architecture and checkpointing guide.

        Checkpoint Location: Always set checkpointLocation for production streaming jobs.
        spark.writeStream.option('checkpointLocation', '/path/to/checkpoint'). The checkpoint
        stores offset logs and metadata to enable exactly-once semantics.

        Kafka Source Recovery: When recovering from failure, Spark reads the committed Kafka offset
        from the checkpoint. If the checkpoint is lost, start from 'latest' or 'earliest' based on
        tolerance for message loss vs reprocessing.

        State Store: Default is HDFSBackedStateStore. For performance, use RocksDB state store
        (spark.sql.streaming.stateStore.providerClass=RocksDBStateStoreProvider). Requires
        spark-sql-kafka connector on classpath.

        Trigger Intervals: Trigger.ProcessingTime('10 seconds') — micro-batch mode.
        Trigger.Continuous('1 second') — experimental low-latency mode.
        Trigger.Once() — runs one micro-batch and stops, useful for batch-style streaming.

        SupportsMetadataColumns: Kafka and file sources expose metadata columns (_topic, _partition,
        _offset, _timestamp). Access via df.withColumn('topic', F.col('_topic')). Only available
        in streaming DataFrames, not static reads.

        Common Issue — StreamingQueryException: Usually caused by schema evolution (new columns in
        source) or Kafka partition rebalancing. Enable spark.sql.streaming.schemaInference=true
        cautiously, or define explicit schema.""",
        "url": "https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html",
        "space_key": "SPARK",
        "component": "Streaming",
        "tags": ["streaming", "kafka", "checkpoint", "fault-tolerance", "state-store", "metadata"],
        "last_modified": "2024-09-30",
    },
    {
        "article_id": "SPARK-KB-004",
        "title": "MLlib — Model Training Failures and Memory Management",
        "content": """Apache Spark MLlib troubleshooting guide for training and inference issues.

        OutOfMemoryError during training: MLlib algorithms collect data to the driver during
        certain phases. Set spark.driver.memory to at least 4g for medium datasets. For gradient
        boosted trees, reduce spark.mllib.tree.maxBins or maxDepth to reduce memory footprint.

        Convergence Issues: If loss is not decreasing, check feature scaling. Use StandardScaler
        or MinMaxScaler before training linear models. Unscaled features cause gradient descent
        to oscillate.

        inferSchema in Pipelines: When saving and loading pipelines, schema inference can fail
        if the input DataFrame schema differs from training time. Always specify schema explicitly
        when reading data for inference.

        Digit strings as integers: A common data loading issue where '01234' is parsed as integer
        1234. Use schema with StringType for ID columns, or set inferSchema=False and define
        schema manually.

        Persistence: Save models with model.save(path). Load with PipelineModel.load(path).
        Model metadata is stored as JSON; binary data as Parquet in the 'data' subdirectory.

        Cross-Validation memory: CrossValidator trains k * numEstimators models. Reduce
        parallelism with parallelism=1 (sequential) if OOM, or reduce fold count.""",
        "url": "https://spark.apache.org/docs/latest/ml-guide.html",
        "space_key": "SPARK",
        "component": "MLlib",
        "tags": ["mllib", "ml", "training", "oom", "convergence", "pipeline", "inference"],
        "last_modified": "2024-08-14",
    },
    {
        "article_id": "SPARK-KB-005",
        "title": "Spark Core — RDD and Task Scheduling Troubleshooting",
        "content": """Spark Core task scheduling, RDD lineage, and executor issues.

        Task not serializable: All variables referenced inside map/filter lambdas must be
        serializable. Move non-serializable objects to local variables inside the lambda, or
        use broadcast variables for large read-only data.

        Skewed partitions: Identified by one task taking much longer than others in Spark UI.
        Fix: repartition on a high-cardinality column, use salting technique for skewed keys,
        or enable AQE skew join optimization.

        Lost executor / FetchFailedException: Occurs when an executor is killed (OOM, preemption)
        mid-shuffle. The fetch of shuffle data fails. Fix: increase executor memory, reduce
        spark.executor.cores to reduce memory pressure per executor, enable
        spark.shuffle.service.enabled for external shuffle service.

        Driver OutOfMemoryError: Caused by actions that collect data to driver (collect(),
        take(n), broadcast of large variable). Limit broadcast threshold or increase
        spark.driver.memory.

        NormalizeCTEIds: An internal Spark SQL optimizer step that assigns unique IDs to
        Common Table Expressions. Failures here indicate a query planning bug, typically
        triggered by deeply nested CTEs or CTEs referenced multiple times. Workaround:
        materialize intermediate CTEs as temp views.""",
        "url": "https://spark.apache.org/docs/latest/rdd-programming-guide.html",
        "space_key": "SPARK",
        "component": "Core",
        "tags": ["rdd", "scheduling", "executor", "oom", "shuffle", "serialization", "cte"],
        "last_modified": "2024-07-05",
    },
    {
        "article_id": "KAFKA-KB-001",
        "title": "Kafka Producer Configuration and Message Delivery Guarantees",
        "content": """Apache Kafka producer configuration for reliability and performance.

        Delivery Guarantees:
        - At most once: acks=0 (fire and forget)
        - At least once: acks=1 or acks=all, retries > 0
        - Exactly once: enable.idempotence=true, transactional.id set, acks=all

        Key Configuration:
        acks=all: Leader waits for all in-sync replicas to acknowledge. Safest but highest latency.
        retries=Integer.MAX_VALUE with delivery.timeout.ms=120000 for bounded retry window.
        max.in.flight.requests.per.connection=1 for strict ordering, or 5 with idempotence.

        Batching for Throughput:
        batch.size=65536 (64KB, default 16KB) — larger batches = better compression and throughput.
        linger.ms=20 — wait up to 20ms to fill batch before sending.
        compression.type=lz4 — good balance of CPU and compression ratio.

        Common Issues:
        RecordTooLargeException: message.max.bytes (broker) must be >= max.request.size (producer).
        TimeoutException: Check network connectivity, broker availability, and request.timeout.ms.
        NotLeaderForPartitionException: Transient during leader election. Retries handle automatically.""",
        "url": "https://kafka.apache.org/documentation/#producerconfigs",
        "space_key": "KAFKA",
        "component": "Producer",
        "tags": ["kafka", "producer", "acks", "idempotence", "batching", "delivery"],
        "last_modified": "2024-11-01",
    },
    {
        "article_id": "KAFKA-KB-002",
        "title": "Kafka Consumer Group Rebalancing — Causes and Mitigation",
        "content": """Understanding and reducing Kafka consumer group rebalances.

        What triggers rebalance: Consumer joins or leaves group, session.timeout.ms exceeded,
        max.poll.interval.ms exceeded (processing too slow), broker-side changes (partition increase).

        Sticky Assignor: Use partition.assignment.strategy=CooperativeStickyAssignor (Kafka 2.4+).
        Incremental cooperative rebalancing — consumers only revoke partitions being moved,
        not all partitions. Reduces stop-the-world effect dramatically.

        Tuning to prevent rebalance:
        session.timeout.ms=45000 (increase from default 10000 for unstable networks)
        heartbeat.interval.ms=15000 (must be < session.timeout.ms / 3)
        max.poll.interval.ms=600000 (increase if processing takes >5 min per poll)
        max.poll.records=100 (reduce if each record takes long to process)

        Static Group Membership: Assign group.instance.id to each consumer.
        Consumer can rejoin within session.timeout.ms without triggering rebalance.
        Useful for stateful consumers (e.g. Kafka Streams).

        Monitoring: Watch consumer_lag (kafka.consumer:type=consumer-fetch-manager-metrics)
        and rebalance_rate_avg metrics in JMX. Alert if rebalances exceed 1 per hour.""",
        "url": "https://kafka.apache.org/documentation/#consumerconfigs",
        "space_key": "KAFKA",
        "component": "Consumer",
        "tags": ["kafka", "consumer", "rebalance", "sticky", "session", "heartbeat", "lag"],
        "last_modified": "2024-10-10",
    },
    {
        "article_id": "KAFKA-KB-003",
        "title": "Kafka Streams State Store and RocksDB Tuning",
        "content": """Kafka Streams state store configuration and RocksDB optimization.

        State Store Types:
        - Persistent (default, RocksDB-backed): survives restarts, backed by changelog topic
        - In-memory: fast, data lost on restart, no changelog
        - Versioned: Kafka 3.5+, supports time-travel queries, backed by segments

        RocksDB Tuning for Streams:
        rocksdb.config.setter implementation to customize:
        setMaxWriteBufferNumber(4), setWriteBufferSize(64MB),
        setMaxBackgroundCompactions(4), setCompressionType(LZ4).

        Standby Replicas: num.standby.replicas=1 keeps a warm replica on another instance.
        Reduces recovery time after failure from minutes to seconds (just needs to catch up
        the lag since last sync).

        Interactive Queries: Use store.query(RangeQuery.withRange(from, to)) for range scans.
        For global stores, QueryableStoreTypes.keyValueStore() from any instance.

        Common Issues:
        RocksDB open failed: Only one process can open a RocksDB store. Ensure previous
        instance fully stopped. Check for lock files in streams application directory.
        State store too large: Enable log compaction on changelog topics. Set
        retention.ms=-1 and cleanup.policy=compact on internal changelog topics.
        Replication factor warning: Internal topics created with replication.factor
        from default.replication.factor broker config. Set to 3 for production.""",
        "url": "https://kafka.apache.org/documentation/streams/",
        "space_key": "KAFKA",
        "component": "Streams",
        "tags": ["kafka", "streams", "rocksdb", "state-store", "standby", "interactive-queries"],
        "last_modified": "2024-09-18",
    },
    {
        "article_id": "KAFKA-KB-004",
        "title": "Kafka Network and Replication Troubleshooting",
        "content": """Kafka broker networking and replication issue diagnosis.

        Under-Replicated Partitions (URP): kafka-topics.sh --describe --under-replicated-partitions.
        Caused by: slow follower, network partition, broker overload, disk I/O bottleneck.
        Fix: Check replica.lag.time.max.ms (default 30s). Increase for slow networks.

        Leader Election:
        Unclean leader election (unclean.leader.election.enable=false recommended) — enabling
        risks data loss. Preferred leader election runs automatically; trigger manually with
        kafka-leader-election.sh.

        Network Thread Tuning:
        num.network.threads=8 (increase for high-throughput brokers with many connections)
        num.io.threads=16 (scale with number of disks)
        socket.send.buffer.bytes=1048576 and socket.receive.buffer.bytes=1048576

        SSL/TLS Performance: SSL handshakes add ~1ms latency. Use ssl.engine.factory.class
        with OpenSSL engine for 3-5x better TLS throughput vs Java SSLEngine.

        Log Fabric / Link-State Issues: In multi-datacenter setups, use MirrorMaker2 or
        Cluster Linking. Monitor replication.bytes rate and consumer_lag on mirror topics.
        Alert on lag > 100k messages for time-sensitive pipelines.""",
        "url": "https://kafka.apache.org/documentation/#brokerconfigs",
        "space_key": "KAFKA",
        "component": "Replication",
        "tags": ["kafka", "replication", "network", "urp", "ssl", "leader-election", "broker"],
        "last_modified": "2024-08-28",
    },
    {
        "article_id": "FIREFOX-KB-001",
        "title": "Firefox JavaScript Engine — JIT Compilation and Memory Issues",
        "content": """Mozilla Firefox SpiderMonkey JIT engine troubleshooting.

        JIT Compilation Tiers: Interpreter → Baseline JIT → Ion JIT → Warp (FF 83+).
        Code is promoted based on call frequency. Deoptimization (bailout) happens when
        type assumptions are violated at runtime.

        Memory Leaks in JavaScript: Common causes — event listeners not removed, closure
        references to DOM nodes, forgotten timers (clearInterval!), circular references
        in old IE compatibility code. Use Firefox Memory tool (about:memory) or DevTools
        Memory panel to take heap snapshots and find leaks.

        Heap OOM Crash: javascript.options.mem.max limits JS heap (default ~1GB on 64-bit).
        Crashes logged to about:crashes. Minidump analyzed with minidump-stackwalk.

        Wasm Performance: Use SharedArrayBuffer + Atomics for multi-threaded Wasm.
        Requires COOP/COEP headers (Cross-Origin-Opener-Policy: same-origin,
        Cross-Origin-Embedder-Policy: require-corp).

        DOM Rendering Performance: Avoid layout thrashing (read, then write, not interleaved).
        Use requestAnimationFrame for visual updates. Compositor thread handles CSS transforms
        and opacity changes without main thread involvement.""",
        "url": "https://firefox-source-docs.mozilla.org/js/",
        "space_key": "FIREFOX",
        "component": "JavaScript Engine",
        "tags": ["firefox", "javascript", "jit", "spidermonkey", "memory", "wasm", "dom"],
        "last_modified": "2024-11-05",
    },
    {
        "article_id": "FIREFOX-KB-002",
        "title": "Firefox Graphics Pipeline — WebGL, WebGPU, and Rendering Bugs",
        "content": """Firefox graphics subsystem troubleshooting and configuration.

        Graphics Backend: Firefox uses WebRender (GPU-accelerated, Rust-based) by default on
        most platforms. about:support shows 'GRAPHICS' section with compositor type and GPU info.

        WebGL Issues: Enable WebGL debugging via WEBGL_debug_renderer_info extension.
        Common issues: context lost (GPU reset, OOM), shader compilation failure (driver bug),
        texture format mismatch. Check gl.getError() after each draw call in debug builds.

        WebGPU (experimental): Enable via dom.webgpu.enabled in about:config. Uses Wgpu (Rust)
        as backend. Validation layer catches API misuse. Dawn not used (unlike Chrome).

        Crash in Graphics: Graphics crashes written to about:crashes with signature containing
        'gl' or 'webrender'. Set MOZ_DISABLE_CONTENT_SANDBOX=1 to isolate GPU process crashes.
        Disable hardware acceleration in Settings → Performance as workaround.

        Display Scaling: HiDPI handled via device pixel ratio. layout.css.devPixelsPerPx in
        about:config overrides system DPI. Fractional scaling (1.25x, 1.5x) can cause blurry
        rendering — set gfx.webrender.dpi-factor to force integer scaling.

        Canvas Performance: OffscreenCanvas with transferControlToOffscreen() moves canvas
        rendering to worker thread. Significant improvement for games and data visualization.""",
        "url": "https://firefox-source-docs.mozilla.org/gfx/",
        "space_key": "FIREFOX",
        "component": "Graphics",
        "tags": ["firefox", "graphics", "webgl", "webgpu", "webrender", "gpu", "canvas"],
        "last_modified": "2024-10-20",
    },
    {
        "article_id": "FIREFOX-KB-003",
        "title": "Firefox DOM and CSS — Layout Bugs and Compatibility Issues",
        "content": """Firefox DOM, CSS layout engine (Gecko), and web compatibility issues.

        CSS Grid and Flexbox: Firefox has strong standards compliance. IE/Edge compatibility
        issues often surface when migrating to Firefox. Use MDN compatibility tables.
        Common: -webkit- prefixed properties not recognized, use unprefixed versions.

        Position Sticky: Works in Firefox but requires overflow:hidden not set on any ancestor.
        Use overflow:clip (CSS 2022) if clipping is needed with sticky positioning.

        Custom Elements / Shadow DOM: Firefox supports all of Web Components v1.
        Declarative Shadow DOM (DSD) requires Firefox 123+. Closed shadow roots prevent
        external JS access via attachShadow({mode:'closed'}).

        Event Handling Differences: Firefox fires pointercancel on scroll, unlike Chrome.
        Use pointer events API instead of mouse events for touch+mouse compat.
        DOMContentLoaded vs load: DOMContentLoaded fires when HTML parsed, load when all
        resources loaded. Don't use window.onload for non-resource-dependent initialization.

        Memory in DOM: Detached DOM nodes retained by JS references cause leaks.
        WeakRef and FinalizationRegistry (ES2021) allow weak references to DOM nodes
        that don't prevent GC.

        Scroll Restoration: history.scrollRestoration = 'manual' to control scroll
        position on back/forward navigation in SPAs.""",
        "url": "https://firefox-source-docs.mozilla.org/dom/",
        "space_key": "FIREFOX",
        "component": "DOM",
        "tags": ["firefox", "dom", "css", "layout", "gecko", "shadow-dom", "events"],
        "last_modified": "2024-09-12",
    },
]


async def seed_kb():
    from orchestrator.db.session import init_db, AsyncSessionLocal
    from orchestrator.db.repositories.kb_articles import insert_kb_article

    await init_db()
    async with AsyncSessionLocal() as session:
        count = 0
        for article in REAL_KB_ARTICLES:
            result = await insert_kb_article(session, article)
            if result:
                count += 1
                print(f"  + {article['article_id']} — {article['title'][:50]}")
            else:
                print(f"  ~ {article['article_id']} (already exists)")
        await session.commit()
    print(f"\nSeeded {count} KB articles.")


if __name__ == "__main__":
    asyncio.run(seed_kb())
