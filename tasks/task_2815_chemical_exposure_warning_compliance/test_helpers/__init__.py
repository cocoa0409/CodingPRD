"""Test infrastructure for the chemical exposure warning compliance API.

Importing this package registers the error identifier → HTTP status mapping with
the framework's validators, so ``validate_error(response, ERR_X)`` cross-checks
the status code without any test restating it.
"""

from . import api_errors  # noqa: F401  (import side effect: status map registration)
from .api_client import ChemicalComplianceApiClient

__all__ = ["ChemicalComplianceApiClient", "api_errors"]
