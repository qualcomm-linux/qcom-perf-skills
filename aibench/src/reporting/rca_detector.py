"""
rca_detector.py - Root Cause Analysis Engine
Uses Chain-of-Thought (COT) logic to correlate performance regressions with system anomalies.

Confidence-score methodology (answers "how is the confidence % derived?"):
Confidence is NOT a statistically-calibrated probability. It is a fixed,
documented weight assigned per decision-tree branch, reflecting how
directly the available evidence explains the observed regression:
  - 90-95%: Direct, unambiguous kernel-logged evidence exists for the
    specific failure mode (e.g. an actual "throttle" string in dmesg, or
    a measured >20% CPU frequency drop coincident with the regression).
  - 80-89%: Strong circumstantial evidence exists (e.g. elevated
    temperature reading, but no explicit throttle log entry; scheduler
    latency spike coincident with a latency regression).
  - 65-79%: Only single-signal circumstantial evidence exists (e.g. OOM
    kill count, or context-switch spike alone) that plausibly but not
    conclusively explains the regression.
  - <65%: No corroborating telemetry evidence was found; the regression is
    flagged but the cause is genuinely ambiguous and needs manual/deeper
    investigation (e.g. `perf record`).
These weights are intentionally documented here (not hidden) so any
consumer of the RCA output (HTML report, JSON, downstream tooling) can
show *why* a given confidence value was assigned, avoiding an
unanswerable "how was X% derived?" question.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from typing import Any, Dict, List

class RCADetector:
    @staticmethod
    def apply_cot_logic(test_name: str, regression_result: Dict[str, Any], build_anomalies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applies Chain-of-Thought logic to determine the Root Cause of a performance regression.
        Correlates throughput/latency drops with telemetry anomalies (e.g., thermal throttles, OOMs,
        scheduler latency spikes, memory pressure, I/O wait, process-level CPU/memory anomalies).
        """
        rca_result = {
            "cause": "Unknown",
            "confidence": "0%",
            "confidence_basis": "",
            "evidence": [],
            "recommendation": "Investigate manually."
        }

        metrics = regression_result.get("metrics", {})
        tp_delta = metrics.get("throughput_delta_percent", 0.0)
        lat_delta = metrics.get("latency_delta_percent", 0.0)

        thermal_throttles = build_anomalies.get("thermal_throttles", [])
        thermal_high_temp = build_anomalies.get("thermal_high_temp", [])
        freq_drops = build_anomalies.get("cpu_frequency_drops", [])
        oom_kills = build_anomalies.get("oom_kills", [])
        context_switches = build_anomalies.get("context_switch_spike", [])
        page_faults = build_anomalies.get("page_fault_spike", [])
        io_wait = build_anomalies.get("io_wait_spike", [])
        memory_pressure = build_anomalies.get("memory_pressure", [])
        process_cpu_anomalies = build_anomalies.get("process_cpu_anomalies", [])
        process_memory_leak = build_anomalies.get("process_memory_leak", [])
        zombie_processes = build_anomalies.get("zombie_processes", [])
        sched_latency_spikes = build_anomalies.get("scheduler_latency_spikes", [])
        task_migration_high = build_anomalies.get("task_migration_high", [])

        # Direction (higher-is-better vs lower-is-better) has already been
        # correctly resolved upstream, per-metric, from config/benchmarks.yaml
        # (see run_rca.py::_resolve_direction) when RegressionDetector computed
        # throughput_regression/latency_regression -- trust those booleans
        # directly instead of re-guessing direction from the test name here.
        throughput_degraded = regression_result.get("throughput_regression", False)

        if test_name == "unixbench_scaling" and throughput_degraded:
            rca_result["cause"] = "Multi-core Scaling Degradation"
            rca_result["confidence"] = "90%"
            rca_result["confidence_basis"] = "Direct: scaling-efficiency metric itself measures the regression; thermal/frequency corroboration below (if present) reinforces this."
            rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{tp_delta:.1f}%", "interpretation": "Scaling efficiency regressed"})
            if len(freq_drops) > 0 or len(thermal_throttles) > 0:
                rca_result["evidence"].append({"type": "CORRELATED", "source": "telemetry", "value": "Thermal/Frequency limits hit", "interpretation": "Limits hit during multi-core run"})
            rca_result["recommendation"] = "Dive into individual results by checking results.json for this run/build to see which specific metric (e.g. Dhrystone, Execl) failed to scale."

        elif throughput_degraded:
            # Bug Fix: Do not attribute to thermal unless an ACTUAL high temp or throttle event occurred.
            # Raw cpufreq drops without thermal events are likely just normal governor scaling.
            has_thermal_breach = len(thermal_throttles) > 0 or len(thermal_high_temp) > 0
            
            if has_thermal_breach:
                rca_result["cause"] = "DVFS / Thermal Throttling"
                rca_result["confidence"] = "92%"
                rca_result["confidence_basis"] = "Direct: kernel-logged throttle event and/or thermal-zone reading above the configured high-temp threshold, coincident with the performance regression."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{tp_delta:.1f}%", "interpretation": "Performance regressed"})
                if len(thermal_throttles) > 0:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "dmesg", "value": f"{len(thermal_throttles)} times", "interpretation": "Thermal throttle events logged in dmesg"})
                if len(thermal_high_temp) > 0:
                    for temp_event in thermal_high_temp:
                        rca_result["evidence"].append({"type": "OBSERVED", "source": "thermal_metrics", "value": f"{temp_event['temp_c']:.1f} C", "interpretation": f"{temp_event['event']} ({temp_event['zone']})"})
                rca_result["recommendation"] = "Investigate thermal design, cooling, or background workloads heating the SoC."

            elif len(oom_kills) > 0:
                rca_result["cause"] = "Severe Memory Pressure"
                rca_result["confidence"] = "85%"
                rca_result["confidence_basis"] = "Strong circumstantial: kernel-logged OOM-kill event(s) directly indicate memory exhaustion, a well-known cause of throughput collapse, though the exact killed process may not be the benchmark itself."
                rca_result["evidence"].append({"type": "OBSERVED", "source": "dmesg", "value": f"{len(oom_kills)} times", "interpretation": "OOM kill events detected"})
                rca_result["recommendation"] = "Check memory usage (top/vmstat) during test. System killed processes."

            elif len(memory_pressure) > 0 or len(process_memory_leak) > 0:
                rca_result["cause"] = "Memory Pressure (Low Free Memory / Possible Leak)"
                rca_result["confidence"] = "78%"
                rca_result["confidence_basis"] = "Strong circumstantial: vmstat free-memory samples dropped below the configured low-memory threshold, and/or a process's RSS grew significantly across the run (leak proxy), without a hard OOM kill."
                if len(memory_pressure) > 0:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "vmstat", "value": f"{len(memory_pressure)} samples", "interpretation": "Free memory dropped below threshold"})
                if len(process_memory_leak) > 0:
                    for leak in process_memory_leak[:3]:
                        rca_result["evidence"].append({
                            "type": "OBSERVED",
                            "source": "top",
                            "value": f"{leak['growth_percent']:.1f}% growth ({leak['first_rss_kb']}KB -> {leak['last_rss_kb']}KB)",
                            "interpretation": f"Process '{leak['command']}' (pid {leak['pid']}) RSS grew"
                        })
                rca_result["recommendation"] = "Check for memory leaks in background processes; review vmstat free/buff/cache trend across the run."

            elif len(io_wait) > 0:
                rca_result["cause"] = "I/O Bottleneck"
                rca_result["confidence"] = "75%"
                rca_result["confidence_basis"] = "Circumstantial: vmstat I/O-wait percentage exceeded the configured threshold during the run, consistent with a storage/disk bottleneck limiting throughput."
                rca_result["evidence"].append({"type": "OBSERVED", "source": "vmstat", "value": f"{len(io_wait)} samples", "interpretation": "I/O wait spiked above threshold"})
                rca_result["recommendation"] = "Check disk I/O patterns, storage performance, and concurrent I/O-bound background processes."

            elif len(page_faults) > 0:
                rca_result["cause"] = "Memory Pressure / Paging"
                rca_result["confidence"] = "70%"
                rca_result["confidence_basis"] = "Circumstantial: vmstat page-fault rate exceeded the configured threshold, suggesting excessive paging/cache-miss activity that can degrade throughput."
                rca_result["evidence"].append({"type": "OBSERVED", "source": "vmstat", "value": f"{len(page_faults)} samples", "interpretation": "Page fault rate spiked above threshold"})
                rca_result["recommendation"] = "Check memory allocation patterns and cache efficiency; consider reducing working-set size or improving locality."

            elif len(context_switches) > 0 or len(task_migration_high) > 0:
                rca_result["cause"] = "Scheduler Contention"
                rca_result["confidence"] = "72%"
                rca_result["confidence_basis"] = "Circumstantial: elevated context-switch rate and/or excessive task-migration count (ftrace) coincide with the throughput regression, consistent with scheduler contention or CPU affinity thrash."
                if len(context_switches) > 0:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "vmstat", "value": f"{len(context_switches)} samples", "interpretation": "Context switch rate spiked above threshold"})
                if len(task_migration_high) > 0:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "ftrace", "value": f"{task_migration_high[0]['migration_count']} migrations (threshold {task_migration_high[0]['threshold']})", "interpretation": "Excessive task migrations detected"})
                rca_result["recommendation"] = "Check thread counts, CPU affinity, and background tasks competing for CPU."

            elif len(process_cpu_anomalies) > 0 or len(zombie_processes) > 0:
                rca_result["cause"] = "Background Process Interference"
                rca_result["confidence"] = "68%"
                rca_result["confidence_basis"] = "Weak-to-moderate circumstantial: a non-benchmark process was observed consuming abnormally high CPU, and/or zombie processes were present, which can steal CPU time or indicate resource-cleanup issues."
                for anomaly in process_cpu_anomalies[:3]:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "top", "value": f"{anomaly['cpu_percent']:.1f}% CPU", "interpretation": f"Process '{anomaly['command']}' (pid {anomaly['pid']}) used CPU"})
                if len(zombie_processes) > 0:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "top", "value": f"{len(zombie_processes)} processes", "interpretation": "Zombie processes detected"})
                rca_result["recommendation"] = "Identify and eliminate interfering background processes before re-running the benchmark."

            else:
                rca_result["cause"] = "Ambiguous CPU/Storage Bottleneck"
                rca_result["confidence"] = "55%"
                rca_result["confidence_basis"] = "No corroborating telemetry evidence found across thermal/memory/IO/scheduler categories; regression is real (per statistical gate) but root cause is unconfirmed."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{tp_delta:.1f}%", "interpretation": "Performance degraded without obvious events"})
                
                # Context-specific fallback recommendations
                if "write" in test_name.lower():
                    rca_result["recommendation"] = "Storage write regression without CPU/IO wait spikes often indicates background garbage collection, SLC cache exhaustion, or insufficient cooldown time between benchmark runs."
                else:
                    rca_result["recommendation"] = "Run `perf record --call-graph dwarf` to profile the workload. Analyze for scheduler misbalance or lock contention."

        elif regression_result.get("latency_regression", False):
            if len(sched_latency_spikes) > 0:
                rca_result["cause"] = "Scheduler Latency / Preemption"
                rca_result["confidence"] = "88%"
                rca_result["confidence_basis"] = "Strong: ftrace-measured sched_wakeup-to-sched_switch latency exceeded the configured threshold for specific PIDs, directly explaining elevated benchmark latency."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{lat_delta:.1f}%", "interpretation": "Latency 95% spiked"})
                for spike in sched_latency_spikes[:3]:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "ftrace", "value": f"{spike['wakeup_to_switch_latency_us']:.1f}us", "interpretation": f"pid {spike['pid']}: wake-up-to-switch latency"})
                rca_result["recommendation"] = "Check thread counts and CPU affinity. Ensure background tasks aren't preempting the benchmark. Review ftrace sched_switch trace for preemption sources."

            elif len(context_switches) > 0:
                rca_result["cause"] = "Scheduler Contention / Preemption"
                rca_result["confidence"] = "80%"
                rca_result["confidence_basis"] = "Circumstantial: elevated context-switch rate coincides with the latency regression, though direct wake-up-latency measurement (ftrace) wasn't available/anomalous."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{lat_delta:.1f}%", "interpretation": "Latency 95% spiked"})
                rca_result["evidence"].append({"type": "OBSERVED", "source": "vmstat", "value": "Spikes detected", "interpretation": "Context switch spikes detected"})
                rca_result["recommendation"] = "Check thread counts and CPU affinity. Ensure background tasks aren't preempting the benchmark."

            elif len(thermal_high_temp) > 0 or len(thermal_throttles) > 0:
                rca_result["cause"] = "Thermal-Induced Latency"
                rca_result["confidence"] = "78%"
                rca_result["confidence_basis"] = "Circumstantial: thermal anomaly (high temp reading or throttle event) coincides with the latency regression; DVFS-induced frequency reduction can increase per-operation latency."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{lat_delta:.1f}%", "interpretation": "Latency 95% spiked"})
                if thermal_throttles:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "dmesg", "value": f"{len(thermal_throttles)} times", "interpretation": "Thermal throttle events logged"})
                if thermal_high_temp:
                    rca_result["evidence"].append({"type": "OBSERVED", "source": "thermal_metrics", "value": f"{thermal_high_temp[0]['temp_c']:.1f} C", "interpretation": f"{thermal_high_temp[0]['event']}"})
                rca_result["recommendation"] = "Reduce thermal load, improve cooling, or investigate concurrent thermally-intensive workloads."

            else:
                rca_result["cause"] = "Ambiguous Latency Issue"
                rca_result["confidence"] = "60%"
                rca_result["confidence_basis"] = "No corroborating telemetry evidence found; regression is real (per statistical gate) but root cause is unconfirmed."
                rca_result["evidence"].append({"type": "CALCULATED", "source": "regression_detector", "value": f"{lat_delta:.1f}%", "interpretation": "Latency 95% spiked without obvious events"})
                rca_result["recommendation"] = "Trigger a targeted rerun with ftrace sched_wakeup/sched_switch tracing enabled to analyze wake-up latencies and scheduling delays."

        return rca_result

    @staticmethod
    def generate_rca(regression_results: Dict[str, Any], build_anomalies: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates RCA for all detected regressions.
        """
        rca = {}
        for test_name, regression_data in regression_results.items():
            if regression_data.get("throughput_regression") or regression_data.get("latency_regression"):
                rca[test_name] = RCADetector.apply_cot_logic(test_name, regression_data, build_anomalies)
        return rca