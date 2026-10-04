"""Error identifiers and the ApiError exception.

The catalogue is transcribed verbatim from PRD section 5 (which agrees with
``SCAFFOLD.yaml`` ``errors``).  ``ApiError`` carries everything the response
layer needs: the machine-readable ``error_id``, a human-readable ``message`` and
the HTTP status the PRD assigns to that identifier.
"""


# --- Authentication and authorisation -------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                     # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                           # 403
ERR_SOD_BACKUP_APPROVER = "ERR_SOD_BACKUP_APPROVER"             # 403

# --- Request shape ---------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                     # 400

# --- Resolution (left-to-right, PRD 2.6) -----------------------------------
ERR_HOMEOWNER_NOT_FOUND = "ERR_HOMEOWNER_NOT_FOUND"             # 404
ERR_PROPERTY_NOT_FOUND = "ERR_PROPERTY_NOT_FOUND"               # 404
ERR_QUALIFICATION_NOT_FOUND = "ERR_QUALIFICATION_NOT_FOUND"     # 404
ERR_BRIDGE_PROGRAM_NOT_FOUND = "ERR_BRIDGE_PROGRAM_NOT_FOUND"   # 404
ERR_LOAN_NOT_FOUND = "ERR_LOAN_NOT_FOUND"                       # 404
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"               # 404

# --- State -----------------------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"                         # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"                   # 409
ERR_BACKUP_OFFER_EXPIRED = "ERR_BACKUP_OFFER_EXPIRED"           # 409
ERR_LISTING_STATE_CONFLICT = "ERR_LISTING_STATE_CONFLICT"       # 409
ERR_LOAN_ALREADY_REPAID = "ERR_LOAN_ALREADY_REPAID"             # 409

# --- Lending and pricing ---------------------------------------------------
ERR_CREDIT_SCORE_BELOW_MINIMUM = "ERR_CREDIT_SCORE_BELOW_MINIMUM"   # 422
ERR_LTV_EXCEEDS_LIMIT = "ERR_LTV_EXCEEDS_LIMIT"                     # 422
ERR_REGULATORY_PRICE_FLOOR = "ERR_REGULATORY_PRICE_FLOOR"           # 422
ERR_STAKEHOLDER_REVIEW_REQUIRED = "ERR_STAKEHOLDER_REVIEW_REQUIRED" # 422

# --- Capacity and partner rules -------------------------------------------
ERR_NO_CAPACITY = "ERR_NO_CAPACITY"                             # 422
ERR_DUPLICATE_ACTIVE_REFERRAL = "ERR_DUPLICATE_ACTIVE_REFERRAL"  # 409
ERR_OVERLAPPING_TASK = "ERR_OVERLAPPING_TASK"                   # 409
ERR_REPAIR_SCOPE_EXCEEDS_CAP = "ERR_REPAIR_SCOPE_EXCEEDS_CAP"   # 422
ERR_LISTING_SLOT_OVERLAP = "ERR_LISTING_SLOT_OVERLAP"           # 409
ERR_ADVANCE_WINDOW_CLOSED = "ERR_ADVANCE_WINDOW_CLOSED"         # 409

# --- Fiscal ----------------------------------------------------------------
ERR_CARRYING_COST_UNPAID = "ERR_CARRYING_COST_UNPAID"           # 422
ERR_SETTLEMENT_NOT_FULL = "ERR_SETTLEMENT_NOT_FULL"             # 422
ERR_DISBURSEMENT_EXCEEDS_BALANCE = "ERR_DISBURSEMENT_EXCEEDS_BALANCE"  # 422

# --- Referential and temporal ---------------------------------------------
ERR_APPRAISAL_STALE = "ERR_APPRAISAL_STALE"                     # 422
ERR_REPAIR_NOT_COMPLETE = "ERR_REPAIR_NOT_COMPLETE"             # 422
ERR_PROPERTY_KIND_MISMATCH = "ERR_PROPERTY_KIND_MISMATCH"       # 422
ERR_HOMEOWNER_MISMATCH = "ERR_HOMEOWNER_MISMATCH"               # 422
ERR_AGENT_NOT_QUALIFIED = "ERR_AGENT_NOT_QUALIFIED"             # 422
ERR_LISTING_OFFER_REQUIRED = "ERR_LISTING_OFFER_REQUIRED"       # 422
ERR_EXERCISE_WINDOW_NOT_OPEN = "ERR_EXERCISE_WINDOW_NOT_OPEN"   # 422
ERR_LISTING_BEFORE_OCCUPANCY = "ERR_LISTING_BEFORE_OCCUPANCY"   # 422

# --- Concurrency -----------------------------------------------------------
ERR_STALE_VERSION = "ERR_STALE_VERSION"                         # 412


