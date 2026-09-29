"""Shared pytest configuration for the Self-Order Kiosk Content Ops API suite.

The fixtures themselves live in test_helpers/fixtures.py; importing them here
makes `api`, `world` and `baseline` available to every test module.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import api, baseline, world  # noqa: E402,F401
