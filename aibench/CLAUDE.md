# aibench — Agent Instructions

For any benchmark execution/run request under this project, the entry point is the `benchmark-orchestrator` skill — it handles working-directory resolution, intent parsing, and routing to the correct benchmark-specific skill. Try `Skill(benchmark-orchestrator)` first. If that call fails (e.g. `Unknown skill` — this happens when `aibench/` is nested inside a larger repo/workspace whose root Claude Code treats as the project root, so `aibench/.claude/skills/` is never scanned), do not retry it or treat it as blocking — immediately fall back to reading `aibench/.claude/skills/benchmark-orchestrator/SKILL.md` directly with the Read tool and follow it as documentation instead.

Do not invoke `run-<benchmark>` skills directly as a first step, even if the prompt names a specific benchmark (e.g. "run coremark"). Let `benchmark-orchestrator` route there.

Do not run `python main.py --help`, explore `main.py`/`src/`, or run discovery commands (`ls`, `find`) to figure out flags or benchmark names. `aibench/.claude/skills/benchmark-orchestrator/SKILL.md` and the leaf skill it opens already document everything needed to compose and run the correct command.
