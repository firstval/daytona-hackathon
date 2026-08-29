from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from .config import load_settings
from .daytona_sandbox import RepoSandbox
from .llm_client import LLMClient

SYSTEM_PROMPT = """You are an automated code reviewer for a pull request. You are given:
1. The full diff of the pull request.
2. The output of running the project's test suite (and optionally a linter)
   against the PR's code in a real sandbox - this is ground truth, not a
   simulation.

Write a structured review. Respond with ONLY a JSON object of this form:
{
  "summary": "one or two sentence overview of the change",
  "issues": [
    {"severity": "high" | "medium" | "low", "file": "path or null", "description": "..."}
  ],
  "verdict": "approve" or "request_changes"
}

Set verdict to "request_changes" if the test run failed, or if you find a
real correctness bug, security issue, or significant design problem
introduced by this diff. Otherwise "approve". Only list genuine issues -
do not pad the list to seem thorough.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Review:
    summary: str
    issues: list[dict] = field(default_factory=list)
    verdict: str = "request_changes"
    raw: str = ""


def get_pr_diff(pr_number: str) -> str:
    result = subprocess.run(
        ["gh", "pr", "diff", pr_number],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def run_checks(repo_dir: str, test_cmd: str, lint_cmd: str | None, settings) -> str:
    with RepoSandbox(settings) as sandbox:
        sandbox.bootstrap(repo_dir)
        sections = []

        test_result = sandbox.run(test_cmd)
        sections.append(f"$ {test_cmd}\nexit_code={test_result.exit_code}\n{test_result.output.strip()}")

        if lint_cmd:
            lint_result = sandbox.run(lint_cmd)
            sections.append(f"$ {lint_cmd}\nexit_code={lint_result.exit_code}\n{lint_result.output.strip()}")

        return "\n\n".join(sections)


def request_review(client: LLMClient, diff_text: str, check_output: str) -> Review:
    user = f"## Pull request diff\n```diff\n{diff_text.strip()}\n```\n\n## Sandbox check output\n```\n{check_output.strip()}\n```"
    raw = client.complete(system=SYSTEM_PROMPT, user=user, temperature=0.0)

    match = _JSON_RE.search(raw)
    if not match:
        return Review(summary="The reviewer model returned an unparseable response.", raw=raw)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Review(summary="The reviewer model returned invalid JSON.", raw=raw)

    return Review(
        summary=str(payload.get("summary", "")),
        issues=list(payload.get("issues", [])),
        verdict=str(payload.get("verdict", "request_changes")),
        raw=raw,
    )


def format_comment(review: Review, model: str) -> str:
    verdict_badge = "✅ Approve" if review.verdict == "approve" else "⚠️ Request changes"
    lines = [
        f"## 🤖 AutoFix Review ({model} via Nosana)",
        "",
        f"**Verdict:** {verdict_badge}",
        "",
        review.summary or "_No summary provided._",
    ]

    if review.issues:
        lines.append("")
        lines.append("### Issues")
        for issue in review.issues:
            severity = issue.get("severity", "?")
            file = issue.get("file")
            description = issue.get("description", "")
            location = f" `{file}`" if file else ""
            lines.append(f"- **[{severity}]**{location}: {description}")

    lines.append("")
    lines.append(
        "---\n*Generated automatically by a Nosana-hosted model reviewing real Daytona "
        "sandbox output (tests/lint). This is advisory only and does not block merging.*"
    )
    return "\n".join(lines)


def post_comment(pr_number: str, body: str) -> None:
    subprocess.run(["gh", "pr", "comment", pr_number, "--body", body], check=True)


def main() -> None:
    pr_number = os.environ["PR_NUMBER"]
    repo_dir = os.environ.get("REPO_DIR", ".")
    test_cmd = os.environ.get("AUTOFIX_TEST_CMD", "pytest -q")
    lint_cmd = os.environ.get("AUTOFIX_LINT_CMD") or None

    settings = load_settings()
    reviewer = LLMClient(
        base_url=settings.nosana_critic_base_url,
        api_key=settings.nosana_critic_api_key,
        model=settings.nosana_critic_model,
    )

    print(f"[pr-review] fetching diff for PR #{pr_number}")
    diff_text = get_pr_diff(pr_number)

    print(f"[pr-review] running checks in a Daytona sandbox: {test_cmd!r}")
    check_output = run_checks(repo_dir, test_cmd, lint_cmd, settings)
    print(check_output)

    print("[pr-review] requesting structured review from the Nosana-hosted model")
    review = request_review(reviewer, diff_text, check_output)
    print(f"[pr-review] verdict={review.verdict}")

    comment = format_comment(review, settings.nosana_critic_model)
    post_comment(pr_number, comment)
    print("[pr-review] posted review comment")


if __name__ == "__main__":
    sys.exit(main() or 0)
