# Benchmark Harness FAQ

**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This FAQ complements [`documentation/BenchmarkPrompts.md`](documentation/BenchmarkPrompts.md), which lists ready-to-use prompts for every benchmark. This document covers recommendations, common pitfalls, performance/resource implications, and troubleshooting guidance, derived from `main.py`, `config/benchmarks.yaml`, and all `src/benchmark/*.py` implementations.

---

## 1. Most Commonly Used Prompts (Recommended Starting Points)

| Use Case | Recommended Prompt |
|---|---|
| Quick smoke-test of CPU | "run coremark over ssh" |
| Quick smoke-test of storage | "run tiobench over ssh" |
| Full device performance sweep | "run all benchmarks over ssh" |
| Regression-check a single subsystem after a build change | "run sysbench over ssh" (broadest single-benchmark coverage: CPU/Memory/Threads/Mutex/FileIO) |
| GPU-only check | "run glmark2 over ssh" |
| Repeatability/statistical confidence check | "run coremark 5 times over ssh" (any benchmark with `-r 5`) |
| Excluding known-slow or currently-irrelevant benchmarks from a full sweep | "run all benchmarks except unixbench and bw_mem over ssh" |

---

## 2. Understanding `-r` (Runs) vs `--iterations`

These are two independent, nested loops that are frequently confused:

