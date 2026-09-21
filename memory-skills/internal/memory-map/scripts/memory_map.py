#!/usr/bin/env python3
# =============================================================================
# Skill        : memory-map
# Display Name : Qualcomm Linux Memory Map Analyzer
# Version      : 0.0.1
# Platform     : Qualcomm Linux
# Author       : Jagadeesh Pagadala <jpagadal@qti.qualcomm.com>
# Description  : Connects to a Qualcomm Linux device via ADB, pulls
#                /proc/meminfo, /proc/iomem, /proc/vmstat, /proc/modules,
#                /proc/vmallocinfo, /proc/slabinfo, device-tree
#                memory/reserved-memory nodes, dmesg, kernel config, and
#                optional GPU/DMA-BUF/ZRAM files, then categorizes physical
#                memory into:
#
#                  NHLOS        - Non-High Level OS (modem, DSP, TrustZone, ...)
#                  Kernel Static - System RAM - MemTotal
#                  Used Memory  - MemTotal - Total_Free
#                  Slab / Vmalloc / PageTables / Modules / KernelStack
#                  Shmem / KGSL / DMA-BUF / CMA / zUsed / SwapCached / AnonPages
#                  KDA          - Kernel Dynamic Allocations (unaccounted)
#                  Total_Free   - MemFree + Cached + Buffers + DMA-BUF Cache + Offlined
#
# Outputs (written to project root by default):
#   memory_report.html  - primary HTML report with machine details
#   memory_report.txt   - plain-text report
#   memory_report.xlsx  - Excel report with 14 sheets (requires openpyxl)
#   <dump_dir>/         - raw pulled files
#
# Compare mode (--compare DIR1 DIR2):
#   memory_compare.html  - side-by-side HTML comparison
#   memory_compare.txt   - plain-text comparison
#   memory_compare.xlsx  - Excel comparison (requires openpyxl)
#
# Usage        : python scripts/memory_map.py [--serial <serial>] [--output <dir>]
#                python scripts/memory_map.py --no-pull --output mem_dump
#                python scripts/memory_map.py --compare mem_dump_A mem_dump_B
# =============================================================================

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path


# =============================================================================
# ADB helpers
# =============================================================================

def run_adb(args: list[str], serial: str | None = None) -> tuple[int, str, str]:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def check_device(serial: str | None) -> str:
    rc, out, _ = run_adb(["devices"], serial)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    devices = [l for l in lines[1:] if "\tdevice" in l]
    if not devices:
        sys.exit("[ERROR] No ADB device found.")
    if serial:
        matched = [d for d in devices if d.startswith(serial)]
        if not matched:
            serials = [d.split("\t")[0] for d in devices]
            sys.exit(f"[ERROR] Device '{serial}' not found. Available: {serials}")
        return serial
    if len(devices) > 1:
        serials = [d.split("\t")[0] for d in devices]
        sys.exit(f"[ERROR] Multiple devices: {serials}. Use --serial.")
    return devices[0].split("\t")[0]


def pull_text_file(remote: str, local: Path, serial: str | None) -> bool:
    local.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = run_adb(["shell", f"cat {remote}"], serial)
    if rc != 0 or not out.strip():
        print(f"  [SKIP] {remote:<55}  ({err.strip() or 'empty / not found'})")
        return False
    local.write_text(out, encoding="utf-8", errors="replace")
    print(f"  [OK]   {remote:<55}  ->  {local.name}")
    return True


def pull_binary_file(remote: str, local: Path, serial: str | None) -> bool:
    local.parent.mkdir(parents=True, exist_ok=True)
    rc, _, err = run_adb(["pull", remote, str(local)], serial)
    if rc != 0 or not local.exists() or local.stat().st_size == 0:
        if local.exists():
            local.unlink()
        return False
    return True


def find_dt_memory_path(serial: str | None) -> str | None:
    rc, out, _ = run_adb(
        ["shell", "find /sys/firmware/devicetree/base -maxdepth 2 "
                  "-name reg -path '*/memory*' 2>/dev/null"],
        serial,
    )
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def get_device_info(serial: str, out_dir: Path) -> dict[str, str]:
    info: dict[str, str] = {"Serial": serial}
    rc, out, _ = run_adb(
        ["shell", "cat /sys/firmware/devicetree/base/model 2>/dev/null"], serial)
    if out.strip():
        info["Device"] = out.strip().rstrip("\x00")
    for cmd in ["hostname", "cat /etc/hostname"]:
        rc, out, _ = run_adb(["shell", cmd], serial)
        if out.strip():
            info["Hostname"] = out.strip()
            break
    rc, out, _ = run_adb(["shell", "uname -r"], serial)
    if out.strip():
        info["Kernel"] = out.strip()
    rc, out, _ = run_adb(
        ["shell", "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'"],
        serial)
    if out.strip():
        info["OS"] = out.strip()
    for label, prop in [("Build ID", "ro.build.id"), ("Build Desc", "ro.build.description")]:
        rc, out, _ = run_adb(["shell", f"getprop {prop} 2>/dev/null"], serial)
        if out.strip():
            info[label] = out.strip()
    info["Captured"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return info


def pull_all(out_dir: Path, serial: str | None) -> None:
    print("\n[1/4] Pulling files from Qualcomm Linux device ...")

    # -- /proc text files ------------------------------------------------------
    text_files: dict[str, str] = {
        "meminfo":      "/proc/meminfo",
        "iomem":        "/proc/iomem",
        "buddyinfo":    "/proc/buddyinfo",
        "slabinfo":     "/proc/slabinfo",
        "vmstat":       "/proc/vmstat",
        "zoneinfo":     "/proc/zoneinfo",
        "pagetypeinfo": "/proc/pagetypeinfo",
        "modules":      "/proc/modules",
        "vmallocinfo":  "/proc/vmallocinfo",
    }
    for name, remote in text_files.items():
        pull_text_file(remote, out_dir / f"{name}.txt", serial)

    # -- Device tree memory node -----------------------------------------------
    dt_path = find_dt_memory_path(serial)
    if dt_path:
        ok = pull_binary_file(dt_path, out_dir / "dt_memory_reg.bin", serial)
        print(f"  {'[OK]  ' if ok else '[SKIP]'} {dt_path:<55}  ->  dt_memory_reg.bin")
    else:
        print("  [SKIP] device tree memory node not found")

    # -- Device tree reserved-memory nodes -------------------------------------
    DT_RESMEM = "/sys/firmware/devicetree/base/reserved-memory"
    rc, ls_out, _ = run_adb(["shell", f"ls {DT_RESMEM}"], serial)
    _SKIP = {"#address-cells", "#size-cells", "name", "ranges"}
    nodes = [n.strip() for n in ls_out.splitlines()
             if n.strip() and n.strip() not in _SKIP]
    res_dir = out_dir / "reserved-memory"
    res_dir.mkdir(exist_ok=True)
    pulled_res = 0
    for node in nodes:
        if pull_binary_file(f"{DT_RESMEM}/{node}/reg", res_dir / f"{node}.bin", serial):
            pulled_res += 1
    print(f"  [OK]   reserved-memory nodes: {pulled_res}/{len(nodes)} pulled")

    # -- dmesg (full + filtered memory line) -----------------------------------
    rc, out, _ = run_adb(["shell", "dmesg 2>/dev/null"], serial)
    if out.strip():
        (out_dir / "dmesg.txt").write_text(out, encoding="utf-8", errors="replace")
        print(f"  [OK]   dmesg (full)                                              ->  dmesg.txt")
        # Also extract the memory line for quick vmlinux breakup
        mem_lines = [l for l in out.splitlines()
                     if "available" in l and "kernel code" in l and "rwdata" in l]
        if mem_lines:
            (out_dir / "dmesg_memory.txt").write_text(
                "\n".join(mem_lines), encoding="utf-8", errors="replace")
            print(f"  [OK]   dmesg Memory line                                         ->  dmesg_memory.txt")
    else:
        print(f"  [SKIP] dmesg not available")

    # -- Kernel config ---------------------------------------------------------
    rc, out, _ = run_adb(["shell", "zcat /proc/config.gz 2>/dev/null"], serial)
    if out.strip():
        (out_dir / "config.txt").write_text(out, encoding="utf-8", errors="replace")
        print(f"  [OK]   /proc/config.gz                                           ->  config.txt")
    else:
        print(f"  [SKIP] /proc/config.gz not available")

    # -- Optional: DMA-BUF, KGSL, ZRAM, memory banks, CMA used ---------------
    optional: dict[str, str] = {
        "dmabuf_bufinfo": "/sys/kernel/debug/dma_buf/bufinfo",
        "kgsl_alloc":     "/sys/class/kgsl/kgsl/page_alloc",
        "zram_stat":      "/sys/block/zram0/mm_stat",
        "memory_state":   "/sys/devices/system/memory/memory*/state",
        "cma_used":       "/sys/kernel/debug/cma/*/used",
    }
    for name, remote in optional.items():
        pull_text_file(remote, out_dir / f"{name}.txt", serial)

    # -- KGSL per-process directory --------------------------------------------
    kgsl_proc_remote = "/sys/class/kgsl/kgsl/proc"
    kgsl_proc_local  = out_dir / "kgsl_procs"
    rc, ls_out, _ = run_adb(["shell", f"ls {kgsl_proc_remote} 2>/dev/null"], serial)
    if ls_out.strip() and "No such file" not in ls_out:
        kgsl_proc_local.mkdir(exist_ok=True)
        pids = [p.strip() for p in ls_out.splitlines() if p.strip().isnumeric()]
        pulled_kgsl = 0
        for pid in pids:
            pid_dir = kgsl_proc_local / pid
            pid_dir.mkdir(exist_ok=True)
            for fname in ["kernel", "gpumem_reclaimed"]:
                rc2, val, _ = run_adb(
                    ["shell", f"cat {kgsl_proc_remote}/{pid}/{fname} 2>/dev/null"], serial)
                if rc2 == 0 and val.strip():
                    (pid_dir / fname).write_text(val, encoding="utf-8")
                    pulled_kgsl += 1
        print(f"  [OK]   kgsl/proc: {len(pids)} processes pulled")
    else:
        print(f"  [SKIP] /sys/class/kgsl/kgsl/proc not found")

    # -- procrank (if available) -----------------------------------------------
    rc, out, _ = run_adb(["shell", "procrank -p 2>/dev/null"], serial)
    if out.strip() and "not found" not in out and "No such file" not in out:
        (out_dir / "procrank.txt").write_text(out, encoding="utf-8", errors="replace")
        print(f"  [OK]   procrank -p                                               ->  procrank.txt")
    else:
        print(f"  [SKIP] procrank not available")


# =============================================================================
# File parsers
# =============================================================================

def parse_meminfo(path: Path) -> dict[str, int]:
    data: dict[str, int] = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            data[m.group(1)] = int(m.group(2))
    return data


def parse_iomem(path: Path) -> list[dict]:
    regions: list[dict] = []
    for line in path.read_text().splitlines():
        m = re.match(r"^(\s*)([0-9a-f]+)-([0-9a-f]+)\s*:\s*(.+)$", line, re.I)
        if not m:
            continue
        depth = len(m.group(1)) // 2
        start = int(m.group(2), 16)
        end   = int(m.group(3), 16)
        regions.append({
            "start":   start,
            "end":     end,
            "size_kb": (end - start + 1) // 1024,
            "name":    m.group(4).strip(),
            "depth":   depth,
        })
    return regions


def parse_dt_memory(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 16 or len(data) % 16 != 0:
        return 0, 0
    total_bytes = 0
    lowest_base = 2**64
    for i in range(0, len(data), 16):
        base = int.from_bytes(data[i:i+8],   byteorder="big")
        size = int.from_bytes(data[i+8:i+16], byteorder="big")
        total_bytes += size
        if base < lowest_base:
            lowest_base = base
    return total_bytes // 1024, lowest_base


def parse_dt_reserved_memory(res_dir: Path) -> list[dict]:
    regions: list[dict] = []
    for bin_file in sorted(res_dir.glob("*.bin")):
        data = bin_file.read_bytes()
        if len(data) < 16:
            continue
        total_bytes = 0
        base_addr   = None
        for i in range(0, len(data) - 15, 16):
            addr = int.from_bytes(data[i:i+8],   byteorder="big")
            size = int.from_bytes(data[i+8:i+16], byteorder="big")
            if base_addr is None:
                base_addr = addr
            total_bytes += size
        if total_bytes > 0 and base_addr is not None:
            regions.append({
                "name":    bin_file.stem,
                "base":    base_addr,
                "size_kb": total_bytes // 1024,
            })
    return sorted(regions, key=lambda r: -r["size_kb"])


def parse_slabinfo(path: Path) -> int:
    """Return total slab memory in kB."""
    total_pages = 0
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) > 14:
            try:
                total_pages += int(parts[14]) * int(parts[5])
            except (ValueError, IndexError):
                pass
    return total_pages * 4


def parse_slabinfo_detail(path: Path) -> dict[str, tuple[float, int, int]]:
    """Parse /proc/slabinfo for per-slab breakdown.
    Returns dict[name -> (size_mb, obj_size_bytes, num_objs)], sorted by size desc."""
    result: dict[str, tuple[float, int, int]] = {}
    try:
        for line in path.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 15:
                continue
            try:
                name          = parts[0]
                num_objs      = int(parts[2])   # num_objs
                obj_size      = int(parts[3])   # objsize (bytes)
                pages_per_slab = int(parts[5])  # pagesperslab
                num_slabs     = int(parts[14])  # num_slabs
                size_kb       = num_slabs * pages_per_slab * 4
                size_mb       = round(size_kb / 1024, 2)
                result[name]  = (size_mb, obj_size, num_objs)
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -x[1][0]))


