"""Shared pytest configuration for the compliance suite.

The composite fixtures live in ``test_helpers.fixtures`` and are re-exported
here so that every test module can request them by name.  Registering the
error-identifier to HTTP-status map at import time lets ``validate_error``
cross-check the status of every rejection without each test naming it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_errors import register_error_status_map  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402,F401
    academy_complete_recruit,
    academy_recruit,
    active_rotation,
    certified_fto,
    certified_instructor,
    client,
    clock_epoch,
    cohort,
    curriculum,
    field_training_recruit,
    instructor,
    probation_recruit,
    recruit,
    standard,
    world,
)

register_error_status_map()
