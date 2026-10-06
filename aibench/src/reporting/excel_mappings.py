"""
Excel Mappings for Benchmark Report Generation.

Maps build_history.json metric keys to the sub-test descriptions
found in the QA_Data_Template.xlsx template (column B).

Structure:
    BENCHMARK_METRIC_MAPPINGS = {
        'benchmark_name': {
            'metric_key_in_build_history': 'sub_test_text_in_template_column_B',
            ...
        },
        ...
    }

The generator uses these mappings to locate the correct row in the
template by scanning column B for matching text, then writes the
mean value into the "QLI 2.0 GA Final Value" column (C), the
auto-inferred unit into the "Unit" column (D), and leaves the
"Notes / Caveats" column (E) blank.
"""

# ---------------------------------------------------------------------------
# Device tab name mapping
# Maps device codename → Excel sheet/tab name in the template
# ---------------------------------------------------------------------------
DEVICE_TAB_NAMES = {
    "IQ-9075": "IQ-9075",
    "SA8775P": "SA8775P",
    "SA8295P": "SA8295P",
    "default": "IQ-9075",
}

# ---------------------------------------------------------------------------
# Column layout in the template
# ---------------------------------------------------------------------------
# Column C  → QLI 2.0 GA Final Value  (populated with mean of all runs)
# Column D  → Unit                    (auto-inferred from metric key)
# Column E  → Notes / Caveats         (left blank)

# ---------------------------------------------------------------------------
# Unit inference — ordered list of (substring_pattern, unit_string) pairs.
# The first matching pattern wins.  Matching is case-insensitive against the
# metric key.
# ---------------------------------------------------------------------------
UNIT_PATTERNS = [
    # Latency / time suffixes
    ("_ns",          "ns"),
    ("_us",          "µs"),
    ("_ms",          "ms"),
    ("_sec",         "sec"),
    ("_time",        "sec"),
    # Throughput / bandwidth
    ("_mib",         "MiB/s"),
    ("mib_",         "MiB/s"),
    ("_rate",        "MB/s"),
    ("_plateau",     "MB/s"),
    ("ramspeed",     "MB/s"),
    ("bw_mem",       "MB/s"),
    # Benchmark scores
    ("glmark2",      "score"),
    ("unixbench",    "score"),
    ("coremark_pro", "score"),
    # Iterations
    ("coremark",     "iterations/sec"),
    # OS-level ops (actually time_us — microseconds per operation, lower is better)
    ("osbench",      "µs"),
    # Scheduler / IPC (msg/sec throughput, higher is better)
    ("sched_ipc",    "msg/sec"),
    ("hackbench",    "msg/sec"),
]

# ---------------------------------------------------------------------------
# Benchmark → metric → template sub-test text mappings
# ---------------------------------------------------------------------------
# The value is the text that appears in column B of the template.
# Matching is case-insensitive and uses substring search as fallback.
# ---------------------------------------------------------------------------

