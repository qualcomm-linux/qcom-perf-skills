# COT: OS & GPU Benchmarks RCA Guide

This document provides benchmark-specific guidance for interpreting regressions across OS/Scheduler (`hackbench`, `osbench`, `unixbench`) and GPU (`glmark2`) benchmarks.

## 1. OS & Scheduler Benchmarks (`hackbench`, `osbench`, `unixbench`)

**Primary Metrics:**
- Hackbench: `sched_ipc_default` (Time - **Lower** is better)
- OSBench: `osbench_*` (us/action - **Lower** is better)
- UnixBench: `unixbench_*` (Index Score - **Higher** is better)

### Expected Anomaly Signatures
- **Scheduler Contention:** These benchmarks explicitly measure OS overhead (process creation, IPC, context switching). 
  - **Signature:** `ftrace.sched_wakeup_latency_us` > 5000us, or `vmstat.context_switches` massively above baseline.
  - **Cause:** Another heavy process (e.g., `system_server`, indexing services) is competing for CPU time slices, causing the OS to delay scheduling the benchmark threads.
- **Memory Allocation Limits (OSBench):**
  - **Signature:** `osbench_memory_alloc` regresses (takes longer), and `vmstat.swap_activity_spike` is high.
  - **Cause:** The OS is struggling to find contiguous free pages or is busy flushing the page cache to satisfy allocation requests.
- **IPC / Socket Limits (Hackbench):**
  - If hackbench `sched_ipc_sockets_extreme` fails or regresses heavily, it often points to kernel socket buffer limits (e.g., `net.core.wmem_max`) rather than CPU frequency. Look for `OOM Kills` or `dmesg` warnings about socket exhaustion.

## 2. GPU Benchmarks (`glmark2`)

**Primary Metrics:**
- `glmark2_*` (Score - **Higher** is better)

### Expected Anomaly Signatures
- **GPU Thermal Throttling:** 
  - **Signature:** `thermal_throttles.count > 0` (look specifically for `gpu-*-thermal` or generic SoC thermal zones).
  - **Cause:** Rendering at unbounded framerates heats up the GPU rapidly, causing the kernel to drop the GPU frequency.
- **CPU Bottleneck (Driver Overhead):**
  - **Signature:** `cpu_frequency_drops.count > 0` but GPU thermals are fine.
  - **Cause:** OpenGL/Wayland drivers require CPU time to dispatch draw calls. If the CPU downclocks, the GPU starves for work, lowering the GLMark2 score.
- **Wayland/Compositor Interference:**
  - **Signature:** High `vmstat.context_switches` or preemption.
  - **Cause:** The display compositor (`weston` / `surfaceflinger`) is struggling or being preempted, delaying frame presentation.