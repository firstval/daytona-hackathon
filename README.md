# AutoFix — a self-healing CI loop

A broken repo goes in; two agents work against a live [Daytona](https://daytona.io)
sandbox until it's green, with a decentralized model hosted on
[Nosana](https://nosana.com) doing the reasoning.

```
        ┌──────────────┐  failing output +  ┌──────────────┐
   ┌───▶│  Coder agent │  repo context      │   Daytona    │
   │    │ (Nosana LLM) │───────────────────▶│   sandbox    │
   │    └──────────────┘   unified diff     │ (real repo,  │
   │                                        │  real pytest)│
   │    ┌──────────────┐  approve/reject    └──────┬───────┘
   └────│ Critic agent │◀───────────────────────────┘
        │ (Nosana LLM  │   diff + test output
        │ + rule check)│
        └──────────────┘
```

1. **Coder agent** gets the failing pytest output + full repo contents, and
   proposes a unified diff via a Qwen2.5-Coder model hosted as an inference
   job on Nosana.
2. **Daytona sandbox** is the ground truth: it applies the diff with
   `git apply` and re-runs the tests for real — no mocked results.
3. **Critic agent** inspects the diff for cheating (deleted/weakened tests,
   hardcoded outputs) using a fast rule-based check plus a second, smaller
   Nosana-hosted model call. Rejections go back to the Coder with a reason.
4. Loop for up to `MAX_ITERATIONS` (default 4) or until tests pass.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # macOS/Linux

cp .env.example .env
```

Fill in `.env`:
- `DAYTONA_API_KEY` — from your Daytona dashboard.
- `NOSANA_CODER_BASE_URL` — the OpenAI-compatible endpoint of your Nosana job
  serving the Coder model, including the `/v1` suffix. Using the Nosana
  template gallery, deploy **Qwen 3.6 (35B-A3B)** for this role — a
  mixture-of-experts variant that gives you a bigger, more code-capable model
  while only activating ~3B params per token, so it stays fast on shared GPU
  compute.
- `NOSANA_CODER_API_KEY` — if your job requires one (some public endpoints don't).
- `NOSANA_CODER_MODEL` — the exact model tag Ollama pulled, e.g. `qwen3.6:35b-a3b`.
  Confirm with `curl <NOSANA_CODER_BASE_URL>/models` after deploying; the
  Hugging Face-style name won't match Ollama's OpenAI-compat API.
- `NOSANA_CRITIC_BASE_URL`/`NOSANA_CRITIC_API_KEY`/`NOSANA_CRITIC_MODEL` —
  deploy **GLM-4.7-Flash** for this role. It's deliberately a different model
  family from the Coder (not just a smaller Qwen) so the critic isn't
  checking the Coder's work with the Coder's own blind spots, and it's fast
  enough to keep each loop iteration quick. Leave blank to reuse the Coder
  endpoint for the critic too.

## Run

```bash
.venv/Scripts/python -m autofix.cli --repo sample_repo
```

`sample_repo/` is a small `calc` package with 4 intentionally broken
functions (`add`, `fibonacci`, `is_palindrome`, `most_common_word`) and a
`pytest` suite that fails against all of them — good for demoing multiple
loop iterations.

Point `--repo` at any other local directory with a `requirements.txt` and a
test command to try it on something else:

```bash
.venv/Scripts/python -m autofix.cli --repo path/to/other/repo --test-cmd "pytest -q"
```

## Demo tips

- Run with the terminal visible — every iteration prints the failing output,
  the proposed diff, and the critic's verdict live.
- To show the Critic actually catching something, you can manually test it
  by editing `autofix/coder_agent.py`'s `SYSTEM_PROMPT` to *not* forbid
  touching tests, which makes it much easier to provoke the model into
  deleting a test — the rule-based check in `critic_agent.py` will catch it
  every time.
- Fallback if the network hiccups during judging: re-run against
  `sample_repo` from a clean `git stash`/checkout, or fall back to a single
  Coder-only pass (skip the Critic call) to still show the Daytona
  ground-truth loop working end to end.
