#!/bin/bash
# /root/stop_telemetry_device.sh

RUN_TIMESTAMP="${1}"
# Strip \r just in case
RUN_TIMESTAMP=$(echo "$RUN_TIMESTAMP" | tr -d '\r')

if [ -z "$RUN_TIMESTAMP" ] && [ -f /root/telemetry_timestamp.txt ]; then
  RUN_TIMESTAMP=$(cat /root/telemetry_timestamp.txt | tr -d '\r')
fi

echo "Stopping telemetry processes for run: $RUN_TIMESTAMP..."

# Kill only processes matching this timestamp
for pid_file in /root/*_${RUN_TIMESTAMP}.pid; do
  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file" | tr -d '\r')
    kill -9 $pid 2>/dev/null
  fi
done

# --------------------------------------------------------------------------
# Stop ftrace (if it was started for this run) and dump the trace buffer to
# a log file alongside the other telemetry logs so the host can pull it.
# ftrace has no userspace PID of its own; its "pid file" is just a marker
# written by start_telemetry_device.sh to signal a session is active.
# --------------------------------------------------------------------------
FTRACE_DIR=/sys/kernel/debug/tracing
if [ -f "/root/ftrace_${RUN_TIMESTAMP}.pid" ]; then
  echo "Stopping ftrace and collecting trace buffer..."
  if [ -d "$FTRACE_DIR" ]; then
    echo 0 > "$FTRACE_DIR/tracing_on" 2>/dev/null
    if [ -r "$FTRACE_DIR/trace" ]; then
      cp "$FTRACE_DIR/trace" "/root/ftrace_metrics_${RUN_TIMESTAMP}.log" 2>/dev/null \
        || echo "WARNING: Failed to copy ftrace trace buffer to log file"
    fi
    # Disable the tracepoints we enabled to leave the device in a clean state
    if [ -d "$FTRACE_DIR/events/sched" ]; then
      echo 0 > "$FTRACE_DIR/events/sched/sched_wakeup/enable" 2>/dev/null
      echo 0 > "$FTRACE_DIR/events/sched/sched_switch/enable" 2>/dev/null
      echo 0 > "$FTRACE_DIR/events/sched/sched_migrate_task/enable" 2>/dev/null
    fi
  else
    echo "WARNING: $FTRACE_DIR no longer available; cannot collect trace buffer"
  fi
  rm -f "/root/ftrace_${RUN_TIMESTAMP}.pid"
fi

# Clean up only this run's PID files (Log files are kept so the host can pull them)
rm -f /root/*_${RUN_TIMESTAMP}.pid

# Verify all killed
# NOTE: We must exclude kernel threads (shown in `ps aux` wrapped in square
# brackets, e.g. "[irq/222-c251000.thermal-sensor]") from this check. These
# are normal, always-present kernel worker/IRQ threads unrelated to our
# user-space telemetry collectors (top/vmstat/dmesg/thermal-polling-loop/
# cpufreq-polling-loop) and will always match a naive keyword grep (e.g.
# "thermal" matches "[irq/222-c251000.thermal-sensor]"), causing false
# positives that make this script report failure even though telemetry was
# stopped successfully.
sleep 1
REMAINING=$(ps aux | grep -E "\b(top|vmstat|dmesg|thermal|cpufreq)\b" | grep -v grep | grep -v "stop_telemetry" | grep -v "\[")
if [ -z "$REMAINING" ]; then
  echo "All telemetry stopped"
  exit 0
else
  echo "WARNING: Some user-space telemetry processes still running"
  echo "$REMAINING"
  exit 1
fi
