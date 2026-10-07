#!/bin/bash
# /root/start_telemetry_device.sh

RUN_TIMESTAMP="${1}"
# Strip \r just in case
RUN_TIMESTAMP=$(echo "$RUN_TIMESTAMP" | tr -d '\r')

if [ -z "$RUN_TIMESTAMP" ]; then
  RUN_TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
fi

# --------------------------------------------------------------------------
# Pre-start cleanup: guard against orphaned telemetry processes/files left
# behind by a previous run that was forcefully interrupted (e.g. terminal
# closed or Ctrl+C on the host before stop_telemetry_device.sh could run).
# This ensures every fresh invocation starts from a clean state.
# --------------------------------------------------------------------------
echo "Checking for orphaned telemetry processes from a previous run..."

# Kill any previously-started telemetry PIDs recorded on device
for pid_file in /root/*.pid; do
  [ -f "$pid_file" ] || continue
  old_pid=$(cat "$pid_file" 2>/dev/null | tr -d '\r')
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Killing orphaned telemetry process PID=$old_pid (from $pid_file)"
    kill -9 "$old_pid" 2>/dev/null || echo "WARNING: Failed to kill PID $old_pid from $pid_file"
  fi
done

# Belt-and-suspenders: also kill by process-name pattern in case a .pid file
# was itself lost/corrupted but the process is still alive.
for pattern in "top -b -d 1" "vmstat 1" "dmesg -w"; do
  pkill -9 -f "$pattern" 2>/dev/null
done
# Kill the thermal/cpufreq polling loops (identifiable by their sleep-loop shell wrapper)
pkill -9 -f "thermal_zone" 2>/dev/null
pkill -9 -f "cpufreq/scaling_cur_freq" 2>/dev/null

# Ensure any stale ftrace session from a previous, forcefully-interrupted run
# is disabled before we start a fresh one below.
if [ -d /sys/kernel/debug/tracing ]; then
  echo 0 > /sys/kernel/debug/tracing/tracing_on 2>/dev/null
fi

# Remove stale telemetry artifacts from any previous run(s)
rm -f /root/*.pid /root/*.log /root/*.csv /root/telemetry_timestamp.txt 2>/dev/null \
  || echo "WARNING: Failed to remove one or more stale telemetry files in /root/"

# --------------------------------------------------------------------------
# Tier 1 (lightweight) telemetry support: the RCA orchestrator (run_rca.py)
# touches this marker file immediately before a Tier 1 diagnostic re-run so
# that THIS invocation skips the heavier ftrace collection below (keeping
# Tier 1 at its documented <2% overhead). The marker is consumed (deleted)
# here so it never leaks into a later, unrelated run.
# --------------------------------------------------------------------------
TIER1_ONLY_MARKER=/root/telemetry_tier1_only
SKIP_FTRACE=0
if [ -f "$TIER1_ONLY_MARKER" ]; then
  SKIP_FTRACE=1
  rm -f "$TIER1_ONLY_MARKER"
fi

echo "Pre-start cleanup complete. Starting fresh telemetry collection..."

TOP_LOG="/root/top_metrics_${RUN_TIMESTAMP}.log"
VMSTAT_LOG="/root/vmstat_metrics_${RUN_TIMESTAMP}.log"
DMESG_LOG="/root/dmesg_metrics_${RUN_TIMESTAMP}.log"
CPUFREQ_LOG="/root/cpufreq_metrics_${RUN_TIMESTAMP}.log"
THERMAL_LOG="/root/thermal_metrics_${RUN_TIMESTAMP}.csv"

echo "$RUN_TIMESTAMP" > /root/telemetry_timestamp.txt

# Start top
nohup top -b -d 1 > $TOP_LOG 2>&1 < /dev/null &
TOP_PID=$!
echo $TOP_PID | tr -d '\r' > /root/top_${RUN_TIMESTAMP}.pid

# Start vmstat
nohup vmstat 1 > $VMSTAT_LOG 2>&1 < /dev/null &
VMSTAT_PID=$!
echo $VMSTAT_PID | tr -d '\r' > /root/vmstat_${RUN_TIMESTAMP}.pid

# Start dmesg
nohup dmesg -w > $DMESG_LOG 2>&1 < /dev/null &
DMESG_PID=$!
echo $DMESG_PID | tr -d '\r' > /root/dmesg_${RUN_TIMESTAMP}.pid

# Start Thermal logging
nohup sh -c '
  echo "timestamp,thermal_zone,type,temp_mC" > "'$THERMAL_LOG'"
  while true; do
    TIMESTAMP=$(date +%s)
    for ZONE in /sys/class/thermal/thermal_zone*; do
      [ -r "$ZONE/type" ] || continue
      [ -r "$ZONE/temp" ] || continue
      
      ZONE_TYPE=$(cat "$ZONE/type" 2>/dev/null)
      TEMP_MC=$(cat "$ZONE/temp" 2>/dev/null)
      
      case "$ZONE_TYPE" in
        cpu-*-thermal|cpuss-*-thermal|ddrss-*-thermal)
          [ -n "$TEMP_MC" ] || continue
          echo "$TIMESTAMP,$(basename "$ZONE"),$ZONE_TYPE,$TEMP_MC" >> "'$THERMAL_LOG'"
          ;;
      esac
    done
    sleep 1
  done
' > /dev/null 2>&1 < /dev/null &
THERMAL_PID=$!
echo $THERMAL_PID | tr -d '\r' > /root/thermal_${RUN_TIMESTAMP}.pid

# Start CPU frequency logging
nohup sh -c '
  while true; do
    echo "$(date +'\''%Y-%m-%d %H:%M:%S'\'')" >> '$CPUFREQ_LOG'
    for i in 0 1 2 3 4 5 6 7; do
      freq=$(cat /sys/devices/system/cpu/cpu$i/cpufreq/scaling_cur_freq 2>/dev/null)
      echo "cpu$i: $freq kHz" >> '$CPUFREQ_LOG'
    done
    echo "---" >> '$CPUFREQ_LOG'
    sleep 1
  done
' > /dev/null 2>&1 < /dev/null &
CPUFREQ_PID=$!
echo $CPUFREQ_PID | tr -d '\r' > /root/cpufreq_${RUN_TIMESTAMP}.pid

# --------------------------------------------------------------------------
# Start ftrace (nop tracer, scheduler events only) for scheduler-latency and
# preemption/lock-contention RCA. Uses the "nop" tracer (not function/
# function_graph) specifically to minimize probe overhead on the target --
# we only need discrete sched_wakeup/sched_switch/sched_migrate_task
# tracepoint events, not full function tracing.
#
# ftrace is treated as OPTIONAL telemetry: if /sys/kernel/debug/tracing is
# unavailable (e.g. debugfs not mounted, or permission denied on a locked-
# down build), we log a warning and continue -- this must never fail the
# overall telemetry startup or the benchmark run.
# --------------------------------------------------------------------------
FTRACE_DIR=/sys/kernel/debug/tracing
FTRACE_ENABLED=0
if [ "$SKIP_FTRACE" = "1" ]; then
  echo "Tier 1 lightweight telemetry requested -- skipping ftrace collection for this run."
elif [ -d "$FTRACE_DIR" ] && [ -w "$FTRACE_DIR/tracing_on" ]; then
  echo "Starting ftrace collection (nop tracer, scheduler events)..."

  echo nop > "$FTRACE_DIR/current_tracer" 2>/dev/null
  echo 0 > "$FTRACE_DIR/tracing_on" 2>/dev/null

  # Clear any residual trace buffer from a previous run
  echo > "$FTRACE_DIR/trace" 2>/dev/null

  # Enable only the scheduler tracepoints needed for wake-up latency,
  # preemption, and migration (lock-contention proxy) analysis.
  if [ -d "$FTRACE_DIR/events/sched" ]; then
    echo 1 > "$FTRACE_DIR/events/sched/sched_wakeup/enable" 2>/dev/null
    echo 1 > "$FTRACE_DIR/events/sched/sched_switch/enable" 2>/dev/null
    echo 1 > "$FTRACE_DIR/events/sched/sched_migrate_task/enable" 2>/dev/null
  fi

  echo 1 > "$FTRACE_DIR/tracing_on" 2>/dev/null

  # There's no background PID for ftrace itself (it's a kernel ring buffer,
  # not a userspace process), but we still write a marker .pid file so
  # stop_telemetry_device.sh knows an ftrace session for this RUN_TIMESTAMP
  # needs to be stopped/collected.
  echo "ftrace" > /root/ftrace_${RUN_TIMESTAMP}.pid
  FTRACE_ENABLED=1
  echo "ftrace started (nop tracer; sched_wakeup, sched_switch, sched_migrate_task)"
else
  echo "WARNING: $FTRACE_DIR not available or not writable -- ftrace collection disabled for this run. Scheduler-latency/preemption RCA will be skipped for this run."
fi

# Verify all processes started
sleep 1
if [ -f /root/top_${RUN_TIMESTAMP}.pid ] && [ -f /root/vmstat_${RUN_TIMESTAMP}.pid ] && [ -f /root/dmesg_${RUN_TIMESTAMP}.pid ] && [ -f /root/cpufreq_${RUN_TIMESTAMP}.pid ] && [ -f /root/thermal_${RUN_TIMESTAMP}.pid ]; then
  echo "Telemetry started: PIDs=$TOP_PID,$VMSTAT_PID,$DMESG_PID,$CPUFREQ_PID,$THERMAL_PID (ftrace_enabled=$FTRACE_ENABLED)"
  exit 0
else
  echo "ERROR: Not all PIDs created"
  exit 1
fi
