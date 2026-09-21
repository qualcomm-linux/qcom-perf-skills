#!/usr/bin/env python3
"""
Memory Skill Validation -- End-to-End Test Runner

Runs each C test program on the device, collects snapshots before and after,
and verifies the skill correctly reports the expected memory delta.

Usage:
    python run_validation.py --serial <adb_serial> [--size <MB>] [--hold <sec>]
    python run_validation.py --serial 4cc505ea --size 50 --hold 30
    python run_validation.py --serial 4cc505ea --test malloc   # run single test
    python run_validation.py --serial 4cc505ea --test all      # run all tests

Tests:
    malloc   -- userspace heap (AnonPages)
    mmap     -- anonymous mmap (AnonPages)
    dmabuf   -- DMA-BUF via /dev/dma_heap (DMA-BUF category)
    shmem    -- POSIX shared memory (Shmem)
    kmalloc  -- kernel slab via module (Slab/SUnreclaim)
"""

import argparse
import json
import os
import subprocess
import sys
import time

# Tolerance: expected delta must be within this fraction of requested size
TOLERANCE = 0.15  # 15%

DEVICE_TMP = "/data/local/tmp"


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def adb(serial, cmd, check=False):
    result = subprocess.run(
        ["adb", "-s", serial, "shell", cmd],
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"ADB command failed: {cmd}\n{result.stderr}")
    return result.stdout.strip()


def adb_push(serial, local, remote):
    subprocess.run(["adb", "-s", serial, "push", local, remote], check=True)


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------

