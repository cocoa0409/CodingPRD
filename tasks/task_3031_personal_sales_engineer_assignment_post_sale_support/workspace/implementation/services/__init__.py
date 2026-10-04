"""Business logic: calculations and shared derived-state maintenance.

Import order matters here: ``core`` builds on ``calc``, and the route modules
build on both.
"""

from services import calc, core  # noqa: F401