STATUS_BY_ERROR = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_SOD_BACKUP_APPROVER: 403,
    ERR_INVALID_REQUEST: 400,
    ERR_HOMEOWNER_NOT_FOUND: 404,
    ERR_PROPERTY_NOT_FOUND: 404,
    ERR_QUALIFICATION_NOT_FOUND: 404,
    ERR_BRIDGE_PROGRAM_NOT_FOUND: 404,
    ERR_LOAN_NOT_FOUND: 404,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_BACKUP_OFFER_EXPIRED: 409,
    ERR_LISTING_STATE_CONFLICT: 409,
    ERR_LOAN_ALREADY_REPAID: 409,
    ERR_CREDIT_SCORE_BELOW_MINIMUM: 422,
    ERR_LTV_EXCEEDS_LIMIT: 422,
    ERR_REGULATORY_PRICE_FLOOR: 422,
    ERR_STAKEHOLDER_REVIEW_REQUIRED: 422,
    ERR_NO_CAPACITY: 422,
    ERR_DUPLICATE_ACTIVE_REFERRAL: 409,
    ERR_OVERLAPPING_TASK: 409,
    ERR_REPAIR_SCOPE_EXCEEDS_CAP: 422,
    ERR_LISTING_SLOT_OVERLAP: 409,
    ERR_ADVANCE_WINDOW_CLOSED: 409,
    ERR_CARRYING_COST_UNPAID: 422,
    ERR_SETTLEMENT_NOT_FULL: 422,
    ERR_DISBURSEMENT_EXCEEDS_BALANCE: 422,
    ERR_APPRAISAL_STALE: 422,
    ERR_REPAIR_NOT_COMPLETE: 422,
    ERR_PROPERTY_KIND_MISMATCH: 422,
    ERR_HOMEOWNER_MISMATCH: 422,
    ERR_AGENT_NOT_QUALIFIED: 422,
    ERR_LISTING_OFFER_REQUIRED: 422,
    ERR_EXERCISE_WINDOW_NOT_OPEN: 422,
    ERR_LISTING_BEFORE_OCCUPANCY: 422,
    ERR_STALE_VERSION: 412,
}

DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Missing or malformed X-User-ID / X-User-Role credentials.",
    ERR_UNAUTHORIZED: "The acting role is not permitted on this operation.",
    ERR_SOD_BACKUP_APPROVER: "The operator that issued this backup offer may not exercise it.",
    ERR_INVALID_REQUEST: "The request payload is missing a required field or holds an invalid value.",
    ERR_HOMEOWNER_NOT_FOUND: "No homeowner matches the referenced id.",
    ERR_PROPERTY_NOT_FOUND: "No property matches the referenced id.",
    ERR_QUALIFICATION_NOT_FOUND: "No qualification matches the referenced id.",
    ERR_BRIDGE_PROGRAM_NOT_FOUND: "No bridge program matches the referenced id.",
    ERR_LOAN_NOT_FOUND: "No interim loan matches the referenced id.",
    ERR_RESOURCE_NOT_FOUND: "No resource matches the referenced id.",
    ERR_INVALID_STATE: "The resource is not in a state from which this transition is declared.",
    ERR_ALREADY_TERMINAL: "The resource is already in a terminal state.",
    ERR_BACKUP_OFFER_EXPIRED: "The backup offer is not issuable or its exercise window has lapsed.",
    ERR_LISTING_STATE_CONFLICT: "The listing or program occupancy state does not permit this marketing step.",
    ERR_LOAN_ALREADY_REPAID: "The interim loan is not repaid, or a reopen has already been applied.",
    ERR_CREDIT_SCORE_BELOW_MINIMUM: "The household credit score is below the lender's floor.",
    ERR_LTV_EXCEEDS_LIMIT: "The interim loan principal exceeds the loan-to-value ceiling.",
    ERR_REGULATORY_PRICE_FLOOR: "The offer price is below the regulatory price floor.",
    ERR_STAKEHOLDER_REVIEW_REQUIRED: "This down payment requires prior stakeholder review.",
    ERR_NO_CAPACITY: "The requested amount exceeds the interim loan's draw headroom.",
    ERR_DUPLICATE_ACTIVE_REFERRAL: "An active referral already covers this side of the transaction.",
    ERR_OVERLAPPING_TASK: "The coordination task interval overlaps a non-terminal task for this referral.",
    ERR_REPAIR_SCOPE_EXCEEDS_CAP: "The cumulative repair amount exceeds the property's repair cap.",
    ERR_LISTING_SLOT_OVERLAP: "Another listing for this property is live over the requested slot.",
    ERR_ADVANCE_WINDOW_CLOSED: "The program's advance window is closed for repair approvals.",
    ERR_CARRYING_COST_UNPAID: "Outstanding carrying costs must be cleared before final settlement.",
    ERR_SETTLEMENT_NOT_FULL: "A final repayment must equal the combined principal and interest.",
    ERR_DISBURSEMENT_EXCEEDS_BALANCE: "The settlement amount exceeds the combined outstanding balance.",
    ERR_APPRAISAL_STALE: "The property appraisal is older than the allowed validity horizon.",
    ERR_REPAIR_NOT_COMPLETE: "The departing property's repairs are not complete.",
    ERR_PROPERTY_KIND_MISMATCH: "A referenced property's kind does not match the role it is used in.",
    ERR_HOMEOWNER_MISMATCH: "The referenced property is not owned by the referenced household.",
    ERR_AGENT_NOT_QUALIFIED: "The agent is suspended and may not receive referrals.",
    ERR_LISTING_OFFER_REQUIRED: "The listing has no recorded offer or is not under contract.",
    ERR_EXERCISE_WINDOW_NOT_OPEN: "The backup offer's exercise window has not opened yet.",
    ERR_LISTING_BEFORE_OCCUPANCY: "The household has not been recorded as occupying the new home.",
    ERR_STALE_VERSION: "The supplied expected version no longer matches the resource.",
}


class ApiError(Exception):
    """A refusal the API turns into the standard error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or STATUS_BY_ERROR.get(error_id, 400)
        super().__init__(self.message)

    def to_payload(self):
        return {"error_id": self.error_id, "message": self.message}