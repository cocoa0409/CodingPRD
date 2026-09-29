"""Shared pytest configuration for the audio post-production compliance suite."""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers import api_errors  # noqa: E402,F401  (registers the error status map)
from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    delivered_environment,
    locked_project,
    open_project,
    prepared_environment,
    qc_passed_environment,
    standard_stage,
    theatrical_mixer,
    theatrical_spec,
    union_talent,
    world,
)
