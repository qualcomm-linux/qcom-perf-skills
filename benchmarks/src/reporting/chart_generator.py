"""
chart_generator.py - Generate data and configuration for HTML Chart.js visualizations

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
from typing import Any, Dict, List

def generate_chart_js_data(history_data: List[Dict[str, Any]]) -> str:
    """
    Returns a JSON string representing Chart.js dataset config for build-over-build comparisons.
    Organizes the data points chronologically.
    Maintains backward compatibility for the main overview chart.
    """
    # Sort history data by timestamp or build id
    sorted_history = sorted(
        history_data,
        key=lambda x: x.get("metadata", {}).get("aggregated_at", "")
    )
    
    labels = []
    coremark_scores = []
    sysbench_cpu_scores = []
    tiobench_write_scores = []
    geekbench_single_scores = []
    geekbench_multi_scores = []
    
    for entry in sorted_history:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        bench_name = meta.get("benchmark_name", "")
        stats = entry.get("statistics", {})

        # Only the benchmarks handled below contribute a data point to
        # these specific datasets. Skipping unhandled benchmarks here (and
        # NOT appending a label for them) keeps `labels` the same length as
        # every `data` array - appending a label unconditionally while only
        # some branches push to the data arrays desyncs the two, shifting
        # every subsequent point on the chart.
        if bench_name not in ("coremark", "sysbench", "tiobench", "geekbench"):
            continue

        label = f"{build_id} ({bench_name})"
        labels.append(label)

        # Coremark
        if bench_name == "coremark":
            score = stats.get("coremark_default", {}).get("mean", 0.0)
            coremark_scores.append(score)
            sysbench_cpu_scores.append(0.0)
            tiobench_write_scores.append(0.0)
            geekbench_single_scores.append(0.0)
            geekbench_multi_scores.append(0.0)
        # Sysbench
        elif bench_name == "sysbench":
            score = stats.get("sysbench_cpu_prime_single_test", stats.get("cpu_prime_single", {})).get("mean", 0.0)
            sysbench_cpu_scores.append(score)
            coremark_scores.append(0.0)
            tiobench_write_scores.append(0.0)
            geekbench_single_scores.append(0.0)
            geekbench_multi_scores.append(0.0)
        # Tiobench
        elif bench_name == "tiobench":
            score = stats.get("sequential_write_rate", {}).get("mean", 0.0)
            tiobench_write_scores.append(score)
            coremark_scores.append(0.0)
            sysbench_cpu_scores.append(0.0)
            geekbench_single_scores.append(0.0)
            geekbench_multi_scores.append(0.0)
        # Geekbench
        elif bench_name == "geekbench":
            sc_score = stats.get("geekbench_cpu_single_core", {}).get("mean", 0.0)
            mc_score = stats.get("geekbench_cpu_multi_core", {}).get("mean", 0.0)
            geekbench_single_scores.append(sc_score)
            geekbench_multi_scores.append(mc_score)
            coremark_scores.append(0.0)
            sysbench_cpu_scores.append(0.0)
            tiobench_write_scores.append(0.0)

    chart_payload = {
        "labels": labels,
        "datasets": [
            {
                "label": "CoreMark Mean Score (Iters/Sec)",
                "data": coremark_scores,
                "backgroundColor": "rgba(230, 126, 34, 0.6)",
                "borderColor": "rgba(230, 126, 34, 1)",
                "borderWidth": 1
            },
            {
                "label": "Sysbench CPU Prime Single Mean (Events/Sec)",
                "data": sysbench_cpu_scores,
                "backgroundColor": "rgba(52, 152, 219, 0.6)",
                "borderColor": "rgba(52, 152, 219, 1)",
                "borderWidth": 1
            },
            {
                "label": "TIOBench Write Rate 4096 Mean (MB/s)",
                "data": tiobench_write_scores,
                "backgroundColor": "rgba(46, 204, 113, 0.6)",
                "borderColor": "rgba(46, 204, 113, 1)",
                "borderWidth": 1
            },
            {
                "label": "Geekbench Single-Core Score",
                "data": geekbench_single_scores,
                "backgroundColor": "rgba(46, 204, 113, 0.6)",
                "borderColor": "rgba(46, 204, 113, 1)",
                "borderWidth": 1
            },
            {
                "label": "Geekbench Multi-Core Score",
                "data": geekbench_multi_scores,
                "backgroundColor": "rgba(52, 152, 219, 0.6)",
                "borderColor": "rgba(52, 152, 219, 1)",
                "borderWidth": 1
            }
        ]
    }
    
    return json.dumps(chart_payload, indent=2)

def generate_category_specific_charts(history_data: List[Dict[str, Any]]) -> str:
    """Generate Chart.js configurations for each benchmark category"""
    
    # Sort history data chronologically
    sorted_history = sorted(
        history_data,
        key=lambda x: x.get("metadata", {}).get("aggregated_at", "")
    )
    
    # Filter for sysbench runs only
    sysbench_data = [h for h in sorted_history if h.get("metadata", {}).get("benchmark_name") == "sysbench"]
    
    if not sysbench_data:
        return "{}"
        
    charts = {
        "threads": _generate_threads_charts(sysbench_data),
        "mutex": _generate_mutex_charts(sysbench_data),
        "memory": _generate_memory_charts(sysbench_data),
        "cpu": _generate_cpu_charts(sysbench_data),
        "fileio": _generate_fileio_charts(sysbench_data)
    }
    
    return json.dumps(charts, indent=2)

def _generate_threads_charts(sysbench_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate charts for threads benchmark"""
    labels = []
    avg_latency = []
    p95_latency = []
    throughput = []
    
    for entry in sysbench_data:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        labels.append(build_id)
        
        stats = entry.get("statistics", {})
        
        # We need to find the threads test in the stats
        # It's usually named "sysbench_threads_scheduler_test"
        threads_stats_prefix = "sysbench_threads_scheduler_test"
        
        # Extract metrics (using defaults if not found)
        avg_lat = stats.get(f"{threads_stats_prefix}_latency_avg", {}).get("mean", 0.0)
        p95_lat = stats.get(f"{threads_stats_prefix}_latency_95", {}).get("mean", 0.0)
        tp = stats.get(f"{threads_stats_prefix}", {}).get("mean", 0.0) # throughput is the base key
        
        avg_latency.append(avg_lat)
        p95_latency.append(p95_lat)
        throughput.append(tp)
        
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Average Latency (ms)",
                "data": avg_latency,
                "borderColor": "rgba(52, 152, 219, 1)",
                "backgroundColor": "rgba(52, 152, 219, 0.1)",
                "borderWidth": 2,
                "tension": 0.1,
                "yAxisID": "y"
            },
            {
                "label": "P95 Latency (ms)",
                "data": p95_latency,
                "borderColor": "rgba(230, 126, 34, 1)",
                "backgroundColor": "rgba(230, 126, 34, 0.1)",
                "borderWidth": 2,
                "tension": 0.1,
                "yAxisID": "y"
            },
            {
                "label": "Throughput (events/sec)",
                "data": throughput,
                "borderColor": "rgba(46, 204, 113, 1)",
                "backgroundColor": "rgba(46, 204, 113, 0.1)",
                "borderWidth": 2,
                "tension": 0.1,
                "yAxisID": "y1"
            }
        ]
    }

