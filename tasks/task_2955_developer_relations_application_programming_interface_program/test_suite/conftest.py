"""Shared pytest configuration for the Developer Relations API Program suite.

Every fixture lives in ``test_helpers.fixtures``; this module only makes the task root
importable and re-exports those fixtures so pytest can collect them.
"""
import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.fixtures import *  # noqa: E402,F401,F403
