"""Pytest wiring for the SafeSport compliance suite.

The helper package sits beside this directory, so it is put on the path before
its fixtures are re-exported.  Every fixture the tests use is defined in
``test_helpers.fixtures``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    club,
    course,
    eligible_member,
    investigating_body,
    member,
    other_club,
)