def _generate_mutex_charts(sysbench_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate charts for mutex benchmark"""
    labels = []
    avg_latency = []
    p95_latency = []
    
    for entry in sysbench_data:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        labels.append(build_id)
        
        stats = entry.get("statistics", {})
        
        mutex_stats_prefix = "sysbench_mutex_contention_test"
        
        avg_lat = stats.get(f"{mutex_stats_prefix}_latency_avg", {}).get("mean", 0.0)
        p95_lat = stats.get(f"{mutex_stats_prefix}_latency_95", {}).get("mean", 0.0)
        
        avg_latency.append(avg_lat)
        p95_latency.append(p95_lat)
        
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Average Event Latency (ms)",
                "data": avg_latency,
                "borderColor": "rgba(155, 89, 182, 1)",
                "backgroundColor": "rgba(155, 89, 182, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            },
            {
                "label": "P95 Event Latency (ms)",
                "data": p95_latency,
                "borderColor": "rgba(231, 76, 60, 1)",
                "backgroundColor": "rgba(231, 76, 60, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            }
        ]
    }

def _generate_memory_charts(sysbench_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate charts for memory benchmark"""
    labels = []
    throughput_read = []
    throughput_write = []
    
    for entry in sysbench_data:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        labels.append(build_id)
        
        stats = entry.get("statistics", {})
        
        read_tp = stats.get("sysbench_memory_random_read", {}).get("mean", 0.0)
        write_tp = stats.get("sysbench_memory_random_write", {}).get("mean", 0.0)
        
        # Fallback to sequential if random is not present
        if read_tp == 0.0:
            read_tp = stats.get("sysbench_memory_seq_read_test", {}).get("mean", 0.0)
        if write_tp == 0.0:
            write_tp = stats.get("sysbench_memory_seq_write_test", {}).get("mean", 0.0)
            
        throughput_read.append(read_tp)
        throughput_write.append(write_tp)
        
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Read Throughput (MiB/sec)",
                "data": throughput_read,
                "borderColor": "rgba(52, 152, 219, 1)",
                "backgroundColor": "rgba(52, 152, 219, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            },
            {
                "label": "Write Throughput (MiB/sec)",
                "data": throughput_write,
                "borderColor": "rgba(230, 126, 34, 1)",
                "backgroundColor": "rgba(230, 126, 34, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            }
        ]
    }

