from __future__ import annotations

from unittest.mock import patch

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "task_persistence: run with real PostgreSQL task/report persistence enabled",
    )


@pytest.fixture(autouse=True)
def disable_task_persistence_by_default(request):
    """Most tests should stay isolated from long-lived DB persistence."""
    if request.node.get_closest_marker("task_persistence"):
        yield
        return

    with (
        patch("src.api.routes.tasks.upsert_task_snapshot", return_value=False),
        patch("src.api.routes.tasks.save_task_report", return_value=None),
        patch("src.api.routes.tasks.list_task_snapshots", return_value=[]),
        patch("src.api.routes.tasks.load_task_snapshot", return_value=None),
        patch("src.api.routes.tasks.load_task_report", return_value=None),
    ):
        yield
