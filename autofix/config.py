from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    daytona_api_key: str
    daytona_api_url: str
    daytona_target: str

    nosana_coder_base_url: str
    nosana_coder_api_key: str
    nosana_coder_model: str

    nosana_critic_base_url: str
    nosana_critic_api_key: str
    nosana_critic_model: str

    max_iterations: int


def _env(name: str, default: str = "") -> str:
    # os.environ.get(name, default) only falls back when the key is absent -
    # GitHub Actions substitutes unset `vars.X` as an empty string rather
    # than omitting it, so an empty value must fall back too.
    return os.environ.get(name) or default


def _require(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def load_settings() -> Settings:
    coder_base_url = _require("NOSANA_CODER_BASE_URL")
    coder_api_key = _env("NOSANA_CODER_API_KEY")

    return Settings(
        daytona_api_key=_require("DAYTONA_API_KEY"),
        daytona_api_url=_env("DAYTONA_API_URL", "https://app.daytona.io/api"),
        daytona_target=_env("DAYTONA_TARGET", "us"),
        nosana_coder_base_url=coder_base_url,
        nosana_coder_api_key=coder_api_key,
        nosana_coder_model=_env("NOSANA_CODER_MODEL", "qwen3.6:35b-a3b-q8_0"),
        nosana_critic_base_url=_env("NOSANA_CRITIC_BASE_URL", coder_base_url),
        nosana_critic_api_key=_env("NOSANA_CRITIC_API_KEY", coder_api_key),
        nosana_critic_model=_env("NOSANA_CRITIC_MODEL", "glm-4.7-flash:bf16"),
        max_iterations=int(_env("MAX_ITERATIONS", "4")),
    )
