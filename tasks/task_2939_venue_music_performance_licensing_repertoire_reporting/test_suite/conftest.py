"""
Pytest wiring for the Venue Music Licensing API suite.

Importing ``test_helpers`` here registers the error-id-to-HTTP-status catalogue
with the shared response validators, so every ``validate_error`` call in the
suite also cross-checks the HTTP status the error catalogue assigns.

The server's state is wiped before every test, so no test may rely on data left
behind by another.  Each test builds what it needs through the API's own
endpoints, using the ``given_*`` builders in ``test_helpers.fixtures``.
"""

import pytest

from test_helpers import LicensingApiClient
from test_helpers.constants import CLOCK_START_INSTANT


@pytest.fixture
def api() -> LicensingApiClient:
    """A client pointed at the server under test for this one test."""
    return LicensingApiClient()


@pytest.fixture
def clock_start() -> str:
    """The instant the logical clock reads at server start-up."""
    return CLOCK_START_INSTANT
