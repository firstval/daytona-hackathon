from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import coder_agent, critic_agent
from .config import Settings
from .daytona_sandbox import RepoSandbox
from .llm_client import LLMClient

Logger = Callable[[str], None]


@dataclass
class LoopResult:
    success: bool
    iterations_used: int
    log: list[str] = field(default_factory=list)


def run_autofix(
    repo_dir: str,
    settings: Settings,
    test_cmd: str = "pytest -q",
    on_log: Logger | None = None,
) -> LoopResult:
    log: list[str] = []

    def emit(message: str) -> None:
        log.append(message)
        if on_log:
            on_log(message)
        else:
            print(message)

    coder = LLMClient(
        base_url=settings.nosana_coder_base_url,
        api_key=settings.nosana_coder_api_key,
        model=settings.nosana_coder_model,
    )
    critic = LLMClient(
        base_url=settings.nosana_critic_base_url,
        api_key=settings.nosana_critic_api_key,
        model=settings.nosana_critic_model,
    )

    with RepoSandbox(settings) as sandbox:
        emit(f"[setup] uploading {repo_dir} into a fresh Daytona sandbox")
        sandbox.bootstrap(repo_dir)

        feedback: str | None = None
        for iteration in range(1, settings.max_iterations + 1):
            emit(f"\n=== Iteration {iteration}/{settings.max_iterations} ===")

            emit(f"[daytona] running `{test_cmd}`")
            test_result = sandbox.run(test_cmd)
            emit(f"[daytona] exit_code={test_result.exit_code}")
            emit(test_result.output.strip())

            if test_result.ok:
                emit("[success] all tests passing")
                return LoopResult(success=True, iterations_used=iteration - 1, log=log)

            emit("[coder] requesting a patch from the Nosana-hosted coder model")
            context = sandbox.collect_context()
            diff_text = coder_agent.propose_patch(
                coder, failing_output=test_result.output, repo_context=context, feedback=feedback
            )
            emit(f"[coder] proposed diff:\n{diff_text}")

            apply_result = sandbox.apply_diff(diff_text)
            if not apply_result.ok:
                emit(f"[daytona] patch failed to apply:\n{apply_result.output}")
                feedback = (
                    f"Your last diff failed to apply with `git apply`:\n{apply_result.output}\n"
                    "Return a corrected unified diff against the current file contents."
                )
                continue

            review = critic_agent.review(critic, diff_text=sandbox.diff(), failing_output=test_result.output)
            emit(f"[critic:{review.method}] approved={review.approved} reason={review.reason}")

            if not review.approved:
                sandbox.discard_uncommitted()
                feedback = (
                    f"Your previous patch was rejected by the critic: {review.reason}\n"
                    "Propose a different fix that addresses the actual bug without cheating."
                )
                continue

            sandbox.commit(f"autofix: iteration {iteration}")
            feedback = None

        emit(f"\n[failure] reached max iterations ({settings.max_iterations}) without a passing test run")
        return LoopResult(success=False, iterations_used=settings.max_iterations, log=log)
