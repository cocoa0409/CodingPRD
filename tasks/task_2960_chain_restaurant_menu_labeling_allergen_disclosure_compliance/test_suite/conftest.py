"""Shared pytest configuration for the Chain Menu Labeling API suite.

The fixtures live in `test_helpers.fixtures`; re-exporting them here is what
makes them visible to every test module in this directory.
"""

from test_helpers.fixtures import (  # noqa: F401
    api,
    certified_brand,
    covered_brand,
    published_scenario,
    registry,
)
