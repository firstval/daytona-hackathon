from __future__ import annotations

import re

from .llm_client import LLMClient

SYSTEM_PROMPT = """You are an autonomous coding agent. You are given:
1. The output of a failing test run (stdout/stderr/exit code) from a real sandbox.
2. The full contents of every tracked file in the repository.

Your job is to fix the underlying bug so the tests pass.

Rules:
- Respond with ONLY a single unified diff (git-style), and nothing else - no
  markdown fences, no prose before or after.
- Use paths relative to the repo root with `--- a/<path>` / `+++ b/<path>` headers.
- Do NOT modify any file under a `tests/` directory or matching `test_*.py`.
  Fix the implementation, not the test.
- Do NOT delete, skip, or weaken any test or assertion.
- Keep the diff minimal and focused on the actual bug.
"""

_FENCE_RE = re.compile(r"^```(?:diff|patch)?\n|```$", re.MULTILINE)


def _clean_diff(raw: str) -> str:
    text = _FENCE_RE.sub("", raw).strip()
    if not text.endswith("\n"):
        text += "\n"
    return text


def propose_patch(
    client: LLMClient,
    failing_output: str,
    repo_context: str,
    feedback: str | None = None,
) -> str:
    user_parts = [
        f"## Failing test output\n```\n{failing_output.strip()}\n```",
        f"## Repository files\n{repo_context}",
    ]
    if feedback:
        user_parts.append(f"## Feedback on your previous attempt\n{feedback}")
    user_parts.append("Return the unified diff that fixes this.")

    raw = client.complete(system=SYSTEM_PROMPT, user="\n\n".join(user_parts))
    return _clean_diff(raw)
