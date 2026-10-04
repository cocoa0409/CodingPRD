"""Error classes and error-id constants.

Every error id and HTTP status below is taken verbatim from PRD.md section 5 /
SCAFFOLD.yaml section 1.6.
"""
from constants import ERROR_HTTP


class ApiError(Exception):
    """An API error carrying the scaffold's error_id and HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)
        self.message = message if message is not None else error_id
        super().__init__(self.error_id)


def raise_err(error_id, message=None):
    raise ApiError(error_id, message)