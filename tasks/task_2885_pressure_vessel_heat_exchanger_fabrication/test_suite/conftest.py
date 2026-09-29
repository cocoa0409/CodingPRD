"""Pytest configuration for the Pressure Vessel Fabrication API test suite.

Makes the sibling ``test_helpers`` package importable and pulls in every fixture
it defines, including the session-scoped registration of the PRD §5 error/status
pairing with the framework validators.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    accepted_heat,
    active_certificate,
    admin_headers,
    client,
    data_package_job,
    design_released_job,
    drafted_wps,
    draft_job,
    error_status_registry,
    fabricating_job,
    heat_exchanger_job,
    nde_hold_job,
    qualified_wps,
    quarantined_heat,
    shop,
    signed_report_job,
    testing_job,
    welded_job,
)
