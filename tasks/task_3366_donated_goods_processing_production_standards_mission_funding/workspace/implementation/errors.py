"""API error type and the scaffold's error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def invalid_request(msg="Request body is missing required fields or contains invalid values"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


def ownership_mismatch(msg="Entity-backed identity does not match the target resource"):
    raise ApiError("ERR_OWNERSHIP_MISMATCH", 403, msg)


def not_found(msg="Referenced resource does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def stale_version(msg="expected_member_org_version does not match the member org's current version"):
    raise ApiError("ERR_STALE_VERSION", 412, msg)


def org_suspended(msg="Member organization brand license is not ACTIVE"):
    raise ApiError("ERR_ORG_SUSPENDED", 409, msg)


def invalid_state(msg="Resource is not in a valid state for the requested transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def markdown_already_run(msg="A markdown event already ran for this org in the current week"):
    raise ApiError("ERR_MARKDOWN_WEEK_ALREADY_RUN", 409, msg)


def diversion_breach(msg="Organization is not currently diversion compliant"):
    raise ApiError("ERR_DIVERSION_BREACH", 409, msg)


def segregation(msg="Creator of the resource may not perform the approval/attestation step"):
    raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, msg)


def no_eligible_standard(msg="No ACTIVE same-org ProductionStandard for this category"):
    raise ApiError("ERR_NO_ELIGIBLE_STANDARD", 409, msg)


def item_already_in_lot(msg="Item is not SALVAGED, already linked to a lot, or foreign to this org"):
    raise ApiError("ERR_ITEM_ALREADY_IN_LOT", 409, msg)


def item_channel_mismatch(msg="Item category not accepted by the lot's channel"):
    raise ApiError("ERR_ITEM_CHANNEL_MISMATCH", 409, msg)


def territory_overlap(msg="Territory window intersects another org's territory for this region_code"):
    raise ApiError("ERR_TERRITORY_WINDOW_OVERLAP", 409, msg)


def contract_overlap(msg="Contract window intersects another contract of the same org and agency"):
    raise ApiError("ERR_CONTRACT_WINDOW_OVERLAP", 409, msg)


def program_window_closed(msg="Logical clock is outside the program's funding window"):
    raise ApiError("ERR_PROGRAM_WINDOW_CLOSED", 409, msg)


def item_count_mismatch(msg="Number of sorted items does not equal item_count_declared"):
    raise ApiError("ERR_ITEM_COUNT_MISMATCH", 409, msg)


def bale_underweight(msg="TEXTILE_BALE lot is below the 50 lb minimum"):
    raise ApiError("ERR_BALE_UNDERWEIGHT", 409, msg)


def headcount_shortfall(msg="contract.enrolled_headcount is below milestone.min_headcount"):
    raise ApiError("ERR_HEADCOUNT_SHORTFALL", 409, msg)


def insufficient_margin(msg="Amount exceeds pool minus reserved"):
    raise ApiError("ERR_INSUFFICIENT_MARGIN", 402, msg)


def margin_reserve_breach(msg="margin_health is LOW; new allocations are blocked"):
    raise ApiError("ERR_MARGIN_RESERVE_BREACH", 409, msg)
