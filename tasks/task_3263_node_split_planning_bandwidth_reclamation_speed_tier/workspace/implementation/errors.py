"""Error types and catalog for the node-split benchmark implementation."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> (http status, default message)
ERR = {
    "ERR_MISSING_AUTH_CONTEXT": (400, "X-User-ID or X-User-Role header missing"),
    "ERR_FORBIDDEN_ROLE": (403, "Caller role is not in the endpoint's declared roles"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_VALIDATION": (400, "Malformed body, missing required field, or illegal enum value"),
    "ERR_STALE_VERSION": (412, "Expected version does not match the current version"),
    "ERR_INVALID_STATE": (409, "Resource lifecycle state does not permit this transition"),
    "ERR_SG_CONGESTED": (409, "Service group posture is CRITICAL; new provisioning requests are blocked"),
    "ERR_TIER_RETIRED": (409, "Speed tier is RETIRED"),
    "ERR_NODE_RETIRED": (409, "Optical node is SPLIT_RETIRED"),
    "ERR_WINDOW_CONFLICT": (409, "Construction window conflicts with another window or a blackout"),
    "ERR_WAVE_GAP_VIOLATION": (409, "Migration wave window violates the >= 7-day gap rule"),
    "ERR_PERMIT_NOT_GRANTED": (409, "Node-split project permit is not GRANTED"),
    "ERR_CAMPAIGN_NOT_LAUNCHED": (409, "Swap references a refresh campaign that is not LAUNCHED"),
    "ERR_CAPABILITY_INSUFFICIENT": (422, "CPE capability below tier minimum"),
    "ERR_UPSTREAM_CONFIG_INSUFFICIENT": (422, "Node upstream_config below tier minimum"),
    "ERR_CAPACITY_EXCEEDED": (422, "Projected load reaches or exceeds the critical threshold"),
    "ERR_LAST_VIDEO_BLOCK": (422, "Reclaim would target every remaining VIDEO_ACTIVE block"),
    "ERR_HOMES_EXCEED_NODE": (422, "Service-group homes would exceed node homes_passed"),
    "ERR_SPECTRUM_OVERALLOCATED": (422, "Sum of block MHz would exceed node downstream_spectrum_mhz"),
    "ERR_ALLOCATION_INVALID": (422, "Cutover waterfall remainder falls outside [min, max]"),
    "ERR_CAUSE_MISMATCH": (422, "Asserted cause_category differs from the computed argmax"),
    "ERR_ACTION_TYPE_MISMATCH": (422, "Child entity created under a capacity action of the wrong action_type"),
    "ERR_UPGRADE_PATH_INVALID": (422, "Upgrade is not a single step or targets the wrong source config"),
    "ERR_CPE_NOT_ELIGIBLE": (422, "Wave target CPE missing, not ACTIVE, or already off legacy video"),
}


def raise_err(error_id, message=None):
    status, default_msg = ERR[error_id]
    raise ApiError(error_id, status, message if message is not None else default_msg)