BENCHMARK_METRIC_MAPPINGS = {

    # -----------------------------------------------------------------------
    # CoreMark
    # -----------------------------------------------------------------------
    "coremark": {
        "coremark_default": "Iterations/sec",
    },

    # -----------------------------------------------------------------------
    # CoreMark Pro
    # -----------------------------------------------------------------------
    "coremark_pro": {
        "coremark_pro_multi_core":  "Multi-core",
        "coremark_pro_single_core": "Single-core",
        # Scaling = multi / single
        # "coremark_pro_scaling": "Scaling",  # derived, not directly in JSON
    },

    # -----------------------------------------------------------------------
    # Sysbench
    # Template rows (column B):
    #   "CPU total time (Lower is better)"
    #   "Memory bandwidth (Higher is better)"
    #   "Total thread time (Lower is better)"
    #   "Mutex total time (Lower is better)"
    # -----------------------------------------------------------------------
    "sysbench": {
        # CPU
        "sysbench_cpu_prime_single_test":           "CPU total time (Lower is better)",
        "sysbench_cpu_prime_multi_test":            "CPU total time (Lower is better)",
        # Memory bandwidth — use seq read MiB/s as the primary bandwidth metric
        "sysbench_memory_seq_read_test_data_transferred_mib":  "Memory bandwidth (Higher is better)",
        # Threads
        "sysbench_threads_scheduler_test":          "Total thread time (Lower is better)",
        # Mutex
        "sysbench_mutex_contention_test":           "Mutex total time (Lower is better)",
    },

    # -----------------------------------------------------------------------
    # TIOBench
    # Template rows (column B):
    #   "Sequential Write (256 MiB/thread at 512 threads)"
    #   "Sequential Read (256 MiB/thread at 512 threads)"
    #   "Random Write (64 MiB/thread at 4 KiB)"
    #   "Random Read (64 MiB/thread at 4 KiB)"
    # -----------------------------------------------------------------------
    "tiobench": {
        "sequential_write_rate": "Sequential Write",
        "sequential_read_rate":  "Sequential Read",
        "random_write_rate":     "Random Write",
        "random_read_rate":      "Random Read",
        "mixed_write_rate":      "Mixed Write",
        "mixed_read_rate":       "Mixed Read",
    },

    # -----------------------------------------------------------------------
    # GLMark2
    # Template rows (column B):
    #   "glmark2 (default resolution)"
    #   "glmark2 1920x1080"
    #   "glmark2 offscreen"
    #   "glmark2 offscreen 1920x1080"
    # -----------------------------------------------------------------------
    "glmark2": {
        "glmark2_default":            "glmark2 (default resolution)",
        "glmark2_1920x1080":          "glmark2 1920x1080",
        "glmark2_offscreen":          "glmark2 offscreen",
        "glmark2_offscreen_1920x1080": "glmark2 offscreen 1920x1080",
    },

    # -----------------------------------------------------------------------
    # UnixBench
    # Template rows (column B):
    #   "1x / Single parallel copy"
    #   "8x / Eight parallel copies"
    # -----------------------------------------------------------------------
    "unixbench": {
        "unixbench_single_core": "1x / Single parallel copy",
        "unixbench_multi_core":  "8x / Eight parallel copies",
    },

    # -----------------------------------------------------------------------
    # bw_mem
    # Template rows (column B): rd, frd, wr, fwr, cp, bcopy, rdwr
    # We use the plateau value as the representative metric.
    # -----------------------------------------------------------------------
    "bw_mem": {
        "bw_mem_rd_plateau":    "rd",
        "bw_mem_frd_plateau":   "frd",
        "bw_mem_wr_plateau":    "wr",
        "bw_mem_fwr_plateau":   "fwr",
        "bw_mem_cp_plateau":    "cp",
        "bw_mem_rdwr_plateau":  "rdwr",
    },

    # -----------------------------------------------------------------------
    # OSBench
    # Template rows (column B):
    #   "mem_alloc"
    #   "launch_programs"
    #   "create_files"
    #   "create_processes"
    #   "create_threads"
    # -----------------------------------------------------------------------
    "osbench": {
        "osbench_launch_programs":  "launch_programs",
        "osbench_create_files":     "create_files",
        "osbench_create_processes": "create_processes",
        "osbench_create_threads":   "create_threads",
    },

    # -----------------------------------------------------------------------
    # Hackbench
    # Template rows (column B): "Total time"
    # sched_ipc_default is the primary throughput metric (msg/sec).
    # -----------------------------------------------------------------------
    "hackbench": {
        "sched_ipc_default":          "Total time",
        "sched_ipc_heavy":            "Per thread time",
        "sched_ipc_sockets_extreme":  "Total time",
    },

    # -----------------------------------------------------------------------
    # RAMSpeed
    # Template rows (column B):
    #   "INTmark average"
    #   "INTmark writing (32768 KB block)"
    #   "INTmark reading (32768 KB block)"
    #   "FLOATmark writing (32768 KB block)"
    #   "FLOATmark reading (32768 KB block)"
    # -----------------------------------------------------------------------
    "ramspeed": {
        "ramspeed_single_b3_integer_average":   "INTmark average",
        "ramspeed_single_b1_intmark_writing":   "INTmark writing (32768 KB block)",
        "ramspeed_single_b2_intmark_reading":   "INTmark reading (32768 KB block)",
        "ramspeed_single_b4_floatmark_writing": "FLOATmark writing (32768 KB block)",
        "ramspeed_single_b5_floatmark_reading": "FLOATmark reading (32768 KB block)",
    },

    # -----------------------------------------------------------------------
    # lat_mem_rd
    # Template rows (column B): varies — use keyword matching
    # -----------------------------------------------------------------------
    "lat_mem_rd": {
        "lat_mem_rd_default_overall_plateau_ns": "Overall plateau",
        "lat_mem_rd_default_iter1_plateau_ns":   "Iter 1 plateau",
        "lat_mem_rd_default_iter2_plateau_ns":   "Iter 2 plateau",
        "lat_mem_rd_default_iter3_plateau_ns":   "Iter 3 plateau",
    },
}

# ---------------------------------------------------------------------------
# Benchmark section header text (column A in the template)
# Used to disambiguate rows when the same sub-test text appears in
# multiple benchmark sections.
# ---------------------------------------------------------------------------
BENCHMARK_SECTION_HEADERS = {
    "coremark":     ["CoreMark", "Coremark"],
    "coremark_pro": ["CoreMark Pro", "Coremark Pro"],
    "sysbench":     ["Sysbench"],
    "tiobench":     ["Tiobench", "TIOBench"],
    "glmark2":      ["GLmark2", "GLMark2", "glmark2"],
    "unixbench":    ["UnixBench"],
    "bw_mem":       ["bw_mem"],
    "osbench":      ["osbench", "OSBench"],
    "hackbench":    ["Hackbench"],
    "ramspeed":     ["RAMSpeed", "Ramspeed"],
    "lat_mem_rd":   ["lat_mem_rd", "Memory Latency"],
}