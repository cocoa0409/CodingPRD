"""
Test infrastructure for the Content Marketing Editorial Governance API.

Importing this package registers the error_id -> HTTP status mapping with the
shared response validators, so ``validate_error`` cross-checks statuses
without any per-test wiring.
"""

from . import api_errors  # noqa: F401  (registers the error status mapping)
from .api_client import ApiClient, canonical_instant, instants_equal
from .fixtures import (
    EditorialWorkflow,
    brief_params_for_effort,
    compute_effort_points,
    reserved_hours_for,
)

__all__ = [
    "ApiClient",
    "canonical_instant",
    "instants_equal",
    "EditorialWorkflow",
    "compute_effort_points",
    "reserved_hours_for",
    "brief_params_for_effort",
]
