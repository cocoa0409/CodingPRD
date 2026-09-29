"""Shared pytest configuration for the Emerging Contaminant Compliance suite.

The fixtures live in `test_helpers.fixtures`; importing them here makes them
visible to every test module in this directory.
"""

from test_helpers.fixtures import api, entry_point, registry  # noqa: F401

__all__ = ["api", "entry_point", "registry"]
