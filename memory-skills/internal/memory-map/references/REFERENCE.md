# Memory Map Analyzer — Reference

Full methodology, file inventory, and output schema for the `memory-map` skill.

---

## Memory Breakdown Methodology

### Total Physical RAM

```
Total Physical = (highest iomem System RAM end + 1) - lowest reserved-memory base
```

The lowest reserved-memory address (e.g. `hyp@0x80000000`) anchors the start of
physical RAM. The highest iomem System RAM end address anchors the end. This gives
the true physical address range of the SoC's RAM.

> **Why not use the device tree memory node sum?**
> The DT memory node lists only the banks given to Linux (System RAM). It does NOT
> include NHLOS banks. Using it as total physical would give NHLOS = 0.

### NHLOS

```
NHLOS = Total Physical - System RAM
```

Broken down into named carveouts from the device tree `reserved-memory` nodes.
Each node's `reg` property gives the base address and size. Any gap between the
sum of named nodes and the total NHLOS is shown as **Unaccounted**.

### Kernel Static

```
Kernel Static = System RAM - MemTotal
```

Captures all memory reserved within System RAM that Linux does not report as
usable: kernel image (code + data + bss), crash kernel region, firmware blobs,
and other reserved sub-regions.

---

## Files Pulled from Device

| Local File | Remote Path | Required | Notes |
|---|---|---|---|
| `meminfo.txt` | `/proc/meminfo` | Yes | HLOS Kernel and Userspace accounting. |
| `iomem.txt` | `/proc/iomem` | Yes | Highest RAM address for total physical calculation. |
| `dt_memory_reg.bin` | `/sys/firmware/devicetree/base/memory@*/reg` | Yes | System RAM bank sizes. |
| `reserved-memory/*.bin` | `/sys/firmware/devicetree/base/reserved-memory/*/reg` | Yes | NHLOS carve-out sizes and base addresses. |
| `slabinfo.txt` | `/proc/slabinfo` | No | Total + per-slab breakdown. |
| `vmstat.txt` | `/proc/vmstat` | No | DMA-BUF Cache (reclaimable kernel memory). |
| `zoneinfo.txt` | `/proc/zoneinfo` | No | Per-zone memory statistics + Zones sheet. |
| `buddyinfo.txt` | `/proc/buddyinfo` | No | Buddy allocator state. |
| `pagetypeinfo.txt` | `/proc/pagetypeinfo` | No | Page type distribution. |
| `modules.txt` | `/proc/modules` | No | Total + per-module breakdown. |
| `vmallocinfo.txt` | `/proc/vmallocinfo` | No | Per-function vmalloc breakdown. |
| `dmesg.txt` | `dmesg` (full) | No | Kernel Page Structs + Hash Tables + vmlinux breakup. |
| `config.txt` | `zcat /proc/config.gz` | No | Full kernel config dump. |
| `dmabuf_bufinfo.txt` | `/sys/kernel/debug/dma_buf/bufinfo` | No | Total + per-allocator DMA-BUF breakdown. |
| `kgsl_alloc.txt` | `/sys/class/kgsl/kgsl/page_alloc` | No | Total KGSL GPU memory. |
| `kgsl_procs/` | `/sys/class/kgsl/kgsl/proc` | No | Per-process KGSL memory. |
| `cma_used.txt` | `/sys/kernel/debug/cma/*/used` | No | CMA used per region. |
| `zram_stat.txt` | `/sys/block/zram0/mm_stat` | No | ZRAM statistics. |
| `memory_state.txt` | `/sys/devices/system/memory/memory*/state` | No | Offlined memory banks. |
| `procrank.txt` | `procrank -p` | No | Per-process PSS/PSwap (if procrank available). |

---

## Excel Sheets (`memory_report.xlsx`)

| Sheet | Content |
|---|---|
| **Summary** | Device info + top-level breakdown (Total Physical, NHLOS, System RAM, MemTotal, Kernel Static, Used, Free) |
| **NHLOS** | Named carve-outs + CMA used per region |
| **KernelStatic** | vmlinux breakup + Kernel Page Structs + Hash Tables + Zones |
| **Slab Info** | Per-slab name, size (MB), object size (bytes), object count |
| **Vmalloc** | Per-function vmalloc, size (KB) |
| **PageTable KStack** | PageTables + KernelStack totals |
| **Modules** | Per-module, size (KB) |
| **User space apps** | Per-process PSS/PSwap from procrank (if available) |
| **KGSL** | Per-process GPU memory |
| **DMA-BUF** | Per-allocator DMA-BUF breakdown (replaces old ION) |
| **MemoryLayout** | Physical address map (carveout name, start, end, size) |
| **Kernel Configs** | Full CONFIG_KEY to value dump |
| **Used Memory** | Used memory sub-categories with % of MemTotal |
| **Free Memory** | Free memory sub-categories with % of MemTotal |

---

## Known Qualcomm NHLOS Carveout Names

| Carveout | Subsystem |
|---|---|
| `mpss` | Modem Processor SubSystem |
| `adsp` | Audio DSP |
| `cdsp` | Compute DSP |
| `cdsp-secure-heap` | CDSP Secure Heap |
| `trusted-apps` | TrustZone / QTEE |
| `wpss` | WiFi Processor SubSystem |
| `wlan-fw` | WLAN Firmware |
| `video` | Video Codec |
| `hyp` | Hypervisor |
| `camera` | Camera |
| `cvp` | Computer Vision Processor |
| `qtee` | Qualcomm Trusted Execution Environment |
| `smem` | Shared Memory |
| `tags` | Tags region |

---

## DMA-BUF vs ION

- Kernels >= 5.15: use `/sys/kernel/debug/dma_buf/bufinfo`
- Older kernels: use `/sys/kernel/debug/ion/`
- The skill probes both and prefers `dma_buf`

---

## Changelog

| Version | Date | Notes |
|---|---|---|
| 1.2.0 | 2026-08-10 | Renamed ION to DMA-BUF throughout. Added 10 new parsers. Excel expanded to 14 sheets. HTML updated with KernelStatic detail. 6 new files pulled from device. |
| 1.1.0 | 2026-08-07 | Added Excel report (memory_report.xlsx, 4 sheets). Added --compare DIR1 DIR2 mode. |
| 1.0.0 | 2026-07-29 | Initial release. NHLOS from device-tree reserved-memory nodes. Total Physical from iomem range. Kernel Static = System RAM - MemTotal. |