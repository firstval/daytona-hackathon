from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from openai import APIError

from . import coder_agent
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


@dataclass
class CheckRun:
    output: str
    suggested_diff: str | None = None
    suggestion_verified: bool | None = None
    suggestion_apply_error: str | None = None
    coder_error: str | None = None


def run_checks_and_suggest_fix(repo_dir: str, test_cmd: str, lint_cmd: str | None, settings) -> CheckRun:
    with RepoSandbox(settings) as sandbox:
        sandbox.bootstrap(repo_dir)
        sections = []

        test_result = sandbox.run(test_cmd)
        sections.append(f"$ {test_cmd}\nexit_code={test_result.exit_code}\n{test_result.output.strip()}")

        if lint_cmd:
            lint_result = sandbox.run(lint_cmd)
            sections.append(f"$ {lint_cmd}\nexit_code={lint_result.exit_code}\n{lint_result.output.strip()}")

        check_output = "\n\n".join(sections)
        if test_result.ok:
            return CheckRun(output=check_output)

        # Tests are failing: ask the Coder model for a fix and verify it in
        # this same sandbox before ever showing it to a human, so the
        # comment can say "confirmed passing" rather than just guessing.
        coder = LLMClient(
            base_url=settings.nosana_coder_base_url,
            api_key=settings.nosana_coder_api_key,
            model=settings.nosana_coder_model,
        )
        context = sandbox.collect_context()
        try:
            diff_text = coder_agent.propose_patch(coder, failing_output=test_result.output, repo_context=context)
        except APIError as e:
            return CheckRun(output=check_output, coder_error=str(e))

        apply_result = sandbox.apply_diff(diff_text)
        if not apply_result.ok:
            return CheckRun(
                output=check_output,
                suggested_diff=diff_text,
                suggestion_apply_error=apply_result.output,
            )

        verify_result = sandbox.run(test_cmd)
        return CheckRun(output=check_output, suggested_diff=diff_text, suggestion_verified=verify_result.ok)


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


def format_comment(review: Review, reviewer_model: str, checks: CheckRun, coder_model: str) -> str:
    verdict_badge = "✅ Approve" if review.verdict == "approve" else "⚠️ Request changes"
    lines = [
        f"## 🤖 AutoFix Review ({reviewer_model} via Nosana)",
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

    if checks.suggested_diff:
        lines.append("")
        if checks.suggestion_verified:
            lines.append(
                f"### Suggested fix ({coder_model} via Nosana)\n"
                "Applied and re-run in the same sandbox - **tests passed** with this change:"
            )
        elif checks.suggestion_apply_error:
            lines.append(
                f"### Suggested fix ({coder_model} via Nosana, unverified)\n"
                "This diff did not apply cleanly in the sandbox, so it has **not** been "
                "confirmed to fix anything - treat it as a rough starting point:"
            )
        else:
            lines.append(
                f"### Suggested fix ({coder_model} via Nosana, unverified)\n"
                "This diff applied cleanly but tests still failed afterwards - it may be "
                "a partial fix:"
            )
        lines.append(f"```diff\n{checks.suggested_diff.strip()}\n```")
    elif checks.coder_error:
        lines.append("")
        lines.append(
            f"### Suggested fix unavailable\n"
            f"The Coder model ({coder_model} via Nosana) didn't respond - likely a "
            f"temporary issue with that Nosana job, not with this PR:\n"
            f"```\n{checks.coder_error.strip()}\n```"
        )

    lines.append("")
    lines.append(
        "---\n*Generated automatically by Nosana-hosted models reviewing real Daytona "
        "sandbox output (tests/lint). A \"request changes\" verdict fails this check.*"
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
    checks = run_checks_and_suggest_fix(repo_dir, test_cmd, lint_cmd, settings)
    print(checks.output)
    if checks.suggested_diff:
        print(f"[pr-review] tests failed; coder-suggested fix (verified={checks.suggestion_verified}):")
        print(checks.suggested_diff)

    print("[pr-review] requesting structured review from the Nosana-hosted model")
    try:
        review = request_review(reviewer, diff_text, checks.output)
    except APIError as e:
        print(f"[pr-review] Critic model unavailable: {e}")
        post_comment(
            pr_number,
            "## 🤖 AutoFix Review\n\n"
            f"**Could not complete the review** - the Critic model "
            f"({settings.nosana_critic_model} via Nosana) didn't respond:\n"
            f"```\n{e}\n```\n"
            "This is a temporary issue with that Nosana job, not with this PR. "
            "Re-run the check once it recovers.",
        )
        sys.exit(1)
    print(f"[pr-review] verdict={review.verdict}")

    comment = format_comment(review, settings.nosana_critic_model, checks, settings.nosana_coder_model)
    post_comment(pr_number, comment)
    print("[pr-review] posted review comment")

    if review.verdict != "approve":
        print(f"[pr-review] verdict={review.verdict!r} - failing the check")
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main() or 0)
