"""Test helpers for the Cement Plant & Kiln Operations API.

Importing this package registers the PRD's error-id to HTTP-status map with the
framework validators, so ``validate_error`` cross-checks the status code as well
as the error id even when a test does not spell the status out.
"""

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

__all__ = ["ApiClient", "api_client", "ApiErrorId", "HTTP_STATUS_CODES"]
