# Memory Skill Validation Tests

End-to-end validation tests that verify the memory skill correctly tracks
known memory allocations on a live device.

## Test programs

| Program | Allocation type | Skill category | meminfo field |
|---|---|---|---|
| `test_malloc_alloc` | `malloc` + `memset` | User Space | `AnonPages` |
| `test_mmap_alloc` | `mmap(MAP_ANONYMOUS)` | User Space | `AnonPages` |
| `test_dmabuf_alloc` | `/dev/dma_heap` DMA-BUF | HW Buffers | DMA-BUF debugfs |
| `test_shmem_alloc` | `shm_open` + `mmap(MAP_SHARED)` | User Space | `Shmem` |
| `test_kmalloc_module` | `kmalloc` (kernel) | Kernel Dynamic | `Slab` / `SUnreclaim` |

All sizes are configurable via `--size <MB>`.

---

## Build

### Userspace tests (cross-compile for aarch64)

```bash
cd tests
make CC=aarch64-linux-gnu-gcc
```

### Push to device

```bash
make push   # requires ADB in PATH
```

### Kernel module (on device or with matching kernel headers)

```bash
cd tests/kernel
make KDIR=/lib/modules/$(uname -r)/build
```

---

## Run automated validation

```bash
# Run all userspace tests (50 MB each, 30s hold)
python tests/run_validation.py --serial <adb_serial> --size 50 --hold 30

# Run a single test
python tests/run_validation.py --serial <adb_serial> --test malloc --size 100

# Available tests: malloc, mmap, dmabuf, shmem, kmalloc
```

### Expected output

```
Memory Skill Validation
  Device: 4cc505ea
  Size:   50 MB per test
  Hold:   30 seconds

============================================================
TEST: malloc  (size=50 MB, hold=30s)
============================================================
  Collecting baseline snapshot...
  Starting: nohup /data/local/tmp/test_malloc_alloc --size 50 --hold 30 ...
  Collecting active snapshot...
  Results:
    [PASS] AnonPages: expected ~50 MB, got 51 MB (tolerance ±15%)
    [PASS] DMA-BUF unchanged: delta=0 MB (expected ~0)

============================================================
VALIDATION SUMMARY
============================================================
  PASS  malloc
  PASS  mmap
  PASS  dmabuf
  PASS  shmem
  SKIP  kmalloc  (manual -- see below)

  4 passed, 0 failed, 1 skipped
```

---

## Kernel module test (manual)

The `test_kmalloc_module` requires manual steps because loading kernel modules
requires root and matching kernel headers:

```bash
# 1. Build (on device or cross-compile)
cd tests/kernel && make

# 2. Push to device
adb push test_kmalloc_module.ko /data/local/tmp/

# 3. Collect baseline snapshot
python internal/data-collection/scripts/collect.py -s <serial> --output tests/validation_results/kmalloc/baseline/

# 4. Load module (allocates N MB via kmalloc)
adb shell insmod /data/local/tmp/test_kmalloc_module.ko size_mb=100

# 5. Collect active snapshot
python internal/data-collection/scripts/collect.py -s <serial> --output tests/validation_results/kmalloc/active/

# 6. Unload module (frees memory)
adb shell rmmod test_kmalloc_module

# 7. Verify: Slab and SUnreclaim should have increased by ~100 MB
```

---

## Tolerance

Each test allows ±15% tolerance to account for:
- OS overhead (kernel metadata, page alignment)
- Other system activity during the test
- Slab fragmentation (kernel allocations)

---

## What these tests validate

1. **Parser correctness** -- `Active(file)`, `Inactive(anon)` etc. are parsed correctly
2. **Category attribution** -- malloc shows in AnonPages, not DMA-BUF
3. **DMA-BUF isolation** -- DMA-BUF allocation does NOT appear in AnonPages/PSS
4. **Shmem isolation** -- shm_open shows in Shmem, not AnonPages
5. **Kernel slab tracking** -- kmalloc shows in Slab/SUnreclaim