"""Error catalog (SCAFFOLD Table 6 / PRD section 5) and the ApiError type."""


class ApiError(Exception):
    """Carries an error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = http_status or status
        self.message = message or default_message


ERROR_CATALOG = {
    "ERR_INVALID_REQUEST": (400, "Required field missing, wrong type, invalid enum member, or a conditional-field rule violated."),
    "ERR_UNAUTHENTICATED": (401, "X-User-Role or X-User-ID header missing, or role value not declared."),
    "ERR_UNAUTHORIZED": (403, "Role not allowed on this endpoint, or Licensor X-User-ID does not equal the line's licensor_user_id."),
    "ERR_NOT_FOUND": (404, "Path id or body foreign key does not exist."),
    "ERR_STALE_VERSION": (412, "Expected version does not match the parent's current version (optimistic concurrency)."),
    "ERR_SOD_VIOLATION": (403, "Segregation of duties: the decider/approver is the same X-User-ID that created or submitted the resource."),
    "ERR_COLOR_NOT_ACTIVE": (409, "Campaign creation on a color not in the required state (PROPOSED for INTRODUCTION, ACTIVE for RETIREMENT)."),
    "ERR_CAMPAIGN_NOT_OPEN": (409, "Vote cast on a campaign that is SCHEDULED or TALLYED."),
    "ERR_CAMPAIGN_WINDOW_CONFLICT": (409, "New campaign window intersects an existing campaign window of the same color."),
    "ERR_FORMULA_NOT_APPROVABLE": (409, "APPROVE attempted while the formula's latest safety test is not PASSED, or a spec entry color has no APPROVED formula."),
    "ERR_INVALID_FORMULA_STATE": (409, "Formula transition not allowed from the formula's current state."),
    "ERR_BATCH_NOT_CERTIFIED": (409, "Production run references a pigment batch not in CERTIFIED state."),
    "ERR_BATCH_TERMINAL": (409, "Certification decision attempted on a REJECTED batch."),
    "ERR_CERTIFICATION_MARK_REQUIRED": (409, "CERTIFY attempted on a SENSITIVE or RESTRICTED hazard batch whose certification_mark is not ACMI_AP."),
    "ERR_SPEC_DEPRECATED": (409, "Production run references a DEPRECATED assortment spec."),
    "ERR_SPEC_INVALID": (409, "Assortment spec structurally invalid: empty entries, duplicate color, count < 1, unknown or non-ACTIVE entry color, box_size not in {8,16,24,64}, or CLASSROOM spec missing an ACTIVE core-curriculum color."),
    "ERR_RUN_STAGE_INVALID": (409, "ADVANCE/HOLD/RESUME/CANCEL not allowed from the run's current stage."),
    "ERR_RUN_ON_HOLD": (409, "ADVANCE attempted while the run is ON_HOLD; use RESUME."),
    "ERR_SESSION_FULL": (409, "INDIVIDUAL ticket created when booked_units + 1 > capacity_units."),
    "ERR_SESSION_CLOSED": (409, "Booking, check-in, or refund attempted on a CLOSED session."),
    "ERR_SESSION_WINDOW_CONFLICT": (409, "New session's occupied interval intersects an existing SCHEDULED session on the same venue and date."),
    "ERR_TICKET_STATE": (409, "Ticket decision not allowed from the ticket's current state, or check-in outside the session's live window."),
    "ERR_GROUP_TOO_LARGE": (422, "GROUP ticket with group_size > 100."),
    "ERR_ALLOCATION_STATE": (409, "Allocation decision not allowed from the allocation's current state."),
    "ERR_INSUFFICIENT_INVENTORY": (409, "COMMIT computes allocated_boxes_final == 0 (no boxes available)."),
    "ERR_LICENSE_STATE": (409, "Licensed-line transition not allowed from the line's current state."),
    "ERR_LICENSE_REQUIRED": (409, "Production run on a LICENSED spec without an APPROVED licensed line covering one of the spec's colors."),
    "ERR_STALE_PIN": (409, "REINSTATE attempted while the pinned formula version no longer matches the formula's current version or the formula is no longer APPROVED."),
    "ERR_LICENSE_TERM_WINDOW": (422, "Licensed run's planned dates are not fully contained in the line's [term_start, term_end]."),
    "ERR_RECALL_ACTIVE": (409, "Production run references a batch with an OPEN or CONTAINED recall case."),
    "ERR_VOTE_INVALID": (422, "Vote payload invalid: unknown voter_segment or choice, or count < 1."),
    "ERR_DATE_ORDER": (422, "Date ordering violated: closes_on <= opens_on, session_date in the past, planned_end_date <= planned_start_date, or term_end <= term_start."),
    "ERR_SEASON_WINDOW": (422, "requested_ship_date outside the season window."),
    "ERR_PLANNED_START_TOO_SOON": (422, "planned_start_date earlier than logical clock + 60 days."),
}
