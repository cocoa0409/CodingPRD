"""Pytest bridge exposing the test_helpers infrastructure as fixtures.

The server under test is restarted before every individual test, so each fixture
here builds its own state from scratch through the API's own endpoints.
"""

import pytest  # noqa: F401  (re-exported for the fixture decorators below)

from test_helpers.fixtures import (  # noqa: F401
    active_lease,
    active_ppa,
    api,
    clock,
    draft_ppa,
    homeowner,
    tariff,
)
