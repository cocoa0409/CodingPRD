"""Shared pytest configuration for the compliance API test suite.

Importing ``test_helpers.api_errors`` registers the error identifier → HTTP
status mapping, so ``validate_error(response, ERR_X)`` cross-checks the status
code the PRD's catalogue pins for that identifier.  Re-exporting the fixture
module makes every composite fixture visible to every test file.
"""

import test_helpers.api_errors  # noqa: F401  (registers the status map)
from test_helpers.fixtures import *  # noqa: F401,F403
