"""Error identifiers, HTTP statuses and the API exception type."""

# --- Authentication / authorization -----------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

# --- Request shape -----------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"

# --- Business safety ---------------------------------------------------------
ERR_HAZMAT_CAP_EXCEEDED = "ERR_HAZMAT_CAP_EXCEEDED"
ERR_POSTURE_BLOCKS_INDUCTION = "ERR_POSTURE_BLOCKS_INDUCTION"

# --- Business temporal -------------------------------------------------------
ERR_LANE_CERTIFICATION_LAPSED = "ERR_LANE_CERTIFICATION_LAPSED"

# --- Business constraints ----------------------------------------------------
ERR_LANE_NOT_AVAILABLE = "ERR_LANE_NOT_AVAILABLE"
ERR_LANE_CAPACITY_EXCEEDED = "ERR_LANE_CAPACITY_EXCEEDED"
ERR_BUILDUP_UNDER_CAPACITY = "ERR_BUILDUP_UNDER_CAPACITY"

# --- Fiscal capacity ---------------------------------------------------------
ERR_LOAD_WEIGHT_EXCEEDED = "ERR_LOAD_WEIGHT_EXCEEDED"
ERR_FEEDER_OVER_CAPACITY = "ERR_FEEDER_OVER_CAPACITY"
ERR_FEEDER_WINDOW_CONFLICT = "ERR_FEEDER_WINDOW_CONFLICT"

# --- State admissibility -----------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_UNLOAD_FACE_OCCUPIED = "ERR_UNLOAD_FACE_OCCUPIED"
ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE = "ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE"
ERR_NO_ALTERNATE_HUB = "ERR_NO_ALTERNATE_HUB"
ERR_CONTINGENCY_NOT_DECLARED = "ERR_CONTINGENCY_NOT_DECLARED"
ERR_HUB_NOT_LOCKED = "ERR_HUB_NOT_LOCKED"
ERR_CLOCK_OUT_OF_ORDER = "ERR_CLOCK_OUT_OF_ORDER"
ERR_DUPLICATE_LIVE_PACKAGE = "ERR_DUPLICATE_LIVE_PACKAGE"
ERR_ACK_MISMATCH = "ERR_ACK_MISMATCH"
ERR_BANK_NOT_UNLOADING = "ERR_BANK_NOT_UNLOADING"
ERR_HYDRAULIC_CREW_UNAVAILABLE = "ERR_HYDRAULIC_CREW_UNAVAILABLE"
ERR_LATE_UNLOAD_REGRESSION = "ERR_LATE_UNLOAD_REGRESSION"
ERR_SORT_STAGE_BUDGET_EXCEEDED = "ERR_SORT_STAGE_BUDGET_EXCEEDED"
ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED = "ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED"
ERR_CUTOFF_NOT_REACHED = "ERR_CUTOFF_NOT_REACHED"
ERR_COMMITMENT_GRACE_EXCEEDED = "ERR_COMMITMENT_GRACE_EXCEEDED"
ERR_AIRCRAFT_NOT_CANCELLED = "ERR_AIRCRAFT_NOT_CANCELLED"
ERR_SORT_PENDING = "ERR_SORT_PENDING"
ERR_FINALIZED_FAILURE_PRESENT = "ERR_FINALIZED_FAILURE_PRESENT"
ERR_REOPEN_POSTURE_BLOCKED = "ERR_REOPEN_POSTURE_BLOCKED"

# --- Optimistic concurrency --------------------------------------------------
ERR_STALE_VERSION = "ERR_STALE_VERSION"

HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_INVALID_REQUEST: 400,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_HAZMAT_CAP_EXCEEDED: 409,
    ERR_POSTURE_BLOCKS_INDUCTION: 409,
    ERR_LANE_CERTIFICATION_LAPSED: 409,
    ERR_LANE_NOT_AVAILABLE: 409,
    ERR_LANE_CAPACITY_EXCEEDED: 409,
    ERR_BUILDUP_UNDER_CAPACITY: 409,
    ERR_LOAD_WEIGHT_EXCEEDED: 409,
    ERR_FEEDER_OVER_CAPACITY: 409,
    ERR_FEEDER_WINDOW_CONFLICT: 409,
    ERR_INVALID_STATE: 409,
    ERR_UNLOAD_FACE_OCCUPIED: 409,
    ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE: 409,
    ERR_NO_ALTERNATE_HUB: 409,
    ERR_CONTINGENCY_NOT_DECLARED: 409,
    ERR_HUB_NOT_LOCKED: 409,
    ERR_CLOCK_OUT_OF_ORDER: 409,
    ERR_DUPLICATE_LIVE_PACKAGE: 409,
    ERR_ACK_MISMATCH: 409,
    ERR_BANK_NOT_UNLOADING: 409,
    ERR_HYDRAULIC_CREW_UNAVAILABLE: 409,
    ERR_LATE_UNLOAD_REGRESSION: 409,
    ERR_SORT_STAGE_BUDGET_EXCEEDED: 409,
    ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED: 409,
    ERR_CUTOFF_NOT_REACHED: 409,
    ERR_COMMITMENT_GRACE_EXCEEDED: 409,
    ERR_AIRCRAFT_NOT_CANCELLED: 409,
    ERR_SORT_PENDING: 409,
    ERR_FINALIZED_FAILURE_PRESENT: 409,
    ERR_REOPEN_POSTURE_BLOCKED: 409,
    ERR_STALE_VERSION: 412,
}