- **`-r` / `--runs`** — the **outer loop**, implemented in `main.py`. Controls how many times the **entire benchmark suite** executes. Each suite run produces its own `run_<...>` directory, `results.json`, and HTML report. Default: **1**.
- **`--iterations`** — the **inner loop**, implemented inside each benchmark engine. Controls how many times **each individual sub-test** repeats *within a single suite run*. Default varies per benchmark (see that benchmark's `iterations:` key in `config/benchmarks.yaml` — typically 3).

**Total sub-test executions = `runs × iterations`**

| Scenario | Meaning | Example Command | Total Executions |
|---|---|---|---|
| `-r 1 --iterations 3` (default) | Suite runs once; each sub-test runs 3 times within that run | `python main.py -b coremark --iterations 3` | 3 |
| `-r 3` (iterations omitted, uses default) | Suite runs 3 times; each sub-test runs at its default iteration count (e.g. 3) per run | `python main.py -b coremark -r 3` | 9 (3 runs × 3 default iterations) |
| `-r 2 --iterations 4` | Suite runs 2 times; each sub-test runs 4 times per run | `python main.py -b coremark -r 2 --iterations 4` | 8 |
| `-r 3 --iterations 4` (the "sysbench 3 times, fileio 4 times" example) | Suite runs 3 times; the targeted sub-test runs 4 times per run | `python main.py -b sysbench -t sysbench_fileio_random_mixed_test -r 3 --iterations 4` | 12 |

**Key takeaway:** If a user says "run X *N* times and its *sub-test* *M* times", that maps directly to `-r N --iterations M` — the sub-test's total execution count is `N × M`, not `N` or `M` alone.

---

## 3. Prompts to Avoid / Invalid Combinations

| Invalid / Problematic Prompt | Why It Fails | Correct Alternative |
|---|---|---|
| "run glmark2_default over ssh" → `-b glmark2_default` | `glmark2_default` is a **sub-test**, not a registered benchmark name (`src/benchmark/registry.py` only knows `glmark2`). Raises `ValueError: Benchmark 'glmark2_default' is not supported.` | "run only the default glmark2 test over ssh" → `-b glmark2 -t glmark2_default` |
| "run coremark over ssh and serial" | `--ssh-connection` and `--default-connection` are **mutually exclusive**; `main.py` calls `parser.error()` if both are passed. | Choose one connection type per invocation. |
| "run tiobench with test type cached over ssh" | `cached` is not a valid TIOBench test type. Valid values are only `sequential`, `random`, `mixed` (from `config/benchmarks.yaml` → `tiobench.test_params` keys). Invalid test names are logged as a warning and silently skipped (`main.py` line ~703), falling back to default tests. | "run only the sequential test of tiobench over ssh" |
| "run sysbench_cpu over ssh" (invented benchmark name) | Not a registered benchmark; will raise `ValueError` listing all registered names. | "run sysbench -t sysbench_cpu_prime_single_test over ssh" |
| "run all benchmarks immediately without any gap" | Running with `--bypass-gap` skips the mandatory 5-minute thermal cooldown between suite runs. This is technically valid but **not recommended** unless you explicitly accept thermally-skewed results. | Only use `--bypass-gap` when you understand and accept the risk (e.g., quick functional smoke test, not a performance regression check). |
| "run all benchmarks twice within the last N minutes of a completed run" | `validate_and_enforce_gap()` will reject execution with exit code 2 if a benchmark was run too recently (unless `--bypass-gap` is passed). | Wait for the enforced gap, or explicitly request `--bypass-gap` if acceptable. |
| Requesting a benchmark name with typos/case mismatches (e.g., "CoreMark", "Core_Mark") | `factory.py` lowercases and strips the name before lookup, so casing like `CoreMark` actually works — but hyphens/spaces (`core-mark`, `core mark`) do **not** match `coremark` and will fail. | Use exact registered names: `coremark`, `sysbench`, `tiobench`, `hackbench`, `glmark2`, `coremark_pro`, `osbench`, `ramspeed`, `unixbench`, `bw_mem`, `lat_mem_rd`, `geekbench`. |

---

## 4. Performance & Resource Implications

| Benchmark | Typical Duration (per run, default settings) | Resource Impact | Notes |
|---|---|---|---|
| `coremark` | Seconds to ~1 min per iteration × 3 iterations | Low CPU-only load | Fastest benchmark; good for quick sanity checks. |
| `sysbench` | Several minutes (13 sub-tests × 3 iterations, some fixed 30-60s each) | CPU, Memory, Disk I/O (fileio sub-tests write up to 8G) | The `fileio` sub-tests prepare/cleanup an 8G file set each iteration — ensure `/root/sysbench_io` has sufficient free space. |
| `tiobench` | Several minutes (3 test types × 3 iterations, storage-bound) | Heavy disk I/O; drops page cache before each run | Storage tests can take longer on slower/eMMC-class storage; SSD-backed targets finish faster. |
| `hackbench` | Fast (seconds per iteration × 3) | CPU + scheduler stress; can spike thermals | Integrated with thermal telemetry — regressions may be attributed to DVFS/thermal throttling if CPU >85°C or DDR >75°C is observed. |
| `glmark2` | Minutes (4 flavors × on-screen/off-screen rendering passes) | GPU-bound | Requires Wayland compositor running (`WAYLAND_DISPLAY=/run/wayland-0`); will fail on headless targets without a compositor. |
| `coremark_pro` | Several minutes (9 microbenchmarks × single+multi-core × 3 iterations = 54 sub-runs) | CPU-heavy, longest CPU-only benchmark | Second-longest single benchmark after `unixbench`; plan accordingly for `-r` > 1. |
| `osbench` | Fast (4 microbenchmarks × 3 iterations) | OS/kernel call overhead only | Lightweight; safe to run frequently. |
| `ramspeed` | Several minutes (6 benchmark IDs × single+multi-threaded × 3 iterations) | Memory bandwidth-bound | Multi-threaded pass uses `$(nproc)` — high core-count targets will show larger single vs multi differences. |
| `unixbench` | **15–40 minutes per pass** (single-core `Run -c 1` + multi-core `Run -c $(nproc)`) | CPU + OS, **longest individual benchmark** | Explicitly called out in `run-unixbench/SKILL.md`; always set duration expectations with the user before starting. Requires `/usr/share/unixbench/Run` present on target. |
| `bw_mem` | Can be **long on high-core-count targets** — sweeps 1→`nproc` workers × 6 operations | Memory bandwidth-bound | Runtime scales linearly with `nproc`; explicitly flagged as long-running in its skill file. |
| `lat_mem_rd` | A few minutes per iteration (5 workload sizes × inter-command delay of 5s, × 3 iterations) | Memory latency-bound | Each iteration includes deliberate inter-command delays; not CPU/IO intensive but wall-clock-bound. |
| **All benchmarks (full suite)** | **Several hours** (11 benchmarks × mandatory 5-min inter-benchmark cooldown gaps) | Full-device stress across CPU/Memory/Storage/GPU/OS | Explicitly noted in `run-all-benchmarks/SKILL.md` — always confirm scope and set time expectations before starting a full sweep. |

**General guidance:**
- Prefer targeting individual benchmarks or sub-tests (`-t`) during iterative development to save time.
- Reserve full-suite runs (`run all benchmarks`) for release/regression-gating scenarios where multi-hour runtimes are acceptable.
- `--bypass-gap` trades thermal-stability guarantees for speed — only use it for quick functional checks, not performance-sensitive comparisons.

---

## 5. Benchmark-Specific Tips

- **GLMark2**: Always specify the flavor via `-t` if you only want one; omitting `-t` runs **all 4 flavors sequentially** (default, 1920x1080, offscreen, offscreen+1920x1080), which takes proportionally longer.
- **Sysbench**: Use category-level test selection (`-t sysbench_cpu_prime_single_test sysbench_cpu_prime_multi_test`) rather than trying to pass a bare category name like `cpu` — the harness only matches exact sub-test names from `config/benchmarks.yaml`.
- **TIOBench**: `-t` values are `sequential`, `random`, `mixed` — do not confuse these with Sysbench-style `sysbench_*` test names; they are unrelated naming schemes.
- **Sysbench (dynamic overrides)**: Any unrecognized CLI flag (e.g., `--time=10`, `--threads=4`) is captured by `parse_unknown_args()` in `main.py` and merged into that benchmark's `overrides` dict — useful for on-the-fly parameter tuning without editing `benchmarks.yaml`, but only supported for `sysbench` sub-test commands.
- **UnixBench / bw_mem**: These are the two most time-expensive benchmarks. If time is limited, consider excluding them via `--skip unixbench,bw_mem` in a full-suite run.
- **Hackbench**: Regression results are automatically cross-referenced against thermal telemetry (CPU/DDR temps) — a throughput drop coinciding with a thermal spike will be labeled "DVFS / Thermal Throttling" rather than a code regression in the dashboard.
- **All benchmarks with `--skip`**: `--skip` only removes benchmarks from the **active/default set** — if you also pass `-b` with an explicit list, `--skip` has no effect on names not in that list (per `main.py`'s skip-handling logic).

---

## 6. Connection Type Guidance

- **SSH (`--ssh-connection`)** — default assumption in all prompts in this repo. Connects directly via `SshManager` (hardcoded host `10.92.197.120` in `main.py` — update if your target's IP differs). Skips the serial login/ADB-enablement dance; faster to start.
- **Serial/ADB (default, no flag, or `--default-connection`)** — opens a serial connection (`port`/`baud` from `config/benchmarks.yaml`, default `COM7 @ 115200`), performs login handshake, enables `usb-debugging`, and starts `android-tools-adbd` before falling back to ADB for build-ID detection and file push/pull. Slower to start but works when SSH isn't configured/reachable.
- Never pass both `--ssh-connection` and `--default-connection` — this is a **hard error** (`parser.error`), not a warning.

---

## 7. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `Fatal: main.py must be executed from within the aibench/ directory` | Command was run from the parent repo root without a `cd aibench;` prefix (or an incorrect `cd`). | Ensure cwd is `aibench/` before invoking `python main.py`, or prefix with `cd aibench; ` (using `;`, not `&&`, for cross-platform safety). |
| `ValueError: Benchmark 'X' is not supported. Registered benchmarks: [...]` | An invalid `-b` name was passed (e.g., a GLMark2 flavor name, or a typo). | Check the registered names list in the error message; for GLMark2 flavors, use `-b glmark2 -t <flavor>` instead. |
| `Error: Config file not found at <path>` | `--config` path is wrong, or `config/benchmarks.yaml` is missing/moved. | Verify `aibench/config/benchmarks.yaml` exists, or pass a correct `-c`/`--config` path. |
| `Aborting execution: <gap validation error>` (exit code 2) | A benchmark ran too recently and the 5-minute cooldown hasn't elapsed. | Wait for the cooldown, or pass `--bypass-gap` if thermally-skewed results are acceptable. |
| Benchmark logged as skipped with reason "Not found in configuration" | Name passed via `-b` or `--skip` doesn't exist under `benchmarks:` in `benchmarks.yaml`. | Double check spelling against the Quick Reference table in `aibench/.claude/skills/benchmark-orchestrator/SKILL.md`. |
| `--cpu-max-prime`, `--threads`, etc. silently ignored | These are Sysbench-specific override flags; passing them for other benchmarks (e.g., `tiobench`) has no effect since only `sysbench.py`'s `_build_command()` consumes `config["overrides"]`. | Only use dynamic overrides (`--time=`, `--threads=`, etc.) when `-b sysbench` is also specified. |
| Test '<name>' not found for benchmark '<bench>'. Skipping. (warning, then defaults used) | A value passed to `-t`/`--tests` doesn't match any key in that benchmark's `test_params`/`tests` list. | Confirm valid sub-test names in `documentation/BenchmarkPrompts.md` for that benchmark. |
| No HTML dashboard generated / "Jinja2 or dashboard template missing" warning | `jinja2` package not installed, or `config/templates/summary_dashboard.html` missing. | `pip install jinja2` and confirm the template file exists under `aibench/config/templates/`. |
| UnixBench error: "/usr/share/unixbench not found" | Target device doesn't have UnixBench installed. | Install UnixBench on the target, or skip this benchmark (`--skip unixbench`). |
| GLMark2 fails to render / empty score | Wayland compositor not running on target, or `WAYLAND_DISPLAY=/run/wayland-0` doesn't match target's actual socket path. | Verify the target's display environment matches what's hardcoded in `config/benchmarks.yaml`'s `glmark2.test_params.*.command`. |
| `--iterations` has no effect for GLMark2 — each flavor still only runs once per suite run | **Confirmed harness bug.** `src/benchmark/glmark2.py` hardcodes `self.iterations = 1` in `__init__` and never reads `self.config.get("iterations", ...)`. | No workaround via CLI today. Use `-r` (suite runs) to get repeat executions of GLMark2 instead; each suite run still only performs 1 iteration per flavor. |
| Confused about why `-r 3` alone (without `--iterations`) produced more total executions than expected | `-r` and `--iterations` multiply: `-r 3` with a benchmark's *default* `--iterations` (e.g. 3) yields `3 × 3 = 9` total sub-test executions, not 3. | See [Section 2](#2-understanding--r-runs-vs---iterations) above for the full `runs × iterations` explanation. |

---

## 8. Output & Reporting Reference

- **Per-run HTML report**: `aibench/output/<benchmark>/build_<id>/<run_name>/report.html` (self-contained; Jinja2-rendered if available, otherwise a simple fallback template with a raw JSON dump).
- **Per-run raw results**: same directory → `results.json`.
- **Per-build aggregated stats**: `aibench/output/<benchmark>/build_<id>/build_analysis.json` (mean/CV statistics across all runs for that build).
- **Unified dashboard**: `aibench/output/reports/index.html` — aggregates all benchmarks and builds, including regression detection, anomaly correlation, and category-grouped charts (CPU/Memory/Threads/Mutex/FileIO/Graphics/scheduler_ipc).
- Always report the dashboard path to the user after a full-suite run, and the individual `report.html`/`build_analysis.json` path after a single-benchmark run.