def parse_dmesg_memory(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "available (" in line and "kernel code" in line and "rwdata" in line:
                total_part = line.split("available (")[0].split("/")[-1].strip()
                result["system_ram_kb"] = int(total_part.replace("K", "").strip())
                inner = line.split("available (")[1].rstrip(")")
                for token in inner.split(","):
                    token = token.strip()
                    val   = int(token.split()[0].replace("K", ""))
                    if "kernel code" in token:
                        result["k_code_kb"]     = val
                    elif "rwdata" in token:
                        result["k_rwdata_kb"]   = val
                    elif "rodata" in token:
                        result["k_rodata_kb"]   = val
                    elif "init" in token:
                        result["k_init_kb"]     = val
                    elif "bss" in token:
                        result["k_bss_kb"]      = val
                    elif "reserved" in token and "cma" not in token:
                        result["k_reserved_kb"] = val
                break
    except Exception:
        pass
    return result


def parse_dmesg_full(path: Path) -> tuple[float, float]:
    """Parse full dmesg for kernelPageStructs and hashtables.
    Returns (kernel_page_structs_mb, hashtables_mb)."""
    kernel_page_structs_pages = 0
    hashtables_bytes = 0
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "pages used for memmap" in line:
                try:
                    numpages = int(line.split("zone:")[1].split()[0])
                except Exception:
                    try:
                        numpages = int(line.split("pages used for memmap")[0].split()[-1])
                    except Exception:
                        numpages = 0
                kernel_page_structs_pages += numpages
            elif "hash table entries:" in line:
                m = re.search(r"order:\s*\d+,\s*(\d+)", line)
                if m:
                    hashtables_bytes += int(m.group(1))
    except Exception:
        pass
    kernel_page_structs_mb = round(kernel_page_structs_pages * 4 / 1024, 2)
    hashtables_mb          = round(hashtables_bytes / 1024 / 1024, 2)
    return kernel_page_structs_mb, hashtables_mb


def parse_zoneinfo_present(path: Path) -> int:
    total_pages = 0
    current_zone = None
    for line in path.read_text().splitlines():
        if "Node 0, zone" in line:
            current_zone = line.split("Node 0, zone")[1].strip()
        elif current_zone and " present " in line:
            try:
                total_pages += int(line.split("present")[1].strip())
            except (ValueError, IndexError):
                pass
    return total_pages * 4  # 4 kB per page


def parse_zoneinfo_detail(path: Path) -> dict[str, float]:
    """Parse /proc/zoneinfo for per-zone present pages.
    Returns dict[zone_name -> size_mb]."""
    result: dict[str, float] = {}
    current_zone = None
    try:
        for line in path.read_text().splitlines():
            if "Node 0, zone" in line:
                current_zone = line.split("Node 0, zone")[1].strip()
            elif current_zone and " present " in line:
                try:
                    pages   = int(line.split("present")[1].strip())
                    size_mb = round(pages * 4 / 1024, 2)
                    result[current_zone] = result.get(current_zone, 0) + size_mb
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return result


def parse_vmstat_dmabuf_cache(path: Path) -> int:
    """Parse /proc/vmstat for DMA-BUF Cache (reclaimable kernel memory).
    Returns value in kB."""
    for line in path.read_text().splitlines():
        if "nr_kernel_misc_reclaimable" in line:
            try:
                pages = int(line.split()[1])
                return pages * 4
            except (ValueError, IndexError):
                pass
        elif "nr_indirectly_reclaimable" in line:
            try:
                pages = int(line.split()[1])
                return pages * 4
            except (ValueError, IndexError):
                pass
    return 0


def parse_modules(path: Path) -> int:
    """Parse /proc/modules and return total module memory in kB."""
    total_bytes = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                total_bytes += int(parts[1])
            except (ValueError, IndexError):
                pass
    return total_bytes // 1024


def parse_modules_detail(path: Path) -> dict[str, int]:
    """Parse /proc/modules for per-module size breakdown.
    Returns dict[module_name -> size_kb], sorted by size desc."""
    result: dict[str, int] = {}
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    name    = parts[0]
                    size_kb = int(parts[1]) // 1024
                    result[name] = result.get(name, 0) + size_kb
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def parse_dmabuf(path: Path) -> int:
    """Parse /sys/kernel/debug/dma_buf/bufinfo for total DMA-BUF bytes.
    Returns value in kB."""
    try:
        for line in path.read_text().splitlines():
            if "bytes" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "bytes" and i > 0:
                        return int(parts[i-1]) // 1024
                m = re.search(r"(\d+)\s+bytes", line)
                if m:
                    return int(m.group(1)) // 1024
    except Exception:
        pass
    return 0


def parse_dmabuf_detail(path: Path) -> dict[str, float]:
    """Parse /sys/kernel/debug/dma_buf/bufinfo for per-allocator DMA-BUF breakdown.
    Returns dict[allocator -> size_mb], sorted by size desc."""
    result: dict[str, float] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if (not line or line.startswith("Dma-buf") or line.startswith("size")
                    or line.startswith("Total") or line.startswith("Attached")
                    or "devices attached" in line):
                continue
            parts = line.split()
            if len(parts) >= 5:
                try:
                    # size column is decimal bytes (e.g. 00262144 = 262144 bytes)
                    size_bytes = int(parts[0])
                    allocator  = parts[4]   # exp_name column
                    size_mb    = size_bytes / 1024 / 1024
                    result[allocator] = result.get(allocator, 0) + size_mb
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return {k: round(v, 2) for k, v in sorted(result.items(), key=lambda x: -x[1])}


def parse_kgsl(path: Path) -> int:
    """Parse /sys/class/kgsl/kgsl/page_alloc for GPU memory in kB."""
    try:
        val = path.read_text().strip()
        if val:
            return int(val) // 1024
    except Exception:
        pass
    return 0


def parse_kgsl_procs(procs_dir: Path) -> dict[str, float]:
    """Parse /sys/class/kgsl/kgsl/proc/<pid>/kernel for per-process KGSL.
    Returns dict[pid -> size_mb], sorted by size desc."""
    result: dict[str, float] = {}
    try:
        for pid_dir in sorted(procs_dir.iterdir()):
            if not pid_dir.is_dir():
                continue
            kernel_file = pid_dir / "kernel"
            if kernel_file.exists():
                try:
                    size_bytes = int(kernel_file.read_text().strip())
                    size_mb    = round(size_bytes / 1024 / 1024, 2)
                    if size_mb > 0:
                        result[pid_dir.name] = size_mb
                except (ValueError, OSError):
                    pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def parse_zram(path: Path) -> tuple[int, int]:
    """Parse /sys/block/zram0/mm_stat. Returns (zram_orig_kb, zram_used_kb)."""
    try:
        parts = path.read_text().split()
        if len(parts) >= 3:
            zorig = int(parts[0]) // 1024
            zused = int(parts[2]) // 1024
            return zorig, zused
    except Exception:
        pass
    return 0, 0


def parse_offlined(path: Path) -> int:
    """Parse memory*/state for offline banks. Returns total offline memory in kB."""
    try:
        block_size_path = path.parent / "block_size_bytes"
        if block_size_path.exists():
            block_size_mb = int(block_size_path.read_text().strip(), 16) // (1024 * 1024)
        else:
            block_size_mb = 128
        offline_count = path.read_text().count("offline")
        return offline_count * block_size_mb * 1024
    except Exception:
        pass
    return 0


def parse_vmallocinfo(path: Path) -> dict[str, int]:
    """Parse /proc/vmallocinfo for per-function vmalloc breakdown.
    Returns dict[function_name -> size_kb], sorted by size desc."""
    _SKIP = {"module_alloc_update_bounds", "dup_task_struct", "binder_alloc",
             "load_module", "copy_process", "kernel_clone", "move_module", "do_fork"}
    result: dict[str, int] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "vmalloc" not in line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            fn = parts[2].split("+")[0].split(".")[0]
            if fn in _SKIP:
                continue
            try:
                if "pages=" in line:
                    size_kb = int(line.split("pages=")[1].split()[0]) * 4
                else:
                    size_kb = int(parts[1]) // 1024
                result[fn] = result.get(fn, 0) + size_kb
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def parse_cma_used(path: Path) -> dict[str, float]:
    """Parse /sys/kernel/debug/cma/*/used for CMA used per region.
    Returns dict[region_name -> size_mb]."""
    result: dict[str, float] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if (not line or "No such file" in line or "No data for CMA" in line
                    or "base_pfn" in line):
                continue
            parts = line.split(":") if ":" in line else line.split()
            if len(parts) >= 2:
                name = parts[0].strip()
                name = (name.replace("/sys/kernel/debug/cma/", "")
                            .replace("/used", "")
                            .replace("cma-", "")
                            .replace("@", ""))
                try:
                    pages   = int(parts[-1].strip())
                    size_mb = round(pages * 4 / 1024, 2)
                    result[name] = result.get(name, 0) + size_mb
                except ValueError:
                    pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def parse_kconfig(path: Path) -> dict[str, str]:
    """Parse decompressed /proc/config.gz for kernel config options.
    Returns dict[CONFIG_KEY -> value]."""
    result: dict[str, str] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip().strip('"')
    except Exception:
        pass
    return result


def parse_procrank(path: Path) -> dict[str, tuple[int, int]]:
    """Parse procrank -p output for per-process PSS/PSwap.
    Returns dict[process_name -> (pss_kb, pswap_kb)], sorted by total desc."""
    result: dict[str, tuple[int, int]] = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or "PID" in line or "------" in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                pss_kb   = int(parts[3].rstrip("K"))
                pswap_kb = int(parts[4].rstrip("K")) if len(parts) > 4 else 0
                cmdline  = parts[-1]
                result[cmdline] = (pss_kb, pswap_kb)
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return dict(sorted(result.items(), key=lambda x: -(x[1][0] + x[1][1])))


def build_memory_layout(iomem_regions: list[dict],
                         reserved_regions: list[dict]) -> list[tuple]:
    """Build physical memory layout from iomem and reserved-memory data.

    Each System RAM block is split into:
      - accessible sub-regions  (region_type = 'sysram')
      - reserved sub-regions    (region_type = 'kstatic')  <- depth-1+ iomem entries
    NHLOS carve-outs are 'nhlos'; address gaps are 'missing'.

    Returns list of (name, start, end, size_mb, region_type), sorted by address.
    Total of all entries ~ Total Physical RAM.
    """
    layout: list[tuple] = []

    # Collect depth-1+ sub-entries (reserved within System RAM)
    sub_entries = [
        (r["name"], r["start"], r["end"] + 1,
         round((r["end"] - r["start"] + 1) / 1024 / 1024, 2))
        for r in iomem_regions if r["depth"] > 0
    ]

    # For each depth-0 System RAM block, split into accessible + reserved parts
    for r in iomem_regions:
        if r["name"] != "System RAM" or r["depth"] != 0:
            continue
        block_start = r["start"]
        block_end   = r["end"] + 1

        # Sub-entries that fall within this block
        block_subs = sorted(
            [(n, s, e, mb) for n, s, e, mb in sub_entries
             if s >= block_start and e <= block_end],
            key=lambda x: x[1],
        )

        if not block_subs:
            # No reserved sub-regions -- entire block is accessible
            layout.append(("System RAM", block_start, block_end,
                            round((block_end - block_start) / 1024 / 1024, 2),
                            "sysram"))
        else:
            prev = block_start
            for name, s, e, mb in block_subs:
                if s > prev:
                    layout.append(("System RAM", prev, s,
                                   round((s - prev) / 1024 / 1024, 2), "sysram"))
                layout.append((name, s, e, mb, "kstatic"))
                prev = e
            if prev < block_end:
                layout.append(("System RAM", prev, block_end,
                               round((block_end - prev) / 1024 / 1024, 2), "sysram"))

    # NHLOS carve-outs from reserved-memory bins
    for r in reserved_regions:
        size_bytes = r["size_kb"] * 1024
        layout.append((
            r["name"].split("@")[0],
            r["base"],
            r["base"] + size_bytes,
            round(r["size_kb"] / 1024, 2),
            "nhlos",
        ))

    if not layout:
        return layout

    # Sort by start address
    layout.sort(key=lambda x: x[1])

    # Fill address gaps with "Missing" entries
    filled: list[tuple] = []
    prev_end = layout[0][1]
    for entry in layout:
        name, start, end, size_mb, region_type = entry
        if start > prev_end:
            gap_bytes = start - prev_end
            gap_mb    = round(gap_bytes / 1024 / 1024, 2)
            if gap_mb > 0:
                filled.append(("Missing", prev_end, start, gap_mb, "missing"))
        filled.append(entry)
        if end > prev_end:
            prev_end = end

    return filled


# =============================================================================
# iomem analysis
# =============================================================================

_SYSTEM_RAM_RE = re.compile(r"^System RAM$", re.I)


def extract_iomem_info(regions: list[dict]) -> dict:
    system_ram_kb = 0
    highest_end   = 0
    lowest_start  = 2**64
    nonzero_count = 0
    for r in regions:
        if r["start"] != 0 or r["end"] != 0:
            nonzero_count += 1
        if _SYSTEM_RAM_RE.match(r["name"]) and r["depth"] == 0:
            system_ram_kb += r["size_kb"]
            if r["end"] > highest_end:
                highest_end = r["end"]
            if r["start"] < lowest_start:
                lowest_start = r["start"]
    return {
        "system_ram_kb":    system_ram_kb,
        "highest_end":      highest_end,
        "lowest_start":     lowest_start if lowest_start < 2**64 else 0,
        "iomem_obfuscated": (nonzero_count == 0),
    }


# =============================================================================
# Memory breakdown computation
# =============================================================================

def compute_breakdown(
    meminfo:           dict[str, int],
    system_ram_kb:     int,
    total_phys_kb:     int,
    reserved_regions:  list[dict],
    slab_kb:           int,
    modules_kb:        int,
    dmabuf_kb:         int,
    kgsl_kb:           int,
    dmabuf_cache_kb:   int,
    offlined_kb:       int,
    zram_orig_kb:      int,
    zram_used_kb:      int,
) -> dict:
    """Build a structured memory breakdown. All values in kB."""
    mem_total_kb   = meminfo.get("MemTotal", 0)
    mem_free_kb    = meminfo.get("MemFree", 0)
    buffers_kb     = meminfo.get("Buffers", 0)
    cached_kb      = meminfo.get("Cached", 0)
    swap_cached_kb = meminfo.get("SwapCached", 0)
    anon_pages_kb  = meminfo.get("AnonPages", 0)
    shmem_kb       = meminfo.get("Shmem", 0)
    cma_kb         = meminfo.get("CmaTotal", 0)

    nhlos_kb       = max(0, total_phys_kb - system_ram_kb)
    named_nhlos_kb = sum(r["size_kb"] for r in reserved_regions)
    unaccounted_kb = max(0, nhlos_kb - named_nhlos_kb)

    kernel_static_kb = max(0, system_ram_kb - mem_total_kb)

    cached_excl_shmem_kb = max(0, cached_kb - shmem_kb)
    total_free_kb = (mem_free_kb + cached_excl_shmem_kb + buffers_kb
                     + dmabuf_cache_kb + offlined_kb)

    linux_fw_kb = max(0, total_phys_kb - nhlos_kb - kernel_static_kb - total_free_kb)

    slab_kb_used   = meminfo.get("Slab", slab_kb)
    vmalloc_kb     = meminfo.get("VmallocUsed", 0)
    pagetables_kb  = meminfo.get("PageTables", 0)
    kernelstack_kb = meminfo.get("KernelStack", 0)
    percpu_kb      = meminfo.get("Percpu", 0)
    sec_pt_kb      = meminfo.get("SecPageTables", 0)

    kda_kb = (mem_total_kb - total_free_kb
              - slab_kb_used - dmabuf_kb - vmalloc_kb - pagetables_kb - modules_kb
              - kgsl_kb - swap_cached_kb - anon_pages_kb - zram_used_kb
              - kernelstack_kb - shmem_kb - cma_kb
              - percpu_kb - sec_pt_kb)
    kda_kb = max(0, kda_kb)

    return {
        "total_physical_kb":  total_phys_kb,
        "system_ram_kb":      system_ram_kb,
        "nhlos_kb":           nhlos_kb,
        "named_nhlos_kb":     named_nhlos_kb,
        "unaccounted_kb":     unaccounted_kb,
        "nhlos_regions":      reserved_regions,
        "mem_total_kb":       mem_total_kb,
        "kernel_static_kb":   kernel_static_kb,
        "linux_fw_kb":        linux_fw_kb,
        "total_free_kb":      total_free_kb,
        "slab_kb":            slab_kb_used,
        "vmalloc_kb":         vmalloc_kb,
        "pagetables_kb":      pagetables_kb,
        "modules_kb":         modules_kb,
        "kernelstack_kb":     kernelstack_kb,
        "percpu_kb":          percpu_kb,
        "sec_pt_kb":          sec_pt_kb,
        "shmem_kb":           shmem_kb,
        "kda_kb":             kda_kb,
        "anon_pages_kb":      anon_pages_kb,
        "kgsl_kb":            kgsl_kb,
        "dmabuf_kb":          dmabuf_kb,
        "cma_kb":             cma_kb,
        "zram_used_kb":       zram_used_kb,
        "swap_cached_kb":     swap_cached_kb,
        "mem_free_kb":        mem_free_kb,
        "cached_kb":          cached_kb,
        "buffers_kb":         buffers_kb,
        "dmabuf_cache_kb":    dmabuf_cache_kb,
        "offlined_kb":        offlined_kb,
        "zram_orig_kb":       zram_orig_kb,
        "zram_savings_kb":    max(0, zram_orig_kb - zram_used_kb),
    }


# =============================================================================
# Report rendering (TXT)
# =============================================================================

def _mb(kb: int) -> str:
    return f"{kb / 1024:>10.2f} MB"


def _pct(part: int, total: int) -> str:
    return f"{100.0 * part / total:>5.1f}%" if total else "   N/A"


def _render_report(bd: dict, device_info: dict, vmlinux_kb: int = 0,
                   vmlinux_detail: dict | None = None) -> list[str]:
    total_phys = bd["total_physical_kb"]
    sys_ram    = bd["system_ram_kb"]
    nhlos      = bd["nhlos_kb"]
    mem_total  = bd["mem_total_kb"]
    k_static   = bd["kernel_static_kb"]
    linux_fw   = bd["linux_fw_kb"]
    total_free = bd["total_free_kb"]
    SEP        = "=" * 72
    out: list[str] = []

    def row(label: str, kb: int, ref: int) -> None:
        out.append(f"  {label:<40} {_mb(kb)}   {_pct(kb, ref)}")

    out.append(SEP)
    out.append("  QUALCOMM LINUX - MEMORY MAP BREAKDOWN")
    out.append(SEP)
    for k, v in device_info.items():
        out.append(f"  {k:<16}: {v}")
    out.append(SEP)
    out.append(f"  {'Category':<40} {'Size':>12}   {'%':>6}")
    out.append("-" * 72)
    row("Total Physical RAM", total_phys, total_phys)
    out.append("-" * 72)

    out.append("\n  -- NHLOS (Non-High Level OS) ------------------------------------------")
    row("  NHLOS Total", nhlos, total_phys)
    if bd["nhlos_regions"]:
        out.append(f"\n  {'  Carve-out':<42} {'Size':>12}   {'% of NHLOS':>10}")
        out.append("  " + "-" * 68)
        for r in bd["nhlos_regions"]:
            label = "  " + r["name"].split("@")[0]
            out.append(f"  {label:<42} {_mb(r['size_kb'])}   {_pct(r['size_kb'], nhlos)}")
        if bd["unaccounted_kb"]:
            out.append(f"  {'  Unaccounted':<42} {_mb(bd['unaccounted_kb'])}   "
                       f"{_pct(bd['unaccounted_kb'], nhlos)}")

    out.append("\n  -- HLOS (High Level OS - Linux) ---------------------------------------")
    row("  System RAM", sys_ram, total_phys)
    row("  MemTotal", mem_total, total_phys)

    out.append("\n  -- Kernel Static  (System RAM - MemTotal) -----------------------------")
    row("  Kernel Static", k_static, sys_ram)
    if vmlinux_kb:
        row(f"    vmlinux  (code+rw+ro+bss)", vmlinux_kb, k_static)
        for k, v in (vmlinux_detail or {}).items():
            if v:
                out.append(f"  {'      ' + k:<40} {_mb(v)}   {_pct(v, k_static)}")
        ks_unacc = max(0, k_static - vmlinux_kb)
        if ks_unacc:
            row(f"    Unaccounted (crash kernel, firmware, ...)", ks_unacc, k_static)

    out.append("\n  -- Used Memory  (MemTotal - Total_Free) -------------")
    row("  Used Memory", linux_fw, mem_total)
    out.append(f"\n  {'  Sub-category':<42} {'Size':>12}   {'% of MemTotal':>13}")
    out.append("  " + "-" * 68)
    for label, key in [
        ("Slab",          "slab_kb"),
        ("Vmalloc",       "vmalloc_kb"),
        ("PageTables",    "pagetables_kb"),
        ("Modules",       "modules_kb"),
        ("KernelStack",   "kernelstack_kb"),
        ("Percpu",        "percpu_kb"),
        ("SecPageTables", "sec_pt_kb"),
        ("Shmem",         "shmem_kb"),
        ("KDA",           "kda_kb"),
        ("AnonPages",     "anon_pages_kb"),
        ("KGSL",          "kgsl_kb"),
        ("DMA-BUF",       "dmabuf_kb"),
        ("CMA",           "cma_kb"),
        ("zUsed",         "zram_used_kb"),
        ("SwapCached",    "swap_cached_kb"),
    ]:
        v = bd.get(key, 0)
        if v:
            out.append(f"  {'  ' + label:<42} {_mb(v)}   {_pct(v, mem_total)}")

    out.append("\n  -- Total Free  (MemFree + Cached + Buffers + DMA-BUF Cache + Offlined) ")
    row("  Total_Free", total_free, mem_total)
    for label, key in [
        ("MemFree",        "mem_free_kb"),
        ("Cached",         "cached_kb"),
        ("Buffers",        "buffers_kb"),
        ("DMA-BUF Cache",  "dmabuf_cache_kb"),
        ("Offlined",       "offlined_kb"),
    ]:
        v = bd.get(key, 0)
        if v:
            out.append(f"  {'  ' + label:<42} {_mb(v)}   {_pct(v, mem_total)}")

    if bd.get("zram_orig_kb"):
        out.append("\n  -- ZRAM ---------------------------------------------------------------")
        row("  zOrig (uncompressed)", bd["zram_orig_kb"], mem_total)
        row("  zUsed (physical)",     bd["zram_used_kb"], mem_total)
        row("  zSavings",             bd["zram_savings_kb"], mem_total)

    out.append(f"\n{SEP}")
    row("  Grand Total  (NHLOS + System RAM)", nhlos + sys_ram, total_phys)
    out.append(SEP)
    return out


def print_report(bd: dict, device_info: dict, vmlinux_kb: int = 0,
                 vmlinux_detail: dict | None = None) -> None:
    for line in _render_report(bd, device_info, vmlinux_kb, vmlinux_detail):
        print(line)


def save_report(bd: dict, device_info: dict, report_dir: Path,
                vmlinux_kb: int = 0, vmlinux_detail: dict | None = None) -> None:
    path = report_dir / "memory_report.txt"
    path.write_text(
        "\n".join(_render_report(bd, device_info, vmlinux_kb, vmlinux_detail)) + "\n",
        encoding="utf-8")
    print(f"[4/4] TXT  saved : {path}")


# =============================================================================
# HTML report
# =============================================================================

def save_html(bd: dict, device_info: dict, report_dir: Path,
              vmlinux_kb: int = 0, vmlinux_detail: dict | None = None,
              kernel_page_structs_mb: float = 0,
              hashtables_mb: float = 0) -> None:
    total  = bd["total_physical_kb"]
    sysram = bd["system_ram_kb"]
    nhlos  = bd["nhlos_kb"]
    mt     = bd["mem_total_kb"]
    k_stat = bd["kernel_static_kb"]
    fw     = bd["linux_fw_kb"]
    tfree  = bd["total_free_kb"]

    def mb(kb: int) -> str:
        return f"{kb / 1024:.2f}"

    def pct(part: int, ref: int) -> str:
        return f"{100.0 * part / ref:.1f}" if ref else "0.0"

    def bar(part: int, ref: int, color: str) -> str:
        w = max(1, round(100.0 * part / ref)) if ref else 0
        return (f'<div style="background:#e8e8e8;border-radius:4px;height:14px;'
                f'width:200px;display:inline-block">'
                f'<div style="background:{color};width:{w}%;height:100%;'
                f'border-radius:4px"></div></div>')

    dev_rows = "".join(
        f'<tr><td class="di-label">{k}</td><td class="di-val">{v}</td></tr>\n'
        for k, v in device_info.items()
    )

    nhlos_rows = ""
    for r in bd["nhlos_regions"]:
        name = r["name"].split("@")[0]
        nhlos_rows += (
            f'<tr><td style="padding-left:24px;color:#555">{name}</td>'
            f'<td class="num">{mb(r["size_kb"])} MB</td>'
            f'<td class="num">{pct(r["size_kb"], nhlos)}%</td>'
            f'<td>{bar(r["size_kb"], nhlos, "#e07b39")}</td></tr>\n'
        )
    if bd["unaccounted_kb"]:
        nhlos_rows += (
            f'<tr><td style="padding-left:24px;color:#999;font-style:italic">Unaccounted</td>'
            f'<td class="num">{mb(bd["unaccounted_kb"])} MB</td>'
            f'<td class="num">{pct(bd["unaccounted_kb"], nhlos)}%</td>'
            f'<td>{bar(bd["unaccounted_kb"], nhlos, "#ccc")}</td></tr>\n'
        )

    # Kernel Static detail rows
    kstat_detail_rows = ""
    if vmlinux_kb:
        kstat_detail_rows += (
            f'<tr class="s-kstat"><td style="padding-left:32px">vmlinux (code+rw+ro+bss)</td>'
            f'<td class="num">{mb(vmlinux_kb)} MB</td>'
            f'<td class="num">{pct(vmlinux_kb, k_stat)}% of KStatic</td>'
            f'<td>{bar(vmlinux_kb, k_stat, "#2471a3")}</td></tr>\n'
        )
    if kernel_page_structs_mb:
        kps_kb = int(kernel_page_structs_mb * 1024)
        kstat_detail_rows += (
            f'<tr class="s-kstat"><td style="padding-left:32px">Kernel Page Structs</td>'
            f'<td class="num">{kernel_page_structs_mb:.2f} MB</td>'
            f'<td class="num">{pct(kps_kb, k_stat)}% of KStatic</td>'
            f'<td>{bar(kps_kb, k_stat, "#2471a3")}</td></tr>\n'
        )
    if hashtables_mb:
        ht_kb = int(hashtables_mb * 1024)
        kstat_detail_rows += (
            f'<tr class="s-kstat"><td style="padding-left:32px">Hash Tables</td>'
            f'<td class="num">{hashtables_mb:.2f} MB</td>'
            f'<td class="num">{pct(ht_kb, k_stat)}% of KStatic</td>'
            f'<td>{bar(ht_kb, k_stat, "#2471a3")}</td></tr>\n'
        )

    fw_fields = [
        ("Slab",          "slab_kb",        "#5b9bd5"),
        ("Vmalloc",       "vmalloc_kb",     "#5b9bd5"),
        ("PageTables",    "pagetables_kb",  "#5b9bd5"),
        ("Modules",       "modules_kb",     "#5b9bd5"),
        ("KernelStack",   "kernelstack_kb", "#5b9bd5"),
        ("Percpu",        "percpu_kb",      "#5b9bd5"),
        ("SecPageTables", "sec_pt_kb",      "#5b9bd5"),
        ("Shmem",         "shmem_kb",       "#70ad47"),
        ("KDA",           "kda_kb",         "#aaa"),
        ("AnonPages",     "anon_pages_kb",  "#70ad47"),
        ("KGSL",          "kgsl_kb",        "#e07b39"),
        ("DMA-BUF",       "dmabuf_kb",      "#e07b39"),
        ("CMA",           "cma_kb",         "#a9c4e8"),
        ("zUsed",         "zram_used_kb",   "#a9c4e8"),
        ("SwapCached",    "swap_cached_kb", "#a9c4e8"),
    ]
    fw_rows = "".join(
        f'<tr><td style="padding-left:24px;color:#555">{label}</td>'
        f'<td class="num">{mb(bd.get(key,0))} MB</td>'
        f'<td class="num">{pct(bd.get(key,0), mt)}%</td>'
        f'<td>{bar(bd.get(key,0), mt, color)}</td></tr>\n'
        for label, key, color in fw_fields if bd.get(key, 0)
    )

    free_fields = [
        ("MemFree",       "mem_free_kb",      "#a9d18e"),
        ("Cached",        "cached_kb",        "#a9c4e8"),
        ("Buffers",       "buffers_kb",       "#a9c4e8"),
        ("DMA-BUF Cache", "dmabuf_cache_kb",  "#a9c4e8"),
        ("Offlined",      "offlined_kb",      "#ccc"),
    ]
    free_rows = "".join(
        f'<tr><td style="padding-left:24px;color:#555">{label}</td>'
        f'<td class="num">{mb(bd.get(key,0))} MB</td>'
        f'<td class="num">{pct(bd.get(key,0), mt)}%</td>'
        f'<td>{bar(bd.get(key,0), mt, color)}</td></tr>\n'
        for label, key, color in free_fields if bd.get(key, 0)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Qualcomm Linux - Memory Map Breakdown</title>
<style>
  body  {{ font-family: Segoe UI, Arial, sans-serif; font-size: 14px;
           background: #f5f5f5; margin: 0; padding: 24px; color: #222; }}
  h1    {{ font-size: 20px; margin-bottom: 4px; }}
  h2    {{ font-size: 15px; margin: 20px 0 6px; border-bottom: 2px solid #ccc;
           padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 860px;
           background: #fff; border-radius: 6px;
           box-shadow: 0 1px 4px rgba(0,0,0,.12); margin-bottom: 24px; }}
  th    {{ background: #3a3a3a; color: #fff; padding: 8px 12px;
           text-align: left; font-weight: 600; }}
  td    {{ padding: 6px 12px; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f9f9f9; }}
  .num  {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .di-label {{ width: 140px; color: #555; font-weight: 600; }}
  .di-val   {{ font-family: monospace; }}
  .s-nhlos  {{ background: #fff4ee; font-weight: 600; }}
  .s-hlos   {{ background: #eef4ff; font-weight: 600; }}
  .s-kstat  {{ background: #f0f5ff; font-weight: 600; }}
  .s-fw     {{ background: #f0fff4; font-weight: 600; }}
  .s-free   {{ background: #f8fff8; font-weight: 600; }}
  .grand-row td {{ background: #1a5276; color: #fff; font-weight: 700; }}
</style>
</head>
<body>
<h1>Qualcomm Linux &mdash; Memory Map Breakdown</h1>

<h2>Device Information</h2>
<table style="max-width:500px">
  <tr><th>Field</th><th>Value</th></tr>
  {dev_rows}
</table>

<h2>Summary</h2>
<table>
  <tr><th>Category</th><th class="num">Size (MB)</th>
      <th class="num">%</th><th style="width:210px">Distribution</th></tr>
  <tr><td><strong>Total Physical RAM</strong></td>
      <td class="num"><strong>{mb(total)}</strong></td>
      <td class="num"><strong>100.0%</strong></td>
      <td>{bar(total, total, "#3a3a3a")}</td></tr>
  <tr class="s-nhlos">
      <td>NHLOS</td>
      <td class="num">{mb(nhlos)}</td>
      <td class="num">{pct(nhlos, total)}%</td>
      <td>{bar(nhlos, total, "#c0392b")}</td></tr>
  <tr class="s-hlos">
      <td>System RAM</td>
      <td class="num">{mb(sysram)}</td>
      <td class="num">{pct(sysram, total)}%</td>
      <td>{bar(sysram, total, "#2980b9")}</td></tr>
  <tr class="s-hlos">
      <td style="padding-left:20px">MemTotal</td>
      <td class="num">{mb(mt)}</td>
      <td class="num">{pct(mt, total)}%</td>
      <td>{bar(mt, total, "#5dade2")}</td></tr>
  <tr class="s-kstat">
      <td style="padding-left:20px">Kernel Static (System RAM &minus; MemTotal)</td>
      <td class="num">{mb(k_stat)}</td>
      <td class="num">{pct(k_stat, sysram)}% of SysRAM</td>
      <td>{bar(k_stat, sysram, "#1a5276")}</td></tr>
  {kstat_detail_rows}
  <tr class="s-fw">
      <td style="padding-left:20px">Used Memory</td>
      <td class="num">{mb(fw)}</td>
      <td class="num">{pct(fw, mt)}% of MemTotal</td>
      <td>{bar(fw, mt, "#70ad47")}</td></tr>
  <tr class="s-free">
      <td style="padding-left:20px">Total Free</td>
      <td class="num">{mb(tfree)}</td>
      <td class="num">{pct(tfree, mt)}% of MemTotal</td>
      <td>{bar(tfree, mt, "#a9d18e")}</td></tr>
  <tr class="grand-row">
      <td>Grand Total (NHLOS + System RAM)</td>
      <td class="num">{mb(nhlos + sysram)}</td>
      <td class="num">100.0%</td><td></td></tr>
</table>

<h2>NHLOS Carve-outs</h2>
<table>
  <tr><th>Carve-out</th><th class="num">Size (MB)</th>
      <th class="num">% of NHLOS</th><th style="width:210px">Distribution</th></tr>
  <tr class="s-nhlos">
      <td><strong>NHLOS Total</strong></td>
      <td class="num"><strong>{mb(nhlos)}</strong></td>
      <td class="num"><strong>100.0%</strong></td>
      <td>{bar(nhlos, nhlos, "#c0392b")}</td></tr>
  {nhlos_rows}
</table>

<h2>Used Memory Breakdown (MemTotal &minus; Total_Free)</h2>
<table>
  <tr><th>Sub-category</th><th class="num">Size (MB)</th>
      <th class="num">% of MemTotal</th><th style="width:210px">Distribution</th></tr>
  <tr class="s-fw">
      <td><strong>Used Memory Total</strong></td>
      <td class="num"><strong>{mb(fw)}</strong></td>
      <td class="num">{pct(fw, mt)}%</td>
      <td>{bar(fw, mt, "#70ad47")}</td></tr>
  {fw_rows}
</table>

<h2>Total Free Breakdown</h2>
<table>
  <tr><th>Sub-category</th><th class="num">Size (MB)</th>
      <th class="num">% of MemTotal</th><th style="width:210px">Distribution</th></tr>
  <tr class="s-free">
      <td><strong>Total Free</strong></td>
      <td class="num"><strong>{mb(tfree)}</strong></td>
      <td class="num">{pct(tfree, mt)}%</td>
      <td>{bar(tfree, mt, "#a9d18e")}</td></tr>
  {free_rows}
</table>

</body>
</html>
"""
    path = report_dir / "memory_report.html"
    path.write_text(html, encoding="utf-8")
    print(f"      HTML saved : {path}")


# =============================================================================
# Excel report  (14 sheets)
# =============================================================================

def save_excel(bd: dict, device_info: dict, report_dir: Path,
               vmlinux_kb: int = 0, vmlinux_detail: dict | None = None,
               extra: dict | None = None) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  [SKIP] openpyxl not installed; skipping Excel report.")
        return

    if extra is None:
        extra = {}

    HDR_FILL  = PatternFill("solid", fgColor="3A3A3A")
    HDR_FONT  = Font(bold=True, color="FFFFFF", size=11)
    BOLD_FONT = Font(bold=True, size=11)
    _thin     = Side(style="thin", color="CCCCCC")
    BORDER    = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

    FILLS = {
        "total": PatternFill("solid", fgColor="DDDDDD"),
        "nhlos": PatternFill("solid", fgColor="FFE8E0"),
        "hlos":  PatternFill("solid", fgColor="E0EEFF"),
        "kstat": PatternFill("solid", fgColor="F0F5FF"),
        "used":  PatternFill("solid", fgColor="F0FFF4"),
        "free":  PatternFill("solid", fgColor="F8FFF8"),
        "grand": PatternFill("solid", fgColor="1A5276"),
        "unacc": PatternFill("solid", fgColor="F5F5F5"),
        "sub":   PatternFill("solid", fgColor="FAFAFA"),
    }

    def _fmb(kb: int) -> float:
        return round(kb / 1024, 2)

    def _fpct(part: int, ref: int) -> float:
        return round(100.0 * part / ref, 1) if ref else 0.0

    def _set_widths(ws, widths: list) -> None:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def _hdr_row(ws, headers: list) -> None:
        ws.append(headers)
        r = ws.max_row
        for col in range(1, len(headers) + 1):
            c = ws.cell(r, col)
            c.font = HDR_FONT
            c.fill = HDR_FILL
            c.alignment = Alignment(horizontal="center")
            c.border = BORDER

    def _data_row(ws, values: list, ncols: int, fill=None,
                  bold: bool = False, grand: bool = False,
                  indent: int = 0) -> None:
        ws.append(values)
        r = ws.max_row
        for col in range(1, ncols + 1):
            c = ws.cell(r, col)
            c.border = BORDER
            if grand:
                c.fill = FILLS["grand"]
                c.font = Font(bold=True, color="FFFFFF", size=11)
            else:
                if fill:
                    c.fill = fill
                if bold:
                    c.font = BOLD_FONT
            if col > 1:
                c.alignment = Alignment(horizontal="right")
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
        if indent:
            ws.cell(r, 1).alignment = Alignment(indent=indent)

    total  = bd["total_physical_kb"]
    sysram = bd["system_ram_kb"]
    nhlos  = bd["nhlos_kb"]
    mt     = bd["mem_total_kb"]
    k_stat = bd["kernel_static_kb"]

    wb = Workbook()

    # ----------------------------------------------------------------
    # Sheet 1 - Summary
    # ----------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Summary"
    _set_widths(ws1, [44, 14, 12, 14])

    ws1.append(["Device Information"])
    ws1.cell(ws1.max_row, 1).font = Font(bold=True, size=13)
    for k, v in device_info.items():
        ws1.append([k, str(v)])
        ws1.cell(ws1.max_row, 1).font = Font(bold=True, color="555555")
    ws1.append([])

    _hdr_row(ws1, ["Category", "Size (MB)", "% of Total", "% of Ref"])

    summary_rows = [
        ("Total Physical RAM",                   total,    total,  total,  "total", True),
        ("NHLOS (Non-High Level OS)",             nhlos,    total,  nhlos,  "nhlos", True),
        ("System RAM",                            sysram,   total,  sysram, "hlos",  True),
        ("  MemTotal",                            mt,       total,  mt,     "hlos",  False),
        ("  Kernel Static (SysRAM - MemTotal)",   k_stat,   sysram, sysram, "kstat", False),
        ("  Used Memory (MemTotal - Total_Free)", bd["linux_fw_kb"],  mt, mt, "used", False),
        ("  Total Free",                          bd["total_free_kb"], mt, mt, "free", False),
    ]
    for label, kb, ref_t, ref_p, fill_key, bold in summary_rows:
        _data_row(ws1, [label, _fmb(kb), _fpct(kb, ref_t), _fpct(kb, ref_p)],
                  ncols=4, fill=FILLS[fill_key], bold=bold,
                  indent=2 if label.startswith("  ") else 0)

    _data_row(ws1, ["Grand Total (NHLOS + System RAM)", _fmb(nhlos + sysram), 100.0, ""],
              ncols=4, grand=True)

    # ----------------------------------------------------------------
    # Sheet 2 - NHLOS (carve-outs + CMA used)
    # ----------------------------------------------------------------
    ws2 = wb.create_sheet("NHLOS")
    _set_widths(ws2, [44, 14, 14])
    _hdr_row(ws2, ["Carve-out", "Size (MB)", "% of NHLOS"])
    _data_row(ws2, ["NHLOS Total", _fmb(nhlos), 100.0], ncols=3,
              fill=FILLS["nhlos"], bold=True)
    for reg in bd["nhlos_regions"]:
        _data_row(ws2, [reg["name"].split("@")[0], _fmb(reg["size_kb"]),
                        _fpct(reg["size_kb"], nhlos)], ncols=3, indent=2)
    if bd["unaccounted_kb"]:
        _data_row(ws2, ["Unaccounted", _fmb(bd["unaccounted_kb"]),
                        _fpct(bd["unaccounted_kb"], nhlos)],
                  ncols=3, fill=FILLS["unacc"])

    cma_used = extra.get("cma_used", {})
    if cma_used:
        ws2.append([])
        _hdr_row(ws2, ["CMA Region", "Used (MB)"])
        for region, size_mb in cma_used.items():
            _data_row(ws2, [region, size_mb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 3 - KernelStatic
    # ----------------------------------------------------------------
    ws3 = wb.create_sheet("KernelStatic")
    _set_widths(ws3, [40, 14])
    kps_mb  = extra.get("kernel_page_structs_mb", 0.0)
    ht_mb   = extra.get("hashtables_mb", 0.0)
    vmx_mb  = round(vmlinux_kb / 1024, 2) if vmlinux_kb else 0.0
    unacc_mb = round(max(0, k_stat / 1024 - vmx_mb - kps_mb - ht_mb), 2)

    _hdr_row(ws3, ["Kernel Static Breakup", "Size (MB)"])
    if vmx_mb:
        _data_row(ws3, ["vmlinux", vmx_mb], ncols=2, indent=2)
    if kps_mb:
        _data_row(ws3, ["Kernel Page Structs", kps_mb], ncols=2, indent=2)
    if ht_mb:
        _data_row(ws3, ["Hash Tables", ht_mb], ncols=2, indent=2)
    if unacc_mb > 0:
        _data_row(ws3, ["Unaccounted (crash kernel, firmware, ...)", unacc_mb],
                  ncols=2, fill=FILLS["unacc"], indent=2)
    _data_row(ws3, ["Kernel Static Total", _fmb(k_stat)], ncols=2,
              fill=FILLS["kstat"], bold=True)

    if vmlinux_detail:
        ws3.append([])
        _hdr_row(ws3, ["vmlinux Breakup", "Size (KB)"])
        for comp, size_kb in vmlinux_detail.items():
            if size_kb:
                _data_row(ws3, [comp, size_kb], ncols=2, indent=2)

    zones = extra.get("zones", {})
    if zones:
        ws3.append([])
        _hdr_row(ws3, ["Zone", "Present (MB)"])
        for zone, size_mb in zones.items():
            _data_row(ws3, [zone, size_mb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 4 - Slab Info
    # ----------------------------------------------------------------
    slab_detail = extra.get("slabinfo_detail", {})
    if slab_detail:
        ws4 = wb.create_sheet("Slab Info")
        _set_widths(ws4, [40, 12, 16, 14])
        _hdr_row(ws4, ["Slab Name", "Size (MB)", "Obj Size (bytes)", "Num Objects"])
        _data_row(ws4, ["Slab Total", _fmb(bd["slab_kb"]), "", ""],
                  ncols=4, fill=FILLS["used"], bold=True)
        for name, (size_mb, obj_bytes, num_objs) in slab_detail.items():
            _data_row(ws4, [name, size_mb, obj_bytes, num_objs], ncols=4, indent=2)

    # ----------------------------------------------------------------
    # Sheet 5 - Vmalloc
    # ----------------------------------------------------------------
    vmallocinfo = extra.get("vmallocinfo", {})
    if vmallocinfo:
        ws5 = wb.create_sheet("Vmalloc")
        _set_widths(ws5, [44, 14])
        _hdr_row(ws5, ["Function", "Size (KB)"])
        _data_row(ws5, ["Vmalloc Total", bd["vmalloc_kb"]], ncols=2,
                  fill=FILLS["used"], bold=True)
        for fn, size_kb in vmallocinfo.items():
            _data_row(ws5, [fn, size_kb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 6 - PageTable KStack
    # ----------------------------------------------------------------
    ws6 = wb.create_sheet("PageTable KStack")
    _set_widths(ws6, [40, 14])
    _hdr_row(ws6, ["Category", "Size (KB)"])
    _data_row(ws6, ["PageTables", bd["pagetables_kb"]], ncols=2,
              fill=FILLS["used"], bold=True)
    _data_row(ws6, ["KernelStack", bd["kernelstack_kb"]], ncols=2,
              fill=FILLS["used"], bold=True)

    # ----------------------------------------------------------------
    # Sheet 7 - Modules
    # ----------------------------------------------------------------
    modules_detail = extra.get("modules_detail", {})
    if modules_detail:
        ws7 = wb.create_sheet("Modules")
        _set_widths(ws7, [44, 14])
        _hdr_row(ws7, ["Module", "Size (KB)"])
        _data_row(ws7, ["Modules Total", bd["modules_kb"]], ncols=2,
                  fill=FILLS["used"], bold=True)
        for name, size_kb in modules_detail.items():
            _data_row(ws7, [name, size_kb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 8 - User space apps
    # ----------------------------------------------------------------
    procrank = extra.get("procrank", {})
    if procrank:
        ws8 = wb.create_sheet("User space apps")
        _set_widths(ws8, [50, 14, 14, 14])
        _hdr_row(ws8, ["Process", "PSS (KB)", "PSwap (KB)", "Total (KB)"])
        for proc_name, (pss_kb, pswap_kb) in procrank.items():
            _data_row(ws8, [proc_name, pss_kb, pswap_kb, pss_kb + pswap_kb],
                      ncols=4, indent=2)

    # ----------------------------------------------------------------
    # Sheet 9 - KGSL
    # ----------------------------------------------------------------
    kgsl_procs = extra.get("kgsl_procs", {})
    ws9 = wb.create_sheet("KGSL")
    _set_widths(ws9, [20, 14])
    _hdr_row(ws9, ["PID / Process", "Size (MB)"])
    _data_row(ws9, ["KGSL Total", _fmb(bd["kgsl_kb"])], ncols=2,
              fill=FILLS["used"], bold=True)
    if kgsl_procs:
        for pid, size_mb in kgsl_procs.items():
            _data_row(ws9, [pid, size_mb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 10 - DMA-BUF
    # ----------------------------------------------------------------
    dmabuf_detail = extra.get("dmabuf_detail", {})
    ws10 = wb.create_sheet("DMA-BUF")
    _set_widths(ws10, [40, 14])
    _hdr_row(ws10, ["Allocator (exp_name)", "Size (MB)"])
    _data_row(ws10, ["DMA-BUF Total", _fmb(bd["dmabuf_kb"])], ncols=2,
              fill=FILLS["used"], bold=True)
    if dmabuf_detail:
        for alloc, size_mb in dmabuf_detail.items():
            _data_row(ws10, [alloc, size_mb], ncols=2, indent=2)

    # ----------------------------------------------------------------
    # Sheet 11 - MemoryLayout
    # region_type: 'sysram' | 'kstatic' | 'nhlos' | 'missing'
    # ----------------------------------------------------------------
    memory_layout = extra.get("memory_layout", [])
    if memory_layout:
        ws11 = wb.create_sheet("MemoryLayout")
        _set_widths(ws11, [32, 14, 14, 10, 10, 12, 12])
        _hdr_row(ws11, ["Name", "Start Address", "End Address",
                         "Size (MB)", "Type", "SysRAM (MB)", "NHLOS (MB)"])

        TYPE_FILL = {
            "sysram":  PatternFill("solid", fgColor="E0EEFF"),   # blue  = accessible SysRAM
            "kstatic": PatternFill("solid", fgColor="D0D8F0"),   # dark blue = reserved in SysRAM
            "nhlos":   PatternFill("solid", fgColor="FFE8E0"),   # orange = NHLOS
            "missing": PatternFill("solid", fgColor="F5F5F5"),   # gray  = gap
        }
        TYPE_LABEL = {
            "sysram":  "System RAM",
            "kstatic": "KStatic",
            "nhlos":   "NHLOS",
            "missing": "Missing",
        }

        total_sysram = 0.0
        total_nhlos  = 0.0
        for name, start, end, size_mb, region_type in memory_layout:
            # SysRAM column = sysram + kstatic (both within System RAM address space)
            sysram_col = size_mb if region_type in ("sysram", "kstatic") else 0.0
            nhlos_col  = size_mb if region_type in ("nhlos", "missing")  else 0.0
            total_sysram += sysram_col
            total_nhlos  += nhlos_col
            _data_row(ws11,
                      [name, hex(start), hex(end), size_mb,
                       TYPE_LABEL.get(region_type, region_type),
                       sysram_col, nhlos_col],
                      ncols=7,
                      fill=TYPE_FILL.get(region_type, FILLS["unacc"]))
        _data_row(ws11, ["Total", "", "", round(total_sysram + total_nhlos, 2),
                          "", round(total_sysram, 2), round(total_nhlos, 2)],
                  ncols=7, grand=True)

    # ----------------------------------------------------------------
    # Sheet 12 - Kernel Configs
    # ----------------------------------------------------------------
    kconfig = extra.get("kconfig", {})
    if kconfig:
        ws12 = wb.create_sheet("Kernel Configs")
        _set_widths(ws12, [60, 20])
        _hdr_row(ws12, ["Config Key", "Value"])
        for key, val in sorted(kconfig.items()):
            ws12.append([key, val])
            r = ws12.max_row
            for col in range(1, 3):
                ws12.cell(r, col).border = BORDER

    # ----------------------------------------------------------------
    # Sheet 13 - Used Memory
    # ----------------------------------------------------------------
    ws13 = wb.create_sheet("Used Memory")
    _set_widths(ws13, [44, 14, 16])
    _hdr_row(ws13, ["Sub-category", "Size (MB)", "% of MemTotal"])
    _data_row(ws13, ["Used Memory Total", _fmb(bd["linux_fw_kb"]),
                     _fpct(bd["linux_fw_kb"], mt)], ncols=3,
              fill=FILLS["used"], bold=True)
    for label, key in [
        ("Slab",          "slab_kb"),
        ("Vmalloc",       "vmalloc_kb"),
        ("PageTables",    "pagetables_kb"),
        ("Modules",       "modules_kb"),
        ("KernelStack",   "kernelstack_kb"),
        ("Percpu",        "percpu_kb"),
        ("SecPageTables", "sec_pt_kb"),
        ("Shmem",         "shmem_kb"),
        ("KDA",           "kda_kb"),
        ("AnonPages",     "anon_pages_kb"),
        ("KGSL",          "kgsl_kb"),
        ("DMA-BUF",       "dmabuf_kb"),
        ("CMA",           "cma_kb"),
        ("zUsed",         "zram_used_kb"),
        ("SwapCached",    "swap_cached_kb"),
    ]:
        v = bd.get(key, 0)
        if v:
            _data_row(ws13, [label, _fmb(v), _fpct(v, mt)], ncols=3, indent=2)

    # ----------------------------------------------------------------
    # Sheet 14 - Free Memory
    # ----------------------------------------------------------------
    ws14 = wb.create_sheet("Free Memory")
    _set_widths(ws14, [44, 14, 16])
    _hdr_row(ws14, ["Sub-category", "Size (MB)", "% of MemTotal"])
    _data_row(ws14, ["Total Free", _fmb(bd["total_free_kb"]),
                     _fpct(bd["total_free_kb"], mt)], ncols=3,
              fill=FILLS["free"], bold=True)
    for label, key in [
        ("MemFree",       "mem_free_kb"),
        ("Cached",        "cached_kb"),
        ("Buffers",       "buffers_kb"),
        ("DMA-BUF Cache", "dmabuf_cache_kb"),
        ("Offlined",      "offlined_kb"),
    ]:
        v = bd.get(key, 0)
        if v:
            _data_row(ws14, [label, _fmb(v), _fpct(v, mt)], ncols=3, indent=2)

    path = report_dir / "memory_report.xlsx"
    try:
        wb.save(str(path))
        print(f"      XLSX saved : {path}")
    except PermissionError:
        alt = report_dir / "memory_report_new.xlsx"
        wb.save(str(alt))
        print(f"      XLSX saved : {alt}  (memory_report.xlsx is open -- saved as _new)")


# =============================================================================
# Compare mode helpers
# =============================================================================

_COMPARE_FIELDS: list[tuple[str, str]] = [
    ("Total Physical RAM",    "total_physical_kb"),
    ("  NHLOS",               "nhlos_kb"),
    ("    Named NHLOS",       "named_nhlos_kb"),
    ("    Unaccounted NHLOS", "unaccounted_kb"),
    ("  System RAM",          "system_ram_kb"),
    ("    MemTotal",          "mem_total_kb"),
    ("    Kernel Static",     "kernel_static_kb"),
    ("    Used Memory",       "linux_fw_kb"),
    ("      Slab",            "slab_kb"),
    ("      Vmalloc",         "vmalloc_kb"),
    ("      PageTables",      "pagetables_kb"),
    ("      Modules",         "modules_kb"),
    ("      KernelStack",     "kernelstack_kb"),
    ("      Percpu",          "percpu_kb"),
    ("      SecPageTables",   "sec_pt_kb"),
    ("      Shmem",           "shmem_kb"),
    ("      KDA",             "kda_kb"),
    ("      AnonPages",       "anon_pages_kb"),
    ("      KGSL",            "kgsl_kb"),
    ("      DMA-BUF",         "dmabuf_kb"),
    ("      CMA",             "cma_kb"),
    ("      zUsed",           "zram_used_kb"),
    ("      SwapCached",      "swap_cached_kb"),
    ("    Total Free",        "total_free_kb"),
    ("      MemFree",         "mem_free_kb"),
    ("      Cached",          "cached_kb"),
    ("      Buffers",         "buffers_kb"),
    ("      DMA-BUF Cache",   "dmabuf_cache_kb"),
    ("      Offlined",        "offlined_kb"),
]


def load_dump(dump_dir: Path) -> tuple[dict, dict]:
    """Parse an existing dump directory and return (breakdown, device_info)."""
    device_info: dict[str, str] = {"Dump": str(dump_dir)}

    meminfo_path = dump_dir / "meminfo.txt"
    if not meminfo_path.exists():
        sys.exit(f"[ERROR] {meminfo_path} not found.")
    meminfo = parse_meminfo(meminfo_path)

    iomem_info = {"system_ram_kb": 0, "highest_end": 0,
                  "lowest_start": 0, "iomem_obfuscated": False}
    if (dump_dir / "iomem.txt").exists():
        regions = parse_iomem(dump_dir / "iomem.txt")
        iomem_info = extract_iomem_info(regions)

    dt_memory_kb = dt_lowest_base = 0
    if (dump_dir / "dt_memory_reg.bin").exists():
        dt_memory_kb, dt_lowest_base = parse_dt_memory(dump_dir / "dt_memory_reg.bin")

    zoneinfo_present_kb = 0
    if (dump_dir / "zoneinfo.txt").exists():
        zoneinfo_present_kb = parse_zoneinfo_present(dump_dir / "zoneinfo.txt")

    iomem_obfuscated = iomem_info.get("iomem_obfuscated", False)
    if not iomem_obfuscated and iomem_info["system_ram_kb"]:
        system_ram_kb = iomem_info["system_ram_kb"]
    elif zoneinfo_present_kb:
        system_ram_kb = zoneinfo_present_kb
    elif dt_memory_kb:
        system_ram_kb = dt_memory_kb
    else:
        system_ram_kb = 0

    reserved_regions: list[dict] = []
    res_dir = dump_dir / "reserved-memory"
    if res_dir.exists():
        reserved_regions = parse_dt_reserved_memory(res_dir)

    highest_end  = iomem_info["highest_end"]
    candidates   = [x for x in [dt_lowest_base, iomem_info["lowest_start"]] if x > 0]
    candidates  += [r["base"] for r in reserved_regions if r.get("base", 0) > 0]
    lowest_start = min(candidates) if candidates else 0

    GRANULE_MB = 1024
    total_phys_kb = 0
    if highest_end and lowest_start and not iomem_obfuscated:
        raw_mb     = (highest_end + 1 - lowest_start) // (1024 * 1024)
        sys_ram_mb = system_ram_kb // 1024
        if system_ram_kb and (raw_mb - sys_ram_mb) > 2 * 1024:
            total_phys_mb = ((sys_ram_mb // GRANULE_MB) + 1) * GRANULE_MB
        else:
            total_phys_mb = (((raw_mb - 1) // GRANULE_MB) + 1) * GRANULE_MB
        total_phys_kb = total_phys_mb * 1024
    elif system_ram_kb:
        sys_ram_mb    = system_ram_kb // 1024
        total_phys_mb = ((sys_ram_mb // GRANULE_MB) + 1) * GRANULE_MB
        total_phys_kb = total_phys_mb * 1024

    slab_kb          = parse_slabinfo(dump_dir / "slabinfo.txt")           if (dump_dir / "slabinfo.txt").exists()          else 0
    dmabuf_cache_kb  = parse_vmstat_dmabuf_cache(dump_dir / "vmstat.txt")  if (dump_dir / "vmstat.txt").exists()            else 0
    modules_kb       = parse_modules(dump_dir / "modules.txt")             if (dump_dir / "modules.txt").exists()           else 0
    dmabuf_kb        = parse_dmabuf(dump_dir / "dmabuf_bufinfo.txt")       if (dump_dir / "dmabuf_bufinfo.txt").exists()    else 0
    kgsl_kb          = parse_kgsl(dump_dir / "kgsl_alloc.txt")             if (dump_dir / "kgsl_alloc.txt").exists()        else 0
    zram_orig_kb = zram_used_kb = 0
    if (dump_dir / "zram_stat.txt").exists():
        zram_orig_kb, zram_used_kb = parse_zram(dump_dir / "zram_stat.txt")
    offlined_kb      = parse_offlined(dump_dir / "memory_state.txt")       if (dump_dir / "memory_state.txt").exists()      else 0

    breakdown = compute_breakdown(
        meminfo, system_ram_kb, total_phys_kb, reserved_regions,
        slab_kb, modules_kb, dmabuf_kb, kgsl_kb,
        dmabuf_cache_kb, offlined_kb, zram_orig_kb, zram_used_kb,
    )
    return breakdown, device_info


def save_compare_txt(bd1: dict, bd2: dict, label1: str, label2: str,
                     report_dir: Path) -> None:
    SEP  = "=" * 92
    SEP2 = "-" * 92
    lines: list[str] = [
        SEP,
        "  MEMORY MAP COMPARISON",
        SEP,
        f"  Dump 1 : {label1}",
        f"  Dump 2 : {label2}",
        SEP,
        f"  {'Category':<36} {'Dump1 (MB)':>12} {'Dump2 (MB)':>12} {'Delta (MB)':>12} {'Delta%':>9}",
        SEP2,
    ]

    for label, key in _COMPARE_FIELDS:
        v1 = bd1.get(key, 0)
        v2 = bd2.get(key, 0)
        if v1 == 0 and v2 == 0:
            continue
        delta = v2 - v1
        sign  = "+" if delta >= 0 else ""
        if v1:
            dpct = f"{sign}{100.0 * delta / v1:>8.1f}%"
        else:
            dpct = "     N/A" if v2 == 0 else "    +inf%"
        lines.append(
            f"  {label:<36} {v1/1024:>12.2f} {v2/1024:>12.2f} "
            f"{sign}{delta/1024:>11.2f} {dpct}"
        )

    lines += [SEP, ""]
    path = report_dir / "memory_compare.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[COMPARE] TXT  saved : {path}")


def save_compare_html(bd1: dict, bd2: dict, label1: str, label2: str,
                      report_dir: Path) -> None:
    def fmb(kb: int) -> str:
        return f"{kb / 1024:.2f}"

    def fdelta(v1: int, v2: int) -> str:
        d    = v2 - v1
        sign = "+" if d >= 0 else ""
        return f"{sign}{d / 1024:.2f}"

    def fdpct(v1: int, v2: int) -> str:
        if v1 == 0:
            return "N/A" if v2 == 0 else "+inf"
        d    = 100.0 * (v2 - v1) / v1
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.1f}%"

    def dcolor(v1: int, v2: int) -> str:
        if v2 > v1:
            return "#c0392b"
        if v2 < v1:
            return "#27ae60"
        return "#555555"

    rows_html = ""
    for label, key in _COMPARE_FIELDS:
        v1 = bd1.get(key, 0)
        v2 = bd2.get(key, 0)
        if v1 == 0 and v2 == 0:
            continue
        indent = len(label) - len(label.lstrip())
        pad    = indent * 6
        color  = dcolor(v1, v2)
        rows_html += (
            f'<tr>'
            f'<td style="padding-left:{12+pad}px">{label.strip()}</td>'
            f'<td class="num">{fmb(v1)}</td>'
            f'<td class="num">{fmb(v2)}</td>'
            f'<td class="num" style="color:{color};font-weight:600">{fdelta(v1,v2)}</td>'
            f'<td class="num" style="color:{color};font-weight:600">{fdpct(v1,v2)}</td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Memory Map Comparison</title>
<style>
  body  {{ font-family: Segoe UI, Arial, sans-serif; font-size: 14px;
           background: #f5f5f5; margin: 0; padding: 24px; color: #222; }}
  h1    {{ font-size: 20px; margin-bottom: 8px; }}
  .meta {{ font-size: 13px; color: #555; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 960px;
           background: #fff; border-radius: 6px;
           box-shadow: 0 1px 4px rgba(0,0,0,.12); margin-bottom: 24px; }}
  th    {{ background: #3a3a3a; color: #fff; padding: 8px 12px;
           text-align: left; font-weight: 600; }}
  td    {{ padding: 6px 12px; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f9f9f9; }}
  .num  {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .legend {{ font-size: 12px; color: #555; margin-top: -16px; margin-bottom: 20px; }}
</style>
</head>
<body>
<h1>Memory Map Comparison</h1>
<div class="meta">
  <strong>Dump 1:</strong> {label1} &nbsp;&nbsp;&nbsp;
  <strong>Dump 2:</strong> {label2}
</div>
<table>
  <tr>
    <th>Category</th>
    <th class="num">Dump 1 (MB)</th>
    <th class="num">Dump 2 (MB)</th>
    <th class="num">Delta (MB)</th>
    <th class="num">Delta %</th>
  </tr>
  {rows_html}
</table>
<div class="legend">
  <span style="color:#c0392b">&#9650; Red</span> = Dump 2 uses more memory &nbsp;&nbsp;
  <span style="color:#27ae60">&#9660; Green</span> = Dump 2 uses less memory
</div>
</body>
</html>
"""
    path = report_dir / "memory_compare.html"
    path.write_text(html, encoding="utf-8")
    print(f"[COMPARE] HTML saved : {path}")


def save_compare_excel(bd1: dict, bd2: dict, label1: str, label2: str,
                       report_dir: Path) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  [SKIP] openpyxl not installed; skipping Excel comparison.")
        return

    _thin  = Side(style="thin", color="CCCCCC")
    BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
    HDR_FILL = PatternFill("solid", fgColor="3A3A3A")
    HDR_FONT = Font(bold=True, color="FFFFFF", size=11)

    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"

    for i, w in enumerate([38, 16, 16, 14, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.append(["Memory Map Comparison"])
    ws.cell(1, 1).font = Font(bold=True, size=14)
    ws.append([f"Dump 1: {label1}", "", f"Dump 2: {label2}"])
    ws.cell(2, 1).font = Font(bold=True, color="555555")
    ws.cell(2, 3).font = Font(bold=True, color="555555")
    ws.append([])

    headers = ["Category", "Dump 1 (MB)", "Dump 2 (MB)", "Delta (MB)", "Delta %"]
    ws.append(headers)
    r = ws.max_row
    for col in range(1, 6):
        c = ws.cell(r, col)
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER

    ws.append(["", label1, label2, "", ""])
    r = ws.max_row
    for col in range(1, 6):
        c = ws.cell(r, col)
        c.font = Font(italic=True, color="555555", size=10)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER

    def fmb(kb: int) -> float:
        return round(kb / 1024, 2)

    for label, key in _COMPARE_FIELDS:
        v1 = bd1.get(key, 0)
        v2 = bd2.get(key, 0)
        if v1 == 0 and v2 == 0:
            continue
        delta    = v2 - v1
        delta_mb = fmb(delta)
        dpct     = round(100.0 * delta / v1, 1) if v1 else None
        indent   = len(label) - len(label.lstrip())

        ws.append([label.strip(), fmb(v1), fmb(v2), delta_mb, dpct])
        r = ws.max_row

        for col in range(1, 6):
            c = ws.cell(r, col)
            c.border = BORDER
            if col > 1:
                c.alignment = Alignment(horizontal="right")
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
        if indent:
            ws.cell(r, 1).alignment = Alignment(indent=indent // 2)

        dclr = "C0392B" if delta > 0 else ("27AE60" if delta < 0 else "555555")
        for col in (4, 5):
            ws.cell(r, col).font = Font(color=dclr, bold=True)

    path = report_dir / "memory_compare.xlsx"
    wb.save(str(path))
    print(f"[COMPARE] XLSX saved : {path}")


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Qualcomm Linux Memory Map Analyzer v0.0.1\n\n"
            "Normal mode  : pull from ADB device and generate reports.\n"
            "Offline mode : --no-pull  analyse existing dump directory.\n"
            "Compare mode : --compare DIR1 DIR2  diff two dump directories.\n\n"
            "Reports are written to the project root (or --report-dir).\n"
            "Raw dump files go into --output (default: mem_dump/)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial",     "-s", metavar="SERIAL")
    parser.add_argument("--output",     "-o", metavar="DIR",  default="mem_dump")
    parser.add_argument("--report-dir",       metavar="DIR",  default=".")
    parser.add_argument("--no-pull",          action="store_true")
    parser.add_argument("--compare",          nargs=2,
                        metavar=("DIR1", "DIR2"),
                        help="Compare two existing dump directories (no ADB pull).")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Compare mode
    # ------------------------------------------------------------------
    if args.compare:
        dir1, dir2 = Path(args.compare[0]), Path(args.compare[1])
        print(f"[COMPARE] Loading dump 1 : {dir1}")
        bd1, info1 = load_dump(dir1)
        print(f"[COMPARE] Loading dump 2 : {dir2}")
        bd2, info2 = load_dump(dir2)
        label1, label2 = str(dir1), str(dir2)
        save_compare_txt(bd1, bd2, label1, label2, report_dir)
        save_compare_html(bd1, bd2, label1, label2, report_dir)
        save_compare_excel(bd1, bd2, label1, label2, report_dir)
        print("[COMPARE] Done.")
        return

    # ------------------------------------------------------------------
    # Normal / offline mode
    # ------------------------------------------------------------------
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- Step 1: pull ----------------------------------------------------------
    device_info: dict[str, str] = {}
    if not args.no_pull:
        serial = check_device(args.serial)
        print(f"[INFO] Device : {serial}")
        print("[INFO] Collecting device information ...")
        device_info = get_device_info(serial, out_dir)
        pull_all(out_dir, serial)
    else:
        print(f"[INFO] --no-pull: using existing files in '{out_dir}'")
        device_info["Captured"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device_info["Note"] = "Analysed from existing dump (no ADB)"

    # -- Step 2: parse ---------------------------------------------------------
    print("\n[2/4] Parsing collected data ...")

    meminfo = parse_meminfo(out_dir / "meminfo.txt")
    if not (out_dir / "meminfo.txt").exists():
        sys.exit("[ERROR] meminfo.txt not found.")
    print(f"  MemTotal       : {meminfo.get('MemTotal', 0) / 1024:.1f} MB")

    iomem_regions: list[dict] = []
    iomem_info = {"system_ram_kb": 0, "highest_end": 0, "lowest_start": 0,
                  "iomem_obfuscated": False}
    if (out_dir / "iomem.txt").exists():
        iomem_regions = parse_iomem(out_dir / "iomem.txt")
        iomem_info    = extract_iomem_info(iomem_regions)
        print(f"  iomem          : {len(iomem_regions)} regions parsed")

    dt_memory_kb = dt_lowest_base = 0
    if (out_dir / "dt_memory_reg.bin").exists():
        dt_memory_kb, dt_lowest_base = parse_dt_memory(out_dir / "dt_memory_reg.bin")

    zoneinfo_present_kb = 0
    if (out_dir / "zoneinfo.txt").exists():
        zoneinfo_present_kb = parse_zoneinfo_present(out_dir / "zoneinfo.txt")

    iomem_obfuscated = iomem_info.get("iomem_obfuscated", False)
    if not iomem_obfuscated and iomem_info["system_ram_kb"]:
        system_ram_kb  = iomem_info["system_ram_kb"]
        system_ram_src = "iomem"
    elif zoneinfo_present_kb:
        system_ram_kb  = zoneinfo_present_kb
        system_ram_src = "zoneinfo present"
    elif dt_memory_kb:
        system_ram_kb  = dt_memory_kb
        system_ram_src = "device tree"
    else:
        system_ram_kb  = 0
        system_ram_src = "unknown"
    if system_ram_kb:
        print(f"  System RAM     : {system_ram_kb / 1024:.1f} MB  ({system_ram_src})")

    reserved_regions: list[dict] = []
    res_dir = out_dir / "reserved-memory"
    if res_dir.exists():
        reserved_regions = parse_dt_reserved_memory(res_dir)
        named_mb = sum(r["size_kb"] for r in reserved_regions) / 1024
        print(f"  Named NHLOS    : {named_mb:.1f} MB  ({len(reserved_regions)} nodes)")

    if iomem_obfuscated:
        print("  [WARN] iomem addresses are all zero (kernel address obfuscation active)")

    highest_end  = iomem_info["highest_end"]
    candidates   = [x for x in [dt_lowest_base, iomem_info["lowest_start"]] if x > 0]
    candidates  += [r["base"] for r in reserved_regions if r.get("base", 0) > 0]
    lowest_start = min(candidates) if candidates else 0

    GRANULE_MB = 1024
    total_phys_kb = 0
    if highest_end and lowest_start and not iomem_obfuscated:
        raw_mb     = (highest_end + 1 - lowest_start) // (1024 * 1024)
        sys_ram_mb = system_ram_kb // 1024
        if system_ram_kb and (raw_mb - sys_ram_mb) > 2 * 1024:
            total_phys_mb = ((sys_ram_mb // GRANULE_MB) + 1) * GRANULE_MB
            total_phys_kb = total_phys_mb * 1024
            print(f"  Total Physical : {total_phys_mb} MB  (system RAM rounded, iomem range too large)")
        else:
            total_phys_mb = (((raw_mb - 1) // GRANULE_MB) + 1) * GRANULE_MB
            total_phys_kb = total_phys_mb * 1024
            print(f"  Total Physical : {total_phys_mb} MB  (iomem, rounded to {GRANULE_MB}MB)")
    elif system_ram_kb:
        sys_ram_mb    = system_ram_kb // 1024
        total_phys_mb = ((sys_ram_mb // GRANULE_MB) + 1) * GRANULE_MB
        total_phys_kb = total_phys_mb * 1024
        src = "zoneinfo present" if iomem_obfuscated else "system RAM"
        print(f"  Total Physical : {total_phys_mb} MB  ({src} rounded to {GRANULE_MB}MB)")

    # -- Optional data sources -------------------------------------------------
    slab_kb = 0
    if (out_dir / "slabinfo.txt").exists():
        slab_kb = parse_slabinfo(out_dir / "slabinfo.txt")

    dmabuf_cache_kb = 0
    if (out_dir / "vmstat.txt").exists():
        dmabuf_cache_kb = parse_vmstat_dmabuf_cache(out_dir / "vmstat.txt")
        if dmabuf_cache_kb:
            print(f"  DMA-BUF Cache  : {dmabuf_cache_kb / 1024:.2f} MB  (vmstat)")

    modules_kb = 0
    if (out_dir / "modules.txt").exists():
        modules_kb = parse_modules(out_dir / "modules.txt")
        if modules_kb:
            print(f"  Modules        : {modules_kb / 1024:.2f} MB  (/proc/modules)")

    dmabuf_kb = 0
    if (out_dir / "dmabuf_bufinfo.txt").exists():
        dmabuf_kb = parse_dmabuf(out_dir / "dmabuf_bufinfo.txt")
        if dmabuf_kb:
            print(f"  DMA-BUF        : {dmabuf_kb / 1024:.2f} MB  (dma_buf/bufinfo)")

    kgsl_kb = 0
    if (out_dir / "kgsl_alloc.txt").exists():
        kgsl_kb = parse_kgsl(out_dir / "kgsl_alloc.txt")
        if kgsl_kb:
            print(f"  KGSL           : {kgsl_kb / 1024:.2f} MB  (kgsl/page_alloc)")

    zram_orig_kb = zram_used_kb = 0
    if (out_dir / "zram_stat.txt").exists():
        zram_orig_kb, zram_used_kb = parse_zram(out_dir / "zram_stat.txt")
        if zram_used_kb:
            print(f"  ZRAM           : {zram_used_kb / 1024:.2f} MB used / "
                  f"{zram_orig_kb / 1024:.2f} MB orig")

    offlined_kb = 0
    if (out_dir / "memory_state.txt").exists():
        offlined_kb = parse_offlined(out_dir / "memory_state.txt")
        if offlined_kb:
            print(f"  Offlined       : {offlined_kb / 1024:.2f} MB")

    # -- dmesg vmlinux breakdown -----------------------------------------------
    dmesg_info: dict[str, int] = {}
    vmlinux_kb = 0
    vmlinux_detail: dict[str, int] = {}
    dmesg_src = out_dir / "dmesg_memory.txt"
    if not dmesg_src.exists():
        dmesg_src = out_dir / "dmesg.txt"
    if dmesg_src.exists():
        dmesg_info = parse_dmesg_memory(dmesg_src)
        if dmesg_info:
            vmlinux_kb = (dmesg_info.get("k_code_kb", 0)
                          + dmesg_info.get("k_rwdata_kb", 0)
                          + dmesg_info.get("k_rodata_kb", 0)
                          + dmesg_info.get("k_bss_kb", 0))
            vmlinux_detail = {
                "Kernel code": dmesg_info.get("k_code_kb", 0),
                "rwdata":      dmesg_info.get("k_rwdata_kb", 0),
                "rodata":      dmesg_info.get("k_rodata_kb", 0),
                "bss":         dmesg_info.get("k_bss_kb", 0),
            }
            print(f"  vmlinux        : {vmlinux_kb / 1024:.2f} MB  [dmesg]")

    # -- Full dmesg for kernelPageStructs + hashtables -------------------------
    kernel_page_structs_mb = 0.0
    hashtables_mb          = 0.0
    if (out_dir / "dmesg.txt").exists():
        kernel_page_structs_mb, hashtables_mb = parse_dmesg_full(out_dir / "dmesg.txt")
        if kernel_page_structs_mb:
            print(f"  KernelPageStructs: {kernel_page_structs_mb:.2f} MB  [dmesg]")
        if hashtables_mb:
            print(f"  HashTables     : {hashtables_mb:.2f} MB  [dmesg]")

    # -- New detail parsers ----------------------------------------------------
    extra: dict = {}

    if (out_dir / "slabinfo.txt").exists():
        extra["slabinfo_detail"] = parse_slabinfo_detail(out_dir / "slabinfo.txt")

    if (out_dir / "vmallocinfo.txt").exists():
        extra["vmallocinfo"] = parse_vmallocinfo(out_dir / "vmallocinfo.txt")
        total_vmalloc_kb = sum(extra["vmallocinfo"].values())
        if total_vmalloc_kb:
            print(f"  Vmalloc detail : {total_vmalloc_kb / 1024:.2f} MB  (/proc/vmallocinfo)")

    if (out_dir / "modules.txt").exists():
        extra["modules_detail"] = parse_modules_detail(out_dir / "modules.txt")

    if (out_dir / "dmabuf_bufinfo.txt").exists():
        extra["dmabuf_detail"] = parse_dmabuf_detail(out_dir / "dmabuf_bufinfo.txt")

    if (out_dir / "cma_used.txt").exists():
        extra["cma_used"] = parse_cma_used(out_dir / "cma_used.txt")
        if extra["cma_used"]:
            total_cma = sum(extra["cma_used"].values())
            print(f"  CMA used       : {total_cma:.2f} MB  (cma/*/used)")

    kgsl_procs_dir = out_dir / "kgsl_procs"
    if kgsl_procs_dir.exists():
        extra["kgsl_procs"] = parse_kgsl_procs(kgsl_procs_dir)

    if (out_dir / "config.txt").exists():
        extra["kconfig"] = parse_kconfig(out_dir / "config.txt")
        print(f"  Kernel Configs : {len(extra['kconfig'])} entries  (config.txt)")

    if (out_dir / "procrank.txt").exists():
        extra["procrank"] = parse_procrank(out_dir / "procrank.txt")
        if extra["procrank"]:
            print(f"  Procrank       : {len(extra['procrank'])} processes")

    if (out_dir / "zoneinfo.txt").exists():
        extra["zones"] = parse_zoneinfo_detail(out_dir / "zoneinfo.txt")

    extra["kernel_page_structs_mb"] = kernel_page_structs_mb
    extra["hashtables_mb"]          = hashtables_mb

    if iomem_regions and reserved_regions:
        extra["memory_layout"] = build_memory_layout(iomem_regions, reserved_regions)

    # -- Step 3: compute -------------------------------------------------------
    print("\n[3/4] Computing memory breakdown ...")
    breakdown = compute_breakdown(
        meminfo, system_ram_kb, total_phys_kb, reserved_regions,
        slab_kb, modules_kb, dmabuf_kb, kgsl_kb,
        dmabuf_cache_kb, offlined_kb, zram_orig_kb, zram_used_kb,
    )

    # -- Step 4: report --------------------------------------------------------
    print_report(breakdown, device_info, vmlinux_kb, vmlinux_detail)
    print()
    save_report(breakdown, device_info, report_dir, vmlinux_kb, vmlinux_detail)
    save_html(breakdown, device_info, report_dir, vmlinux_kb, vmlinux_detail,
              kernel_page_structs_mb, hashtables_mb)
    save_excel(breakdown, device_info, report_dir, vmlinux_kb, vmlinux_detail, extra)


if __name__ == "__main__":
    main()
