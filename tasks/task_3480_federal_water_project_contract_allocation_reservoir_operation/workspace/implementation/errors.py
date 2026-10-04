"""Error type and helpers for the Federal Water Allocation API.

Every error carries an error_id from the scaffold error catalog (SCAFFOLD
section 1.6 / PRD section 5) plus its pinned HTTP status.
"""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


def not_found(entity):
    """404s name the entity type that failed to resolve (PRD section 2.8)."""
    fail("ERR_NOT_FOUND", 404, entity + " not found")


def invalid_request(message):
    fail("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message):
    fail("ERR_INVALID_STATE", 409, message)


def invalid_quantity(message):
    fail("ERR_INVALID_QUANTITY", 400, message)
