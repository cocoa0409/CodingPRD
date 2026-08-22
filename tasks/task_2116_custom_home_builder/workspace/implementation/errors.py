"""Error catalog (PRD section 5 / SCAFFOLD section 1.6)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ROLE_IDENTITY_MISMATCH": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_LENDER_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_SUBCONTRACTOR_NOT_FOUND": 404,
    "ERR_ALLOWANCE_ITEM_NOT_FOUND": 404,
    "ERR_SELECTION_NOT_FOUND": 404,
    "ERR_CHANGE_ORDER_NOT_FOUND": 404,
    "ERR_SCHEDULE_TASK_NOT_FOUND": 404,
    "ERR_COST_ENTRY_NOT_FOUND": 404,
    "ERR_DRAW_REQUEST_NOT_FOUND": 404,
    "ERR_LIEN_WAIVER_NOT_FOUND": 404,
    "ERR_DEFECT_TICKET_NOT_FOUND": 404,
    "ERR_PHOTO_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CONTRACT_TERMS_INVALID": 422,
    "ERR_PROJECT_INVALID_STATE": 409,
    "ERR_PROJECT_NOT_UNDER_CONSTRUCTION": 409,
    "ERR_PROJECT_NOT_READY_TO_START": 409,
    "ERR_PROJECT_TASKS_INCOMPLETE": 409,
    "ERR_CHANGE_ORDER_PENDING": 409,
    "ERR_PROJECT_NOT_ACCEPTING_PHOTOS": 409,
    "ERR_PHOTO_ALREADY_PUBLISHED": 409,
    "ERR_ALLOWANCE_INVALID_STATE": 409,
    "ERR_ALLOWANCE_FROZEN": 409,
    "ERR_ALLOWANCE_ACTUAL_MISSING": 409,
    "ERR_ALLOWANCE_PROJECT_MISMATCH": 422,
    "ERR_SELECTION_NOT_PENDING": 409,
    "ERR_SELECTION_DEADLINE_PASSED": 422,
    "ERR_STALE_ALLOWANCE_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_CHANGE_ORDER_INVALID_STATE": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_TASK_INVALID_STATE": 409,
    "ERR_PREDECESSOR_INCOMPLETE": 409,
    "ERR_PREDECESSOR_CROSS_PROJECT": 422,
    "ERR_ALLOWANCE_NOT_LOCKED": 409,
    "ERR_MATERIAL_NOT_READY": 409,
    "ERR_CREW_CAPACITY_CONFLICT": 409,
    "ERR_JOBSITE_EXCLUSIVE_CONFLICT": 409,
    "ERR_COST_ENTRY_INVALID_STATE": 409,
    "ERR_DRAW_NOT_IN_DRAFT": 409,
    "ERR_DRAW_INVALID_STATE": 409,
    "ERR_DRAW_NO_ELIGIBLE_COSTS": 422,
    "ERR_DRAW_EXCEEDS_LENDER_CAP": 422,
    "ERR_PROJECT_HAS_NO_LENDER": 422,
    "ERR_LENDER_DECISION_WINDOW_EXPIRED": 409,
    "ERR_WAIVER_INVALID_STATE": 409,
    "ERR_WAIVER_TYPE_MISMATCH": 422,
    "ERR_WAIVER_AMOUNT_INSUFFICIENT": 422,
    "ERR_DEFECT_INVALID_STATE": 409,
    "ERR_DEFECT_NOT_COVERED": 422,
    "ERR_DEFECT_PHASE_MISMATCH": 422,
    "ERR_BLOCKING_PUNCH_ITEMS": 409,
    "ERR_PUNCH_ACK_COUNT_MISMATCH": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing, empty or unrecognised authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_ROLE_IDENTITY_MISMATCH": "X-User-ID does not resolve to a staff member with the acting role's function.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this operation.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_CONTRACT_TERMS_INVALID": "The supplied contract terms are incoherent.",
}


def _humanise(error_id):
    text = error_id[4:] if error_id.startswith("ERR_") else error_id
    text = text.replace("_", " ").lower()
    return text[:1].upper() + text[1:] + "."


class AppError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = (message
                        or DEFAULT_MESSAGES.get(error_id)
                        or _humanise(error_id))
