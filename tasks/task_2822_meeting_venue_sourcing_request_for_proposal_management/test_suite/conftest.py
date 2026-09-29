"""Shared pytest configuration for the Meeting Venue Sourcing & RFP API suite.

The harness restarts the API before every individual test, so each test starts
against an empty store and builds all of the state it needs through the
documented endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Let pytest rewrite the assertions inside the shared helper modules so a failing
# domain assertion reports the offending values.
pytest.register_assert_rewrite(
    "test_helpers",
    "test_helpers.assertions",
    "test_helpers.fixtures",
)

# Loading the fixtures module also imports the package, which registers the
# error_id -> HTTP status map used by validate_error(). It exposes the composite
# state fixtures (sourcing_world, issued_round, submitted_bid, evaluated_bid,
# awarded_contract, routed_contract, executed_contract,
# deposit_scheduled_contract, two_venue_round, sourcing_clock) to every module.
pytest_plugins = ["test_helpers.fixtures"]
