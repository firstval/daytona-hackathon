from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig

from .config import Settings

REMOTE_ROOT = "/home/daytona/repo"

# Any exec-oriented image works; git isn't guaranteed present so bootstrap()
# installs it on demand rather than depending on the exact base image.
DEFAULT_IMAGE = "python:3.12-slim"

_ENSURE_TOOLS = (
    "(command -v git >/dev/null 2>&1 || "
    "(apt-get update -qq && apt-get install -qq -y git >/dev/null))"
)


@dataclass
class ExecResult:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class RepoSandbox:
    """Owns one Daytona sandbox holding a real checkout of the target repo.
    This is the ground truth for the loop: patches are applied here and
    stdout/stderr/exit_code come straight from a live `pytest` run, not a
    simulation."""

    def __init__(self, settings: Settings, image: str = DEFAULT_IMAGE) -> None:
        self._daytona = Daytona(
            DaytonaConfig(
                api_key=settings.daytona_api_key,
                api_url=settings.daytona_api_url,
                target=settings.daytona_target,
            )
        )
        self._image = image
        self._sandbox = None

    def __enter__(self) -> "RepoSandbox":
        self._sandbox = self._daytona.create(CreateSandboxFromImageParams(image=self._image))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._sandbox is not None:
            self._sandbox.delete()

    def bootstrap(self, local_dir: str, install_cmd: str = "pip install -q -r requirements.txt") -> None:
        local_root = Path(local_dir)
        for path in sorted(local_root.rglob("*")):
            if path.is_file():
                remote_path = f"{REMOTE_ROOT}/{path.relative_to(local_root).as_posix()}"
                self._sandbox.fs.upload_file(path.read_bytes(), remote_path)

        tools = self.run(_ENSURE_TOOLS)
        if not tools.ok:
            raise RuntimeError(f"Failed to prepare sandbox tools:\n{tools.output}")

        init = self.run(
            "git init -q && "
            "git config user.name AutoFix && git config user.email autofix@local && "
            "git add -A && git commit -q -m initial --allow-empty"
        )
        if not init.ok:
            raise RuntimeError(f"Failed to initialize repo git history:\n{init.output}")

        if install_cmd and (local_root / "requirements.txt").exists():
            result = self.run(install_cmd)
            if not result.ok:
                raise RuntimeError(f"Sandbox dependency install failed:\n{result.output}")

    def run(self, command: str, timeout: int = 180) -> ExecResult:
        response = self._sandbox.process.exec(command, cwd=REMOTE_ROOT, timeout=timeout)
        return ExecResult(exit_code=response.exit_code, output=response.result or "")

    def apply_diff(self, diff_text: str) -> ExecResult:
        self._sandbox.fs.upload_file(diff_text.encode(), "/tmp/autofix.diff")
        # --recount: LLM-authored diffs routinely miscount the context/line
        # totals in `@@ -a,b +c,d @@` hunk headers even when the actual
        # +/-/context lines are correct; plain `git apply` rejects those as
        # "corrupt patch" while --recount recomputes the counts itself.
        return self.run("git apply --recount --whitespace=fix /tmp/autofix.diff")

    def diff(self) -> str:
        return self.run("git diff").output

    def commit(self, message: str) -> None:
        self.run(f'git add -A && git commit -q -m "{message}" --allow-empty')

    def discard_uncommitted(self) -> None:
        self.run("git checkout -q -- . && git clean -qfd")

    def tracked_files(self) -> list[str]:
        result = self.run("git ls-files")
        return [line for line in result.output.splitlines() if line.strip()]

    def read_file(self, relative_path: str) -> str:
        data = self._sandbox.fs.download_file(f"{REMOTE_ROOT}/{relative_path}")
        return data.decode(errors="replace") if data else ""

    def collect_context(self, max_chars: int = 20_000) -> str:
        """Dump every tracked file's contents for the Coder agent's prompt."""
        chunks = []
        used = 0
        for relative_path in self.tracked_files():
            content = self.read_file(relative_path)
            chunk = f"--- {relative_path} ---\n{content}\n"
            if used + len(chunk) > max_chars:
                chunks.append(f"... (truncated, {relative_path} and later files omitted)")
                break
            chunks.append(chunk)
            used += len(chunk)
        return "\n".join(chunks)