def _generate_cpu_charts(sysbench_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate charts for CPU benchmark"""
    labels = []
    tp_single = []
    tp_multi = []
    
    for entry in sysbench_data:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        labels.append(build_id)
        
        stats = entry.get("statistics", {})
        
        single = stats.get("sysbench_cpu_prime_single_test", {}).get("mean", 0.0)
        multi = stats.get("sysbench_cpu_prime_multi_test", {}).get("mean", 0.0)
        
        tp_single.append(single)
        tp_multi.append(multi)
        
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Single Thread (Events/sec)",
                "data": tp_single,
                "borderColor": "rgba(46, 204, 113, 1)",
                "backgroundColor": "rgba(46, 204, 113, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            },
            {
                "label": "Multi Thread (Events/sec)",
                "data": tp_multi,
                "borderColor": "rgba(155, 89, 182, 1)",
                "backgroundColor": "rgba(155, 89, 182, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            }
        ]
    }

def _generate_fileio_charts(sysbench_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate charts for FileIO benchmark"""
    labels = []
    seq_read = []
    seq_write = []
    rnd_read = []
    rnd_write = []
    
    for entry in sysbench_data:
        meta = entry.get("metadata", {})
        build_id = meta.get("build_id", "Unknown")
        labels.append(build_id)
        
        stats = entry.get("statistics", {})
        
        seq_read.append(stats.get("sysbench_fileio_seq_read_test", {}).get("mean", 0.0))
        seq_write.append(stats.get("sysbench_fileio_seq_write_test", {}).get("mean", 0.0))
        rnd_read.append(stats.get("sysbench_fileio_random_read_test", {}).get("mean", 0.0))
        rnd_write.append(stats.get("sysbench_fileio_random_write_test", {}).get("mean", 0.0))
        
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Seq Read (MiB/sec)",
                "data": seq_read,
                "borderColor": "rgba(52, 152, 219, 1)",
                "backgroundColor": "rgba(52, 152, 219, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            },
            {
                "label": "Seq Write (MiB/sec)",
                "data": seq_write,
                "borderColor": "rgba(230, 126, 34, 1)",
                "backgroundColor": "rgba(230, 126, 34, 0.1)",
                "borderWidth": 2,
                "tension": 0.1
            },
            {
                "label": "Random Read (MiB/sec)",
                "data": rnd_read,
                "borderColor": "rgba(155, 89, 182, 1)",
                "backgroundColor": "rgba(155, 89, 182, 0.1)",
                "borderWidth": 2,
                "borderDash": [5, 5],
                "tension": 0.1
            },
            {
                "label": "Random Write (MiB/sec)",
                "data": rnd_write,
                "borderColor": "rgba(231, 76, 60, 1)",
                "backgroundColor": "rgba(231, 76, 60, 0.1)",
                "borderWidth": 2,
                "borderDash": [5, 5],
                "tension": 0.1
            }
        ]
    }