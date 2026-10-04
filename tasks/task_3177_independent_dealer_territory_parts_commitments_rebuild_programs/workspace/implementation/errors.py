"""Error catalogue: identifiers, HTTP statuses and the exception type."""

from __future__ import annotations

# id -> (http status, default message)
ERROR_CATALOG = {
    "ERR_INVALID_REQUEST": (400, "The request body does not parse into the declared shape."),
    "ERR_UNAUTHENTICATED": (401, "Missing or unrecognised caller credentials."),
    "ERR_UNAUTHORIZED": (403, "The acting role is not permitted for this operation."),
    "ERR_DEALER_SCOPE_MISMATCH": (403, "The acting party's dealer scope does not cover this resource."),
    "ERR_DEALER_NOT_FOUND": (404, "No dealer exists for the supplied identifier."),
    "ERR_AGREEMENT_NOT_FOUND": (404, "No dealer agreement exists for the supplied identifier."),
    "ERR_COMMITMENT_NOT_FOUND": (404, "No parts commitment exists for the supplied identifier."),
    "ERR_CLAIM_NOT_FOUND": (404, "No rebuild claim exists for the supplied identifier."),
    "ERR_REVIEW_NOT_FOUND": (404, "No performance review exists for the supplied identifier."),
    "ERR_POPULATION_NOT_FOUND": (404, "No machine population record exists for the supplied identifier."),
    "ERR_INVALID_STATE": (409, "The target resource is not in a state that admits the requested transition."),
    "ERR_STALE_VERSION": (412, "The supplied expected version no longer matches the parent's current version."),
    "ERR_TERRITORY_OVERLAP": (409, "An exclusive representation interval overlaps, or the planned share sits above 100."),
    "ERR_AGREEMENT_EXCLUSIVITY_MISMATCH": (409, "The exclusive agreement's territory does not match its dealer's territory."),
    "ERR_TOOLING_INCOMPLETE": (409, "The agreement's tooling compliance or technician head-count is short of the minimum."),
    "ERR_STOCKING_MANDATE_HARD_CAP": (409, "The stocking mandate's hard cap would be passed."),
    "ERR_COMMITMENT_EMPTY": (409, "The commitment holds no available units for a non-emergency order."),
    "ERR_COMMITMENT_BATCH_OPEN": (409, "An open or ordered batch of this commitment blocks the operation."),
    "ERR_AGREEMENT_COMMITMENT_OPEN": (409, "The agreement holds a commitment with an open or ordered batch."),
    "ERR_COMMITMENT_PERFORMANCE_DEFICIENT": (409, "The commitment is performance deficient so its core return cannot be accepted."),
    "ERR_CREDIT_ALREADY_APPLIED": (409, "The commitment already holds a core credit balance."),
    "ERR_REBUILD_SPEC_EXCEEDED": (422, "The certified rebuild specification limit would be exceeded."),
    "ERR_REBUILD_CORE_UNRETURNED": (409, "The rebuild claim's core has not been returned under the certified return terms."),
    "ERR_NO_RESTRICTION_PRIORITY": (409, "The dealer holds no performance-deficient commitment to carry the repair priority."),
    "ERR_PARTY_SUPERSEDED": (409, "A superseded party registration blocks the requested decline."),
    "ERR_MACHINE_NOT_IN_POPULATION": (409, "The machine serial is not live in the dealer's active population."),
    "ERR_MACHINE_ALREADY_REGISTERED": (409, "The machine serial is already registered outside this dealer's records."),
    "ERR_MACHINE_POPULATION_RETIRED": (409, "The machine serial is carried by a retired population record."),
    "ERR_MACHINE_REMARKETED": (409, "The machine serial has been remarketed and cannot be reinstated."),
    "ERR_TRADE_IN_APPRAISAL_EXCEEDS_PRICE": (409, "The attached trade-in's appraised value reaches the list price."),
    "ERR_TRADE_IN_NOT_ACCEPTED": (409, "The trade-in the operation needs is not in status ACCEPTED."),
    "ERR_NO_ACTIVE_AGREEMENT": (409, "The dealer holds no active agreement for the machine's product family."),
    "ERR_DEALER_TERMINATED": (409, "The dealer or agreement is terminated and admits no further operation."),
    "ERR_REVIEW_OUTSTANDING": (409, "A performance review of the agreement is not evaluated."),
    "ERR_REVIEW_AWAITING_CIRCUMSTANCE": (409, "A performance review of the agreement awaits circumstances."),
    "ERR_SLA_AUDIT_PENDING": (409, "An SLA audit service order referencing the machine serial is open or in progress."),
    "ERR_RESTRICTION_ALREADY_FULL_STOP": (409, "The restriction order is already at FULL_STOP."),
    "ERR_RESTRICTION_ALREADY_MINIMAL": (409, "The restriction order is already at HOURS_SPENT."),
    "ERR_DUPLICATE_SERIAL": (409, "The machine serial is already held by another order or population record."),
    "ERR_STOCKING_MANDATE_UNMET": (409, "The commitment's final stocking variant is below one unit."),
    "ERR_EXECUTION_EPOCH_CONFLICT": (409, "The batch receipt collides with a deferred re-evaluation in the same epoch."),
}