def collect_snapshot(serial, output_dir, label):
    """Collect a snapshot using the data-collection skill."""
    os.makedirs(output_dir, exist_ok=True)
    result = subprocess.run(
        [sys.executable,
         os.path.join(os.path.dirname(__file__), "..", "internal", "data-collection", "scripts", "collect.py"),
         "-s", serial,
         "--output", output_dir,
         "--label", label],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  WARNING: collect.py returned {result.returncode}")
        print(result.stderr[:200])
    snap_path = os.path.join(output_dir, "snapshot.json")
    if not os.path.isfile(snap_path):
        raise RuntimeError(f"snapshot.json not found at {snap_path}")
    return json.load(open(snap_path, encoding="utf-8"))


def get_meminfo(snap, key):
    src = snap.get("sources", {}).get("meminfo", {})
    return src.get("parsed", {}).get(key, 0) if src.get("available") else 0


def get_dmabuf_total(snap):
    debugfs = snap.get("sources", {}).get("debugfs", {})
    dmabuf = debugfs.get("dmabuf", {})
    return dmabuf.get("parsed", {}).get("total_kb", 0) if dmabuf.get("available") else 0


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def check_delta(name, actual_kb, expected_kb, tolerance=TOLERANCE):
    """Check that actual delta is within tolerance of expected."""
    low  = expected_kb * (1 - tolerance)
    high = expected_kb * (1 + tolerance)
    ok = low <= actual_kb <= high
    status = "PASS" if ok else "FAIL"
    print(f"    [{status}] {name}: expected ~{expected_kb//1024} MB, "
          f"got {actual_kb//1024} MB "
          f"(tolerance ±{int(tolerance*100)}%)")
    return ok


def run_test(serial, test_name, binary, args_str, size_mb, hold_sec, output_base,
             check_fn):
    """
    Generic test runner:
    1. Collect baseline
    2. Start binary on device (background)
    3. Wait for allocation to stabilize
    4. Collect active snapshot
    5. Kill binary
    6. Run check_fn(baseline, active, size_mb)
    """
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}  (size={size_mb} MB, hold={hold_sec}s)")
    print(f"{'='*60}")

    baseline_dir = os.path.join(output_base, test_name, "baseline")
    active_dir   = os.path.join(output_base, test_name, "active")

    # Push binary
    local_bin = os.path.join(os.path.dirname(__file__), binary)
    if not os.path.isfile(local_bin):
        print(f"  SKIP: binary not found: {local_bin}")
        print(f"  Build first: cd tests && make")
        return None

    remote_bin = f"{DEVICE_TMP}/{os.path.basename(binary)}"
    print(f"  Pushing {binary} -> {remote_bin}")
    adb_push(serial, local_bin, remote_bin)
    adb(serial, f"chmod +x {remote_bin}")

    # Collect baseline
    print("  Collecting baseline snapshot...")
    baseline = collect_snapshot(serial, baseline_dir, f"{test_name}_baseline")
    print(f"  Baseline: MemFree={get_meminfo(baseline,'MemFree')//1024} MB")

    # Start allocation in background
    cmd = f"nohup {remote_bin} {args_str} > {DEVICE_TMP}/{test_name}.log 2>&1 &"
    print(f"  Starting: {cmd}")
    adb(serial, cmd)

    # Wait for allocation to stabilize
    wait = min(hold_sec // 2, 10)
    print(f"  Waiting {wait}s for allocation to stabilize...")
    time.sleep(wait)

    # Verify process is running
    pid = adb(serial, f"pgrep -f {os.path.basename(binary)}")
    if not pid:
        log = adb(serial, f"cat {DEVICE_TMP}/{test_name}.log 2>/dev/null | tail -5")
        print(f"  WARNING: process not found. Log: {log}")

    # Collect active snapshot
    print("  Collecting active snapshot...")
    active = collect_snapshot(serial, active_dir, f"{test_name}_active")
    print(f"  Active:   MemFree={get_meminfo(active,'MemFree')//1024} MB")

    # Kill the test process
    adb(serial, f"pkill -f {os.path.basename(binary)} 2>/dev/null")
    time.sleep(2)

    # Run checks
    print("  Results:")
    passed = check_fn(baseline, active, size_mb)

    # Show log tail
    log = adb(serial, f"cat {DEVICE_TMP}/{test_name}.log 2>/dev/null | tail -3")
    if log:
        print(f"  Device log: {log}")

    return passed


# ---------------------------------------------------------------------------
# Individual test check functions
# ---------------------------------------------------------------------------

def check_malloc(baseline, active, size_mb):
    expected_kb = size_mb * 1024
    delta_anon = get_meminfo(active, "AnonPages") - get_meminfo(baseline, "AnonPages")
    ok1 = check_delta("AnonPages", delta_anon, expected_kb)
    # DMA-BUF should NOT change
    delta_dmabuf = get_dmabuf_total(active) - get_dmabuf_total(baseline)
    ok2 = abs(delta_dmabuf) < 5 * 1024  # < 5 MB change
    print(f"    [{'PASS' if ok2 else 'FAIL'}] DMA-BUF unchanged: delta={delta_dmabuf//1024} MB (expected ~0)")
    return ok1 and ok2


def check_mmap(baseline, active, size_mb):
    expected_kb = size_mb * 1024
    delta_anon = get_meminfo(active, "AnonPages") - get_meminfo(baseline, "AnonPages")
    return check_delta("AnonPages", delta_anon, expected_kb)


def check_dmabuf(baseline, active, size_mb):
    expected_kb = size_mb * 1024
    delta_dmabuf = get_dmabuf_total(active) - get_dmabuf_total(baseline)
    ok1 = check_delta("DMA-BUF", delta_dmabuf, expected_kb)
    # AnonPages should NOT change significantly
    delta_anon = get_meminfo(active, "AnonPages") - get_meminfo(baseline, "AnonPages")
    ok2 = abs(delta_anon) < 10 * 1024  # < 10 MB change
    print(f"    [{'PASS' if ok2 else 'FAIL'}] AnonPages unchanged: delta={delta_anon//1024} MB (expected ~0)")
    return ok1 and ok2


def check_shmem(baseline, active, size_mb):
    expected_kb = size_mb * 1024
    delta_shmem = get_meminfo(active, "Shmem") - get_meminfo(baseline, "Shmem")
    ok1 = check_delta("Shmem", delta_shmem, expected_kb)
    # AnonPages should NOT change
    delta_anon = get_meminfo(active, "AnonPages") - get_meminfo(baseline, "AnonPages")
    ok2 = abs(delta_anon) < 5 * 1024
    print(f"    [{'PASS' if ok2 else 'FAIL'}] AnonPages unchanged: delta={delta_anon//1024} MB (expected ~0)")
    return ok1 and ok2


def check_kmalloc(baseline, active, size_mb):
    expected_kb = size_mb * 1024
    delta_slab     = get_meminfo(active, "Slab")     - get_meminfo(baseline, "Slab")
    delta_sunreclaim = get_meminfo(active, "SUnreclaim") - get_meminfo(baseline, "SUnreclaim")
    ok1 = check_delta("Slab",      delta_slab,      expected_kb)
    ok2 = check_delta("SUnreclaim", delta_sunreclaim, expected_kb)
    return ok1 and ok2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Memory skill end-to-end validation tests."
    )
    parser.add_argument("--serial", "-s", required=True,
                        help="ADB device serial")
    parser.add_argument("--size", type=int, default=50,
                        help="MB to allocate in each test (default: 50)")
    parser.add_argument("--hold", type=int, default=30,
                        help="Seconds to hold allocation (default: 30)")
    parser.add_argument("--test", default="all",
                        choices=["all", "malloc", "mmap", "dmabuf", "shmem", "kmalloc"],
                        help="Which test to run (default: all)")
    parser.add_argument("--output-dir", default="tests/validation_results",
                        help="Output directory for snapshots (default: tests/validation_results)")
    args = parser.parse_args()

    size_mb  = args.size
    hold_sec = args.hold
    serial   = args.serial

    print(f"Memory Skill Validation")
    print(f"  Device: {serial}")
    print(f"  Size:   {size_mb} MB per test")
    print(f"  Hold:   {hold_sec} seconds")
    print(f"  Tests:  {args.test}")

    results = {}

    TESTS = {
        "malloc": {
            "binary":   "test_malloc_alloc",
            "args":     f"--size {size_mb} --hold {hold_sec}",
            "check_fn": check_malloc,
        },
        "mmap": {
            "binary":   "test_mmap_alloc",
            "args":     f"--size {size_mb} --hold {hold_sec}",
            "check_fn": check_mmap,
        },
        "dmabuf": {
            "binary":   "test_dmabuf_alloc",
            "args":     f"--size {size_mb} --hold {hold_sec}",
            "check_fn": check_dmabuf,
        },
        "shmem": {
            "binary":   "test_shmem_alloc",
            "args":     f"--size {size_mb} --hold {hold_sec}",
            "check_fn": check_shmem,
        },
        "kmalloc": {
            "binary":   None,  # kernel module -- manual
            "args":     f"size_mb={size_mb}",
            "check_fn": check_kmalloc,
        },
    }

    to_run = list(TESTS.keys()) if args.test == "all" else [args.test]

    for test_name in to_run:
        t = TESTS[test_name]

        if test_name == "kmalloc":
            print(f"\n{'='*60}")
            print(f"TEST: kmalloc (kernel module -- manual steps required)")
            print(f"{'='*60}")
            print(f"  1. Build: cd tests/kernel && make")
            print(f"  2. Push:  adb push tests/kernel/test_kmalloc_module.ko /data/local/tmp/")
            print(f"  3. Load:  adb shell insmod /data/local/tmp/test_kmalloc_module.ko size_mb={size_mb}")
            print(f"  4. Collect baseline + active snapshots manually")
            print(f"  5. Unload: adb shell rmmod test_kmalloc_module")
            print(f"  SKIP: automated run not supported for kernel module")
            results[test_name] = None
            continue

        passed = run_test(
            serial=serial,
            test_name=test_name,
            binary=t["binary"],
            args_str=t["args"],
            size_mb=size_mb,
            hold_sec=hold_sec,
            output_base=args.output_dir,
            check_fn=t["check_fn"],
        )
        results[test_name] = passed

    # Summary
    print(f"\n{'='*60}")
    print("VALIDATION SUMMARY")
    print(f"{'='*60}")
    passed_count = 0
    failed_count = 0
    skipped_count = 0
    for name, result in results.items():
        if result is None:
            print(f"  SKIP  {name}")
            skipped_count += 1
        elif result:
            print(f"  PASS  {name}")
            passed_count += 1
        else:
            print(f"  FAIL  {name}")
            failed_count += 1
    print(f"\n  {passed_count} passed, {failed_count} failed, {skipped_count} skipped")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())