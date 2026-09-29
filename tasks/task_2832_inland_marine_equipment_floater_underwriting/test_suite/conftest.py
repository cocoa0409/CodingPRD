"""Shared pytest wiring for the inland marine equipment floater suite.

The harness relaunches the service before every individual test, so each test
starts against an empty database and builds every precondition it needs through
the public API. The base URL is supplied by the runner's environment, so the
client is constructed with no arguments.
"""

from test_helpers.fixtures import (  # noqa: F401
    api,
    bound_file,
    clock_default,
    draft_policy,
    excavator_rate_cell,
    in_force_file,
    installation_file,
    owned_vehicle,
    quoted_file,
    reporting_file,
    rented_leased_file,
    scheduled_file,
    transit_file,
)
