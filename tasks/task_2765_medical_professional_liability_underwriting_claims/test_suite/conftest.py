"""Shared pytest configuration for the Medical Professional Liability suite.

The helper package sits beside this directory at the repository root, so it is
placed on the import path before the fixture plugin is loaded.
"""
import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

pytest_plugins = ["test_helpers.fixtures"]
