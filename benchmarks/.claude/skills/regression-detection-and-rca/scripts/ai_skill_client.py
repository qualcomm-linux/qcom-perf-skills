"""
ai_skill_client.py - Shells out to the local AI CLI to run the
Chain-of-Thought skills (regression_detector.md / rca_detector.md) directly
against raw data, as the primary detection/RCA path.

Callers are expected to validate the returned dict against the exact
Python-engine schema themselves (the two skills have different expected
shapes) and fall back to the deterministic Python engine on any
AISkillError or schema mismatch -- this module never falls back on its own.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

_THIS_DIR = Path(__file__).resolve().parent
_AI_CLI_BINARY = "claude"


class AISkillError(Exception):
    """Raised whenever the AI skill call cannot be trusted as a result."""
    pass


def _extract_json(raw_text: str) -> Dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw_text[start:end + 1])
        except json.JSONDecodeError as e:
            raise AISkillError(f"AI response was not valid JSON: {e}") from e

    raise AISkillError("AI response contained no JSON object")


def call_ai_skill(skill_md_filename: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    """
    Runs the named Chain-of-Thought skill spec (e.g. "regression_detector.md")
    against `payload` via the local AI CLI in non-interactive mode, and
    returns the parsed JSON result.

    Raises AISkillError on any failure (CLI missing, timeout, non-zero exit,
    unparseable output) -- callers must catch this and fall back to the
    deterministic Python engine.
    """
    skill_md_path = _THIS_DIR / skill_md_filename
    try:
        skill_instructions = skill_md_path.read_text(encoding="utf-8")
    except OSError as e:
        raise AISkillError(f"Could not read skill spec {skill_md_path}: {e}") from e

    prompt = (
        f"{skill_instructions}\n\n"
        "Apply the Chain-of-Thought logic above directly to the following input data:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Respond with ONLY the resulting raw JSON object described by the logic above. "
        "No markdown code fences, no explanation, no text before or after the JSON."
    )

    try:
        proc = subprocess.run(
            [_AI_CLI_BINARY, "-p", prompt, "--output-format", "text"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise AISkillError(f"AI CLI call timed out after {timeout}s") from e
    except OSError as e:
        raise AISkillError(f"Could not invoke AI CLI ({_AI_CLI_BINARY}): {e}") from e

    if proc.returncode != 0:
        raise AISkillError(f"AI CLI exited with status {proc.returncode}: {proc.stderr.strip()}")

    if not proc.stdout.strip():
        raise AISkillError("AI CLI returned empty output")

    return _extract_json(proc.stdout)