MESSAGES = {
    ERR_UNAUTHENTICATED: "The request carries no valid X-User-Role header.",
    ERR_UNAUTHORIZED: "The acting role is not permitted on this endpoint.",
    ERR_INVALID_REQUEST: "The request body is malformed or incomplete.",
    ERR_RESOURCE_NOT_FOUND: "The referenced resource does not exist.",
    ERR_HAZMAT_CAP_EXCEEDED: "Onboarding this hazmat package would breach the buildup hazardous cap.",
    ERR_POSTURE_BLOCKS_INDUCTION: "The hub posture blocks induction, loading, departure or landing.",
    ERR_LANE_CERTIFICATION_LAPSED: "The sort lane certification has lapsed at the current hub minute.",
    ERR_LANE_NOT_AVAILABLE: "The sort lane is not available or not certified for this commodity class.",
    ERR_LANE_CAPACITY_EXCEEDED: "The sort lane hourly capacity would be exceeded.",
    ERR_BUILDUP_UNDER_CAPACITY: "The destination buildup sits inside its breach-tolerance band.",
    ERR_LOAD_WEIGHT_EXCEEDED: "The load move weight floor or the use-it-or-lose-it ceiling is breached.",
    ERR_FEEDER_OVER_CAPACITY: "The feeder staged weight exceeds its departure ceiling.",
    ERR_FEEDER_WINDOW_CONFLICT: "Another feeder already occupies this turnout interval.",
    ERR_INVALID_STATE: "The target resource is not in a state that admits this transition.",
    ERR_UNLOAD_FACE_OCCUPIED: "Another aircraft on this bank already holds the single unload face.",
    ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE: "A carrier-attributed failure is a refund obligation, not a dispute candidate.",
    ERR_NO_ALTERNATE_HUB: "The hub has no alternate hub declared.",
    ERR_CONTINGENCY_NOT_DECLARED: "The requested action requires the opposite contingency state.",
    ERR_HUB_NOT_LOCKED: "A ground stop requires the hub to be in LOCKDOWN.",
    ERR_CLOCK_OUT_OF_ORDER: "The logical clock may not move strictly backwards.",
    ERR_DUPLICATE_LIVE_PACKAGE: "This hub already holds a live package with that tracking number.",
    ERR_ACK_MISMATCH: "The acknowledgement number was replayed against a different payload.",
    ERR_BANK_NOT_UNLOADING: "The arrival bank is not in UNLOADING.",
    ERR_HYDRAULIC_CREW_UNAVAILABLE: "The hydraulic-lift crew is not available for this bank.",
    ERR_LATE_UNLOAD_REGRESSION: "The supplied unload minute precedes the actual arrival.",
    ERR_SORT_STAGE_BUDGET_EXCEEDED: "The secondary stage budget has closed.",
    ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED: "The irregular resolve budget has closed.",
    ERR_CUTOFF_NOT_REACHED: "The package has not yet entered its downgrade lead window.",
    ERR_COMMITMENT_GRACE_EXCEEDED: "The commitment grace window has closed.",
    ERR_AIRCRAFT_NOT_CANCELLED: "The package inbound aircraft is not CANCELLED.",
    ERR_SORT_PENDING: "The package has already been loaded onto a move.",
    ERR_FINALIZED_FAILURE_PRESENT: "The package carries a FINALIZED service failure.",
    ERR_REOPEN_POSTURE_BLOCKED: "A failure may not be reopened while the hub is LOCKDOWN or GROUND_STOP.",
    ERR_STALE_VERSION: "The supplied expected version does not match the current version.",
}


class ApiError(Exception):
    """Carries an error_id, a message and the HTTP status from the catalog."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)