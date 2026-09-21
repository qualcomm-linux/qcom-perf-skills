#!/usr/bin/env python3
"""
test_malloc_alloc.py -- Memory skill validation: userspace heap allocation

Allocates N MB via bytearray (equivalent to malloc+memset).
Expected skill delta: AnonPages +N MB, Shmem unchanged.

Usage:
    python3 test_malloc_alloc.py --size 50 [--hold 60]
"""
import argparse
import time
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, required=True, help="MB to allocate")
    parser.add_argument("--hold", type=int, default=60, help="Seconds to hold (default: 60)")
    args = parser.parse_args()

    size_bytes = args.size * 1024 * 1024

    print(f"[test_malloc_alloc] PID={os.getpid()}")
    print(f"[test_malloc_alloc] Allocating {args.size} MB via bytearray (heap)...")

    # bytearray allocates on heap and initializes to zero (touches all pages)
    buf = bytearray(size_bytes)
    # Write pattern to ensure physical allocation
    for i in range(0, size_bytes, 4096):
        buf[i] = 0xAB

    print(f"[test_malloc_alloc] Allocated {args.size} MB. Holding for {args.hold} seconds.")
    print(f"[test_malloc_alloc] Expected skill delta: AnonPages +{args.size} MB")
    print(f"[test_malloc_alloc] Collect snapshot now, then wait for 'Done'.")

    time.sleep(args.hold)

    del buf
    print(f"[test_malloc_alloc] Freed {args.size} MB. Done.")

if __name__ == "__main__":
    main()