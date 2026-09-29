"""Pytest wiring for the Venue Event-Day Staffing & Guest Services suite.

The runner puts the parent of this directory on PYTHONPATH, so the shared
infrastructure package is importable as ``test_helpers``.  Importing the
``client`` fixture here makes it available to every test module.
"""

from test_helpers.fixtures import client  # noqa: F401
