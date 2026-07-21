from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_compose_exposes_secrets_only_to_services_that_need_them():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    collector_environment = compose["services"]["collector"]["environment"]
    migration_environment = compose["services"]["migrate"]["environment"]
    web_environment = compose["services"]["web"]["environment"]

    for environment in (collector_environment, migration_environment):
        assert "OPERATOR_PASSWORD" not in environment
        assert "SESSION_SECRET" not in environment

    assert "DISCORD_WEBHOOK_URL" in collector_environment
    assert "DISCORD_WEBHOOK_URL" not in web_environment
    assert "OPERATOR_PASSWORD" in web_environment
    assert "SESSION_SECRET" in web_environment
