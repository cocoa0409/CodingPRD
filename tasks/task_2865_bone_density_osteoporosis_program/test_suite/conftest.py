"""Shared pytest configuration for the Bone Density & Osteoporosis Program suite.

The server is restarted before every individual test, so each test starts from
an empty database with the logical clock at its default start. All preconditions
are therefore built from scratch through the API's own endpoints.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    accepted_session,
    api,
    booked,
    draft_report,
    finalized_report,
    foundation,
    foundation_with_profile,
    in_progress_session,
    measured_session,
    ordered,
    submitted_session,
    treatment_plan,
    world,
)
