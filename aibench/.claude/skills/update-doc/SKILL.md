---
name: update-doc
description: Automatically update Architecture.md based on recent git commits
category: documentation
---

# Update Documentation Skill

**version:** 1.1
**author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
**created:** 2026-09-16

## Overview

Automatically updates `aibench/documentation/Architecture.md` based on recent git commits. This skill analyzes code changes in the aibench folder and generates corresponding documentation updates.

## Features

- **Incremental Updates**: Only processes new commits since last run
- **Commit Tracking**: Maintains persistent state of processed commits
- **Dirty Branch Detection**: Ensures working directory is clean before processing
- **Error Recovery**: Fallback to full scan if state is corrupted
- **Modular Design**: Separate components for git, analysis, generation, and updates

## Invocation

### Entry Point
```python
scripts/run_update_doc.py
```

### Function
```python
run_update_doc(force_full_scan=False, commits_to_process=0)
```

## Input Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `force_full_scan` | bool | false | Force full scan ignoring commit history |
| `commits_to_process` | int | 0 | Number of recent commits to process (0 = all new) |

## Output

| Field | Type | Description |
|-------|------|-------------|
| `status` | str | "success" or "error" |
| `commits_processed` | int | Number of commits analyzed |
| `sections_updated` | list[str] | List of Architecture.md sections updated |
| `documentation_changes` | str | Summary of changes made |
| `state_file_updated` | bool | Whether commit_tracker.json was updated |

## State Management

### Location
```
aibench/.claude/skills/update-doc/state/commit_tracker.json
```

### Format
```json
{
  "last_processed_commit": "commit_hash",
  "last_update_timestamp": "ISO8601_timestamp",
  "documentation_version": "1.0",
  "sections_updated": ["5", "8", "9"],
  "update_history": [
    {
      "commit_id": "commit_hash",
      "timestamp": "ISO8601_timestamp",
      "files_changed": ["file1.py", "file2.py"],
      "sections_affected": ["5.2.1", "9.2.1"],
      "status": "success"
    }
  ]
}
```

### Retention
- Keeps last 100 commit entries in history
- State file persists across runs
- Can be reset with `--force-full-scan`

## Dependencies

```
PyYAML>=6.0
Jinja2>=3.0
GitPython>=3.1.0
```

Install with:
```bash
pip install -r scripts/requirements.txt
```

## Workflow

### 1. Check Git Status
- Verify working directory is clean
- Abort if uncommitted changes detected

### 2. Load State
- Read `state/commit_tracker.json`
- Get last processed commit ID
- If first run, process all commits

### 3. Get Recent Commits
- Query git log for commits since last processed
- Extract commit ID, message, timestamp

### 4. Analyze Code Changes
- For each commit:
  - Get changed files in `aibench/` folder
  - Parse Python AST for code structure
  - Extract functions, classes, docstrings
  - Identify architectural patterns

### 5. Generate Documentation
- Map code changes to Architecture.md sections
- Generate function/class documentation
- Create code examples
- Build parameter tables

### 6. Update Architecture.md
- Read current document
- Identify sections to update
- Merge new documentation
- Preserve manual sections (marked with `<!-- MANUAL -->`)
- Update table of contents

### 7. Update State
- Save processed commit ID
- Add to update history
- Write `commit_tracker.json`

## Code-to-Documentation Mapping

| Code Location | Architecture Section | Pattern |
|---------------|---------------------|---------|
| `src/benchmark/*.py` | Section 5 | `class.*Benchmark.*BenchmarkBase` |
| `src/reporting/outlier_detector*.py` | Section 6 | `class.*OutlierDetector` |
| `src/utils/telemetry/` | Section 7 | `def.*telemetry` |
| `src/reporting/regression_detector.py` | Section 8 | `def.*detect.*` |
| `src/reporting/rca_detector.py` | Section 9 | `def.*analyze` |
| `config/benchmarks.yaml` | Section 11 | YAML keys |
| `main.py` | Section 12 | Execution phases |

## Usage Examples

### Normal Run (Incremental)
```bash
python scripts/run_update_doc.py
```

### Force Full Scan
```bash
python scripts/run_update_doc.py --force-full-scan
```

### Process Specific Number of Commits
```bash
python scripts/run_update_doc.py --commits-to-process 5
```

### Check State
```bash
cat state/commit_tracker.json
```

## Error Handling

### Dirty Branch
```
Status: DIRTY ✗
→ Error: "Working directory has uncommitted changes"
→ Action: Abort and ask user to commit/stash
```

### First Run (No State File)
```
Last Commit: None
→ Process all commits in repository
→ Create state file with latest commit ID
```

### State File Corrupted
```
→ Detect JSON parse error
→ Fallback to full scan
→ Regenerate state file
→ Log warning
```

### Commit History Rewritten
```
→ Detect if last_processed_commit no longer exists
→ Fallback to full scan
→ Update state file
→ Log warning about history rewrite
```

## Performance

### First Run
- Scan all commits: ~5 minutes (100 commits)
- Create state file

### Subsequent Runs
- Process new commits only: ~10 seconds (2 commits)
- Update state file

### No New Commits
- Instant return: ~2 seconds
- No changes made

## Testing

### Unit Tests
```bash
python -m pytest tests/test_git_manager.py
python -m pytest tests/test_state_manager.py
python -m pytest tests/test_code_analyzer.py
python -m pytest tests/test_doc_generator.py
```

### Integration Tests
```bash
python -m pytest tests/test_integration.py
```

## File Structure

```
aibench/.claude/skills/update-doc/
├── SKILL.md                          # This file
├── scripts/
│   ├── main.py                       # Orchestrator
│   ├── git_manager.py                # Git operations
│   ├── state_manager.py              # State persistence
│   ├── code_analyzer.py              # Code analysis
│   ├── doc_generator.py              # Doc generation
│   ├── doc_updater.py                # Doc updates
│   ├── run_update_doc.py             # Entry point
│   └── requirements.txt              # Dependencies
├── state/
│   └── commit_tracker.json           # Persistent state
├── templates/
│   ├── section_template.md           # Section template
│   ├── code_block_template.md        # Code example template
│   └── function_signature_template.md # Function doc template
├── reference/
│   ├── code_patterns.md              # Patterns to detect
│   ├── doc_mapping.json              # Code-to-doc mapping
│   └── section_guidelines.md         # Section guidelines
└── tests/
    ├── test_git_manager.py
    ├── test_state_manager.py
    ├── test_code_analyzer.py
    ├── test_doc_generator.py
    └── test_integration.py
```

## Limitations

- Only processes Python files (`.py`)
- Only updates Architecture.md (not other docs)
- Requires clean git working directory
- Manual sections must be marked with `<!-- MANUAL -->`
- Does not handle binary files or images

## Future Enhancements

- Support for multiple documentation files
- Automatic diagram generation (Mermaid)
- Support for other languages (C, C++, Shell)
- Integration with CI/CD pipelines
- Automatic PR creation for doc updates
- AI-powered documentation improvement suggestions

## Contact

For questions or issues:
- **Author**: Sarbojit Ganguly
- **Email**: sarbgang@qti.qualcomm.com
- **Repository**: https://github.qualcomm.com/linux/skills-lab

## License

Internal use only - Qualcomm Technologies, Inc.