"""Runtime configuration contract for the ChatBI frontend.

The frontend only needs the Backend API base URL and display defaults. It must
not receive database, Redis, vector-store, or agent service URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Literal, Mapping, cast


FrontendEnvironment = Literal["dev", "staging", "prod"]
FrontendLocale = Literal["en", "zh-CN"]

FORBIDDEN_FRONTEND_CONFIG_KEYS = frozenset(
    {
        "database_url",
        "redis_url",
        "vector_store_url",
        "agent_url",
    }
)

FORBIDDEN_FRONTEND_ENV_KEYS = frozenset(
    {
        "DATABASE_URL",
        "REDIS_URL",
        "VECTOR_STORE_URL",
        "AGENT_URL",
    }
)


@dataclass(frozen=True, slots=True)
class FrontendRuntimeConfig:
    api_base_url: str
    environment: FrontendEnvironment
    locale_default: FrontendLocale


def parse_frontend_runtime_config(raw: Mapping[str, object]) -> FrontendRuntimeConfig:
    """Build the public frontend config and reject backend-only secrets."""

    forbidden_keys = FORBIDDEN_FRONTEND_CONFIG_KEYS.intersection(raw)
    if forbidden_keys:
        names = ", ".join(sorted(forbidden_keys))
        raise ValueError(f"Frontend config contains forbidden backend keys: {names}")

    api_base_url = _required_string(raw.get("api_base_url"), "api_base_url")
    if not api_base_url.startswith(("http://", "https://", "/")):
        raise ValueError("api_base_url must be an absolute URL or an app-relative path")

    environment = _environment(raw.get("environment"))
    locale_default = _locale(raw.get("locale_default"))
    return FrontendRuntimeConfig(
        api_base_url=api_base_url.rstrip("/") or "/",
        environment=environment,
        locale_default=locale_default,
    )


def load_frontend_runtime_config(
    env: Mapping[str, str] | None = None,
) -> FrontendRuntimeConfig:
    """Load browser-safe frontend runtime config from deployment environment."""

    runtime_env = env or os.environ
    forbidden_env_keys = FORBIDDEN_FRONTEND_ENV_KEYS.intersection(runtime_env)
    if forbidden_env_keys:
        names = ", ".join(sorted(forbidden_env_keys))
        raise ValueError(f"Frontend environment contains forbidden backend keys: {names}")

    return parse_frontend_runtime_config(
        {
            "api_base_url": _first_present(
                runtime_env,
                "CHATBI_FRONTEND_API_BASE_URL",
                "API_BASE_URL",
                "BACKEND_API_URL",
            ),
            "environment": _first_present(
                runtime_env,
                "CHATBI_FRONTEND_ENVIRONMENT",
                "FRONTEND_ENVIRONMENT",
            ),
            "locale_default": _first_present(
                runtime_env,
                "CHATBI_FRONTEND_LOCALE_DEFAULT",
                "FRONTEND_LOCALE_DEFAULT",
            ),
        }
    )


def public_frontend_runtime_config(config: FrontendRuntimeConfig) -> dict[str, str]:
    """Serialize only fields that are safe to expose to browser code."""

    return {
        "api_base_url": config.api_base_url,
        "environment": config.environment,
        "locale_default": config.locale_default,
    }


def frontend_runtime_config_script(config: FrontendRuntimeConfig) -> str:
    """Render the browser runtime config as a small JavaScript assignment."""

    payload = json.dumps(
        public_frontend_runtime_config(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return f"window.__CHATBI_RUNTIME_CONFIG__={payload};"


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _environment(value: object) -> FrontendEnvironment:
    if value not in {"dev", "staging", "prod"}:
        raise ValueError("environment must be one of: dev, staging, prod")
    return cast(FrontendEnvironment, value)


def _locale(value: object) -> FrontendLocale:
    if value not in {"en", "zh-CN"}:
        raise ValueError("locale_default must be one of: en, zh-CN")
    return cast(FrontendLocale, value)


def _first_present(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None:
            return value
    return None
