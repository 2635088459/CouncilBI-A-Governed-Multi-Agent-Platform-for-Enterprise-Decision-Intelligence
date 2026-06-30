import pytest

from chatbi.frontend.runtime_config import (
    frontend_runtime_config_script,
    load_frontend_runtime_config,
    parse_frontend_runtime_config,
    public_frontend_runtime_config,
)


def test_parse_frontend_runtime_config_keeps_only_public_fields() -> None:
    config = parse_frontend_runtime_config(
        {
            "api_base_url": "https://chatbi.example.com/api/",
            "environment": "staging",
            "locale_default": "zh-CN",
        }
    )

    public_config = public_frontend_runtime_config(config)

    assert public_config == {
        "api_base_url": "https://chatbi.example.com/api",
        "environment": "staging",
        "locale_default": "zh-CN",
    }


def test_parse_frontend_runtime_config_rejects_backend_only_urls() -> None:
    with pytest.raises(ValueError, match="database_url"):
        parse_frontend_runtime_config(
            {
                "api_base_url": "/api",
                "environment": "dev",
                "locale_default": "en",
                "database_url": "postgresql://chatbi:test@db:5432/chatbi",
            }
        )


def test_load_frontend_runtime_config_reads_deployment_env() -> None:
    config = load_frontend_runtime_config(
        {
            "API_BASE_URL": "/api",
            "FRONTEND_ENVIRONMENT": "prod",
            "FRONTEND_LOCALE_DEFAULT": "en",
        }
    )

    assert config.api_base_url == "/api"
    assert config.environment == "prod"
    assert config.locale_default == "en"


def test_load_frontend_runtime_config_accepts_legacy_backend_api_url_name() -> None:
    config = load_frontend_runtime_config(
        {
            "BACKEND_API_URL": "http://backend:8000",
            "FRONTEND_ENVIRONMENT": "dev",
            "FRONTEND_LOCALE_DEFAULT": "en",
        }
    )

    assert config.api_base_url == "http://backend:8000"


def test_load_frontend_runtime_config_prefers_chatbi_specific_env_names() -> None:
    config = load_frontend_runtime_config(
        {
            "CHATBI_FRONTEND_API_BASE_URL": "https://api.chatbi.example.com",
            "API_BASE_URL": "/api",
            "CHATBI_FRONTEND_ENVIRONMENT": "staging",
            "FRONTEND_ENVIRONMENT": "dev",
            "CHATBI_FRONTEND_LOCALE_DEFAULT": "zh-CN",
            "FRONTEND_LOCALE_DEFAULT": "en",
        }
    )

    assert config.api_base_url == "https://api.chatbi.example.com"
    assert config.environment == "staging"
    assert config.locale_default == "zh-CN"


def test_load_frontend_runtime_config_rejects_backend_env_urls() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        load_frontend_runtime_config(
            {
                "API_BASE_URL": "/api",
                "FRONTEND_ENVIRONMENT": "dev",
                "FRONTEND_LOCALE_DEFAULT": "en",
                "DATABASE_URL": "postgresql://chatbi:test@db:5432/chatbi",
            }
        )


def test_frontend_runtime_config_script_exposes_only_public_browser_config() -> None:
    config = parse_frontend_runtime_config(
        {
            "api_base_url": "/api",
            "environment": "prod",
            "locale_default": "en",
        }
    )

    script = frontend_runtime_config_script(config)

    assert script == (
        'window.__CHATBI_RUNTIME_CONFIG__={"api_base_url":"/api",'
        '"environment":"prod","locale_default":"en"};'
    )
    assert "DATABASE_URL" not in script
    assert "REDIS_URL" not in script
    assert "VECTOR_STORE_URL" not in script
