"""Shared pytest configuration for the Interlibrary Loan API test suite."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    accountant_headers,
    acq_headers,
    admin_headers,
    client,
    staff_headers,
)
