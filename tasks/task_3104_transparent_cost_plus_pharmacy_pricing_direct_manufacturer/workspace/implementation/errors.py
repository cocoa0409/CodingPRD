"""Error catalogue, exception type and the response envelopes.

Every error id below is verbatim from PRD §5 / SCAFFOLD §1.6, together with
its HTTP status. Envelope field names are verbatim from PRD §2.2.
"""

import uuid

from clock import now_iso


class ApiError(Exception):
    """Carries the error id, human message and HTTP status of a refusal."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# error_id -> (http status, default human-readable message)
ERROR_CATALOG = {
    "ERR_MISSING_ROLE_HEADER": (
        401,
        "The X-User-Role header is absent or is not one of the declared roles.",
    ),
    "ERR_ROLE_NOT_PERMITTED": (
        403,
        "The caller's role is not permitted to perform this operation.",
    ),
    "ERR_PATIENT_OWNERSHIP_REQUIRED": (
        403,
        "The addressed resource does not belong to the calling patient.",
    ),
    "ERR_RESOURCE_NOT_FOUND": (
        404,
        "An identifier in the request path does not resolve to a resource.",
    ),
    "ERR_INVALID_STATE": (
        409,
        "The resource is not in a state that admits the requested transition.",
    ),
    "ERR_STALE_VERSION": (
        412,
        "expected_order_version does not match the order's current version.",
    ),
    "ERR_CONTROLLED_SUBSTANCE_EXCLUDED": (
        422,
        "The drug is a controlled substance and is excluded from the pipeline.",
    ),
    "ERR_NOT_LICENSED_IN_STATE": (
        422,
        "No ACTIVE licence covers the destination state for the selected pharmacy.",
    ),
    "ERR_REQUEST_NOT_ACCEPTED": (
        422,
        "The referenced intake request is not ACCEPTED.",
    ),
    "ERR_REQUEST_CAPACITY_EXCEEDED": (
        422,
        "The requested quantity exceeds the available capacity or supply.",
    ),
    "ERR_SHIP_INTERVAL_NOT_ELAPSED": (
        422,
        "The shipment interval has not yet elapsed for this order.",
    ),
    "ERR_LICENSE_CONFLICT": (
        409,
        "A conflicting ACTIVE licence already exists for this pharmacy and state.",
    ),
    "ERR_PRICE_INVARIANT_BROKEN": (
        422,
        "The order's price decomposition violates the fiscal invariant.",
    ),
    "ERR_COMPARISON_UNSUBSTANTIATED": (
        422,
        "The comparison message is withheld because it is unsubstantiated or blocked.",
    ),
    "ERR_SHIP_SLOT_CONFLICT": (
        409,
        "The drug's carrier slot for the dispatch day and its quarantine buffer is full.",
    ),
    "ERR_SOURCE_PRICE_DRUG_MISMATCH": (
        422,
        "The source price row does not cover the prescription's drug.",
    ),
    "ERR_PRESCRIBER_ORDER_REQUIRED": (
        422,
        "Intake requires a prescription with a prescriber and drug reference and an ACTIVE prescriber.",
    ),
    "ERR_SUBSTITUTION_REASON_REQUIRED": (
        422,
        "A stated reason code is mandatory for a drug substitution.",
    ),
    "ERR_CANCELLATION_REASON_REQUIRED": (
        422,
        "A stated reason code is mandatory for an order cancellation.",
    ),
    "ERR_SUBSTANTIATION_ORDER_MISMATCH": (
        422,
        "The substantiation record does not belong to the order in the path.",
    ),
    "ERR_SUBSTANTIATION_EXPIRED": (
        422,
        "The substantiation's valid_until is not strictly after the logical clock.",
    ),
    "ERR_FORMULARY_GATE_FAILED": (
        422,
        "The demand-versus-supply gate for formulary admission did not pass.",
    ),
    "ERR_SOURCING_UNAVAILABLE": (
        422,
        "The drug's sourcing_status is not SOURCED.",
    ),
    "ERR_SUPPLY_SHORTFALL": (
        422,
        "The drug's supply_units are below the requested quantity.",
    ),
    "ERR_DRUG_DELISTED": (
        422,
        "The drug is DELISTED.",
    ),
    "ERR_INVALID_AMOUNT": (
        400,
        "A numeric input violates its declared lower bound.",
    ),
}


def fail(error_id, message=None):
    """Raise the catalogue error, optionally with a more specific message."""
    status, default_message = ERROR_CATALOG[error_id]
    raise ApiError(error_id, message or default_message, status)


def new_request_id():
    return "req_" + uuid.uuid4().hex[:16].upper()


def meta_object(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_payload(data, response_type, pagination=None):
    """PRD §2.2 standard success envelope."""
    from resources import prune

    return {
        "meta": meta_object(pagination),
        "response_type": response_type,
        "data": prune(data),
    }


def error_payload(error_id, message):
    """PRD §2.2 standard error envelope; meta carries only the two fields."""
    return {
        "meta": meta_object(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }