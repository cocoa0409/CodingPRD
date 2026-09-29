"""Shared pytest configuration for the compliance suite.

Re-exporting the fixtures from ``test_helpers.fixtures`` here is what makes them
visible to every test module without each one importing them by name.
"""
from test_helpers.api_errors import HTTP_STATUS_CODES  # noqa: F401  (registers the map)
from test_helpers.fixtures import (  # noqa: F401
    api,
    certified_match,
    closed_season,
    forming_league,
    league,
    officer,
    opened_match,
    sanctioned_league,
)
