"""Composite setup helpers — barrel over the two fixture modules.

fixtures_core: logical clock, master data, campaign and seed-train chains.
fixtures_batch: batch processing, testing, disposition, deviations, shipments.

Tests import from test_helpers (or test_helpers.fixtures) and see both.
"""
from .fixtures_core import *  # noqa: F401,F403
from .fixtures_batch import *  # noqa: F401,F403
