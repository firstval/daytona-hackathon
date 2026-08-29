from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .loop import run_autofix


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoFix: self-healing CI loop over a Daytona sandbox.")
    parser.add_argument("--repo", default="sample_repo", help="Local path to the repo to fix (default: sample_repo)")
    parser.add_argument("--test-cmd", default="pytest -q", help="Command to run inside the sandbox to check success")
    parser.add_argument("--max-iterations", type=int, default=None, help="Override MAX_ITERATIONS from .env")
    args = parser.parse_args()

    settings = load_settings()
    if args.max_iterations is not None:
        settings.max_iterations = args.max_iterations

    result = run_autofix(repo_dir=args.repo, settings=settings, test_cmd=args.test_cmd)

    print("\n" + "=" * 60)
    if result.success:
        print(f"AutoFix succeeded after {result.iterations_used} iteration(s).")
    else:
        print(f"AutoFix did not converge within {result.iterations_used} iteration(s).")
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
