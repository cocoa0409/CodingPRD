"""Error catalogue (PRD section 5) and the exception used to abort a request."""
from __future__ import annotations

# error_id -> (http_status, default human readable message)
ERROR_CATALOGUE = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or malformed"),
    "ERR_UNAUTHORIZED": (403, "Role is not permitted to perform this operation"),
    "ERR_OWNERSHIP_VIOLATION": (403, "Household may only act on its own lease"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The requesting user may not also decide this item"),
    "ERR_COMMUNITY_NOT_FOUND": (404, "Community not found"),
    "ERR_PHASE_NOT_FOUND": (404, "Phase not found"),
    "ERR_HOMESITE_NOT_FOUND": (404, "Homesite not found"),
    "ERR_RENT_SCHEDULE_NOT_FOUND": (404, "Market rent schedule not found"),
    "ERR_CONCESSION_PROGRAM_NOT_FOUND": (404, "Concession program not found"),
    "ERR_HOUSEHOLD_NOT_FOUND": (404, "Household not found"),
    "ERR_LEASE_NOT_FOUND": (404, "Lease not found"),
    "ERR_TURN_WORK_ORDER_NOT_FOUND": (404, "Turn work order not found"),
    "ERR_ABSORPTION_REVIEW_NOT_FOUND": (404, "Absorption review not found"),
    "ERR_INVALID_REQUEST": (400, "Request body failed schema validation"),
    "ERR_STALE_COMMUNITY_VERSION": (
        412, "expected_community_version does not match the community's current version"),
    "ERR_INVALID_PLAT_STATE": (409, "Plat is not in a state that allows this operation"),
    "ERR_INVALID_PHASE_STATE": (409, "Phase is not in a state that allows this operation"),
    "ERR_INVALID_HOMESITE_STATE": (409, "Homesite is not in a state that allows this operation"),
    "ERR_INVALID_LEASE_STATE": (409, "Lease is not in a state that allows this operation"),
    "ERR_INVALID_CONCESSION_STATE": (409, "Concession is not in a state that allows this operation"),
    "ERR_INVALID_TURN_STATE": (409, "Turn work order is not in a state that allows this operation"),
    "ERR_INVALID_LIFECYCLE_STATE": (409, "Community lifecycle does not allow this operation"),
    "ERR_INVALID_FACILITY_STATE": (409, "Financing facility is not in a state that allows this operation"),
    "ERR_INVALID_MANAGEMENT_STATE": (409, "Management mode does not allow this operation"),
    "ERR_SCHEDULE_ALREADY_SUPERSEDED": (409, "Market rent schedule has already been superseded"),
    "ERR_COMMUNITY_POSTURE_FROZEN": (
        409, "Community posture is FROZEN; leasing and inventory operations are blocked"),
    "ERR_COMMUNITY_POSTURE_RESTRICTED": (
        409, "Community posture is RESTRICTED; this operation requires an OPEN posture"),
    "ERR_HOMESITE_NOT_LEASABLE": (409, "Homesite is not available for leasing"),
    "ERR_CONCESSION_PROGRAM_NOT_ACTIVE": (409, "Concession program is not active"),
    "ERR_HOMESITE_NOT_IN_TURN": (409, "Homesite is not on notice or in turn"),
    "ERR_OCCUPANCY_CERTIFICATE_REQUIRED": (409, "Homesite has no certificate of occupancy"),
    "ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED": (
        409, "Plat approval requires the single-ownership covenant"),
    "ERR_MAINTENANCE_STAFFING_REQUIRED": (
        409, "Community has no maintenance technicians assigned"),
    "ERR_LEASE_UP_THRESHOLD_NOT_MET": (
        409, "Community has not reached the lease-up threshold for a management transition"),
    "ERR_PLAT_REVISION_LIMIT": (409, "Plat revision limit reached"),
    "ERR_DUPLICATE_RESOURCE": (409, "A resource with this natural key already exists"),
    "ERR_HOUSEHOLD_ALREADY_LEASED": (409, "Household already holds an open lease"),
    "ERR_PRODUCT_MIX_EXCEEDED": (
        409, "Homesite exceeds the community's planned product mix or the phase unit count"),
    "ERR_INVALID_PHASE_PREDECESSOR": (409, "Phase predecessor is invalid"),
    "ERR_TURN_WINDOW_OVERLAP": (409, "Turn window overlaps an existing work order on this homesite"),
    "ERR_PHASE_CONCURRENCY_LIMIT": (
        409, "Phase cannot start: predecessor incomplete or concurrency cap reached"),
    "ERR_INVALID_TURN_WINDOW": (409, "Turn window is not a valid whole-hour future window"),
    "ERR_TURN_REWORK_BUFFER": (409, "Turn window violates the 48-hour same-scope rework buffer"),
    "ERR_PHASE_GAP_VIOLATION": (
        409, "Same-kind phase windows are closer than the 48-hour minimum gap"),
    "ERR_INVALID_REVIEW_WINDOW": (409, "Absorption review window is invalid"),
    "ERR_CLOCK_REWIND": (409, "The logical clock may only move forward"),
    "ERR_TURN_CAPACITY_EXCEEDED": (
        409, "Turn work exceeds the community's maintenance technician capacity"),
    "ERR_NO_PUBLISHED_RENT_SCHEDULE": (
        409, "No published market rent schedule is effective for this product type"),
    "ERR_PRODUCT_TYPE_NOT_ELIGIBLE": (
        409, "Homesite product type is not eligible for this concession program"),
    "ERR_CONCESSION_PERIOD_OUT_OF_ORDER": (
        409, "Concession credit period is out of order or beyond the schedule"),
    "ERR_CONCESSION_BUDGET_EXCEEDED": (
        409, "Approving this concession would exceed the community concession budget"),
    "ERR_INCOME_QUALIFICATION_FAILED": (
        409, "Household income does not meet the 3x gross monthly charge requirement"),
    "ERR_LTV_COVENANT_BREACH": (409, "Operation would breach the 6500 bps loan-to-value covenant"),
}


class ApiError(Exception):
    """Raised anywhere in a request to abort it with a catalogued error identifier."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOGUE[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
