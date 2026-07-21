from datetime import datetime

import pytest

from app.collector import CollectorResult, completed_candle_boundary, run_collector_loop
from app.config import Settings


def test_boundary_requires_timezone():
    with pytest.raises(ValueError, match="timezone"):
        completed_candle_boundary(datetime(2026, 7, 20, 12, 7))


def test_continuous_loop_collects_immediately_before_waiting():
    events: list[tuple[str, object]] = []
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://example:example@localhost/example",
        collector_interval_seconds=60,
    )

    def fake_collect(received: Settings) -> CollectorResult:
        events.append(("collect", received))
        return CollectorResult(True, 4, 12, ())

    def fake_report(result: CollectorResult) -> None:
        events.append(("report", result))

    def fake_wait(seconds: float) -> None:
        events.append(("wait", seconds))
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_collector_loop(
            settings,
            collect=fake_collect,
            wait=fake_wait,
            report=fake_report,
        )

    assert [event[0] for event in events] == ["collect", "report", "wait"]
    assert events[-1] == ("wait", 60)