class ApiError(Exception):
    """Carries the machine-readable error id, message and HTTP status."""

    def __init__(self, error_id: str, message: str | None = None, http_status: int | None = None):
        if error_id not in ERROR_CATALOG:
            raise KeyError("unknown error id: %s" % error_id)
        status, default_message = ERROR_CATALOG[error_id]
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = http_status or status
        super().__init__(self.message)


# Convenience aliases so route modules read clearly.
E_INVALID_REQUEST = "ERR_INVALID_REQUEST"
E_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
E_UNAUTHORIZED = "ERR_UNAUTHORIZED"
E_DEALER_SCOPE_MISMATCH = "ERR_DEALER_SCOPE_MISMATCH"
E_DEALER_NOT_FOUND = "ERR_DEALER_NOT_FOUND"
E_AGREEMENT_NOT_FOUND = "ERR_AGREEMENT_NOT_FOUND"
E_COMMITMENT_NOT_FOUND = "ERR_COMMITMENT_NOT_FOUND"
E_CLAIM_NOT_FOUND = "ERR_CLAIM_NOT_FOUND"
E_REVIEW_NOT_FOUND = "ERR_REVIEW_NOT_FOUND"
E_POPULATION_NOT_FOUND = "ERR_POPULATION_NOT_FOUND"
E_INVALID_STATE = "ERR_INVALID_STATE"
E_STALE_VERSION = "ERR_STALE_VERSION"
E_TERRITORY_OVERLAP = "ERR_TERRITORY_OVERLAP"
E_EXCLUSIVITY_MISMATCH = "ERR_AGREEMENT_EXCLUSIVITY_MISMATCH"
E_TOOLING_INCOMPLETE = "ERR_TOOLING_INCOMPLETE"
E_HARD_CAP = "ERR_STOCKING_MANDATE_HARD_CAP"
E_COMMITMENT_EMPTY = "ERR_COMMITMENT_EMPTY"
E_COMMITMENT_BATCH_OPEN = "ERR_COMMITMENT_BATCH_OPEN"
E_AGREEMENT_COMMITMENT_OPEN = "ERR_AGREEMENT_COMMITMENT_OPEN"
E_COMMITMENT_PERF_DEF = "ERR_COMMITMENT_PERFORMANCE_DEFICIENT"
E_CREDIT_ALREADY_APPLIED = "ERR_CREDIT_ALREADY_APPLIED"
E_REBUILD_SPEC_EXCEEDED = "ERR_REBUILD_SPEC_EXCEEDED"
E_REBUILD_CORE_UNRETURNED = "ERR_REBUILD_CORE_UNRETURNED"
E_NO_RESTRICTION_PRIORITY = "ERR_NO_RESTRICTION_PRIORITY"
E_PARTY_SUPERSEDED = "ERR_PARTY_SUPERSEDED"
E_MACHINE_NOT_IN_POPULATION = "ERR_MACHINE_NOT_IN_POPULATION"
E_MACHINE_ALREADY_REGISTERED = "ERR_MACHINE_ALREADY_REGISTERED"
E_MACHINE_POPULATION_RETIRED = "ERR_MACHINE_POPULATION_RETIRED"
E_MACHINE_REMARKETED = "ERR_MACHINE_REMARKETED"
E_TRADE_IN_APPRAISAL = "ERR_TRADE_IN_APPRAISAL_EXCEEDS_PRICE"
E_TRADE_IN_NOT_ACCEPTED = "ERR_TRADE_IN_NOT_ACCEPTED"
E_NO_ACTIVE_AGREEMENT = "ERR_NO_ACTIVE_AGREEMENT"
E_DEALER_TERMINATED = "ERR_DEALER_TERMINATED"
E_REVIEW_OUTSTANDING = "ERR_REVIEW_OUTSTANDING"
E_REVIEW_AWAITING_CIRCUMSTANCE = "ERR_REVIEW_AWAITING_CIRCUMSTANCE"
E_SLA_AUDIT_PENDING = "ERR_SLA_AUDIT_PENDING"
E_RESTRICTION_FULL_STOP = "ERR_RESTRICTION_ALREADY_FULL_STOP"
E_RESTRICTION_MINIMAL = "ERR_RESTRICTION_ALREADY_MINIMAL"
E_DUPLICATE_SERIAL = "ERR_DUPLICATE_SERIAL"
E_STOCKING_MANDATE_UNMET = "ERR_STOCKING_MANDATE_UNMET"
E_EPOCH_CONFLICT = "ERR_EXECUTION_EPOCH_CONFLICT"