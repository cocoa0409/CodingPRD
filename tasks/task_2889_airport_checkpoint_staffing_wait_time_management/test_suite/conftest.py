"""Pytest configuration for the Airport Checkpoint Staffing API suite.

The server lifecycle, the base URL and result collection are owned by the
runner; this module only makes the shared helper fixtures visible to every test
file in the suite.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    acknowledged_ticket,
    activated_plan,
    api,
    approved_plan,
    base,
    checked_in_assignment,
    closed_lane_floor,
    draft_plan_floor,
    forecast_floor,
    open_lane_floor,
    plan_with_assignment,
    raised_ticket,
    scenario,
    staffed_floor,
    submitted_plan,
    supervised_floor,
)
