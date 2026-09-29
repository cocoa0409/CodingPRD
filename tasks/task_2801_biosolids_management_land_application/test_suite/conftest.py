"""Shared pytest configuration for the Biosolids Management API test suite."""

import os
import sys

# The helper package lives beside test_suite/ at the task root.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import api_errors  # noqa: E402,F401  (registers error -> status map)
from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    base_world,
    build,
    cadmium_limit,
    dewatered_batch,
    diversion_world,
    draft_site,
    facility,
    permitted_site,
    qualified_batch,
    tight_cplr_world,
)
