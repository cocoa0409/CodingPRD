"""Suite-wide pytest configuration.

The harness restarts the API server before every individual test, so the
database is empty at the start of each test and every fixture below is function
scoped.  Fixtures are defined once in ``test_helpers.fixtures`` and re-exported
here so pytest collects them for every module in this directory.
"""

from test_helpers.fixtures import (  # noqa: F401
    adult_guest,
    adult_rider,
    client,
    horse,
    in_season,
    open_season,
    planning_season,
    ready_cabin,
    ride_scenario,
)

__all__ = [
    "adult_guest",
    "adult_rider",
    "client",
    "horse",
    "in_season",
    "open_season",
    "planning_season",
    "ready_cabin",
    "ride_scenario",
]
