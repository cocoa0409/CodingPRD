"""Test infrastructure for the Affiliate Program Management API PRD suite.

Stage 1 helpers: constants and the error catalogue of §5, typed resource
shapes, one client method per §4 route, envelope and money assertions,
request-payload factories, caller identities, and composite setup helpers.
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import AffiliateProgramApiClient, canonical_instant  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
