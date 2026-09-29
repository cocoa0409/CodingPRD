"""Pytest wiring for the Private-Label Brand Development API suite.

The harness restarts the API server against an empty database before every
individual test, so all shared setup lives in function-scoped fixtures that
rebuild their state through the public API.
"""

from test_helpers.fixtures import *  # noqa: F401,F403
