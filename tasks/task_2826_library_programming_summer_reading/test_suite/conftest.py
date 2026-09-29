"""Shared pytest configuration for the Library Programming API compliance suite.

The harness restarts the API server before each individual test, so every test
here starts from an empty database with the logical clock at its startup value.
The fixtures below are re-exported from the shared test infrastructure so that
pytest can resolve them by name from any test module.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    adult_program,
    api,
    branch,
    cleared_presenter,
    confirmed_program_with_draw,
    confirmed_program_with_executed_contract,
    craft_program,
    east_branch,
    enrolled_participant,
    held_reservation,
    open_minutes_challenge,
    presenter,
    room,
    scheduled_program,
    supply_lot,
    world,
)
