"""Error catalogue for the Retiree Medical & Medicare Coordination API.

Every error id and its HTTP status is taken verbatim from PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# --- authentication / authorization -----------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

# --- existence ---------------------------------------------------------------
ERR_PLAN_YEAR_NOT_FOUND = "ERR_PLAN_YEAR_NOT_FOUND"
ERR_RETIREE_NOT_FOUND = "ERR_RETIREE_NOT_FOUND"
ERR_PLAN_OPTION_NOT_FOUND = "ERR_PLAN_OPTION_NOT_FOUND"
ERR_DETERMINATION_NOT_FOUND = "ERR_DETERMINATION_NOT_FOUND"
ERR_ELECTION_EVENT_NOT_FOUND = "ERR_ELECTION_EVENT_NOT_FOUND"
ERR_ENROLLMENT_NOT_FOUND = "ERR_ENROLLMENT_NOT_FOUND"
ERR_HRA_ACCOUNT_NOT_FOUND = "ERR_HRA_ACCOUNT_NOT_FOUND"
ERR_CLAIM_NOT_FOUND = "ERR_CLAIM_NOT_FOUND"
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"

# --- request shape -----------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"

# --- optimistic concurrency --------------------------------------------------
ERR_STALE_RETIREE_VERSION = "ERR_STALE_RETIREE_VERSION"
ERR_STALE_HRA_ACCOUNT_VERSION = "ERR_STALE_HRA_ACCOUNT_VERSION"

# --- state machine legality --------------------------------------------------
ERR_INVALID_PLAN_YEAR_TRANSITION = "ERR_INVALID_PLAN_YEAR_TRANSITION"
ERR_PLAN_YEAR_NOT_OPEN = "ERR_PLAN_YEAR_NOT_OPEN"
ERR_PLAN_OPTION_NOT_ACTIVE = "ERR_PLAN_OPTION_NOT_ACTIVE"
ERR_INVALID_DETERMINATION_STATE = "ERR_INVALID_DETERMINATION_STATE"
ERR_INVALID_ELECTION_STATE = "ERR_INVALID_ELECTION_STATE"
ERR_INVALID_ENROLLMENT_STATE = "ERR_INVALID_ENROLLMENT_STATE"
ERR_HRA_ACCOUNT_NOT_OPEN = "ERR_HRA_ACCOUNT_NOT_OPEN"
ERR_INVALID_CLAIM_STATE = "ERR_INVALID_CLAIM_STATE"
ERR_INVOICE_ALREADY_SETTLED = "ERR_INVOICE_ALREADY_SETTLED"

# --- regulatory / segregation of duties --------------------------------------
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_ACTUARIAL_GROSS_TEST_FAILED = "ERR_ACTUARIAL_GROSS_TEST_FAILED"
ERR_ACTUARIAL_NET_TEST_FAILED = "ERR_ACTUARIAL_NET_TEST_FAILED"
ERR_SUBSIDY_NOT_CERTIFIED = "ERR_SUBSIDY_NOT_CERTIFIED"
ERR_DETERMINATION_NOT_CERTIFIED = "ERR_DETERMINATION_NOT_CERTIFIED"
ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL = "ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL"

# --- temporal windows --------------------------------------------------------
ERR_ELECTION_WINDOW_CLOSED = "ERR_ELECTION_WINDOW_CLOSED"
ERR_LIFE_EVENT_WINDOW_EXPIRED = "ERR_LIFE_EVENT_WINDOW_EXPIRED"

# --- referential / interval integrity ----------------------------------------
ERR_PLAN_CLASS_MISMATCH = "ERR_PLAN_CLASS_MISMATCH"
ERR_MEDICARE_PART_B_REQUIRED = "ERR_MEDICARE_PART_B_REQUIRED"
ERR_GRANDFATHER_GROUP_NOT_PERMITTED = "ERR_GRANDFATHER_GROUP_NOT_PERMITTED"
ERR_DUPLICATE_ENROLLMENT_PERIOD = "ERR_DUPLICATE_ENROLLMENT_PERIOD"
ERR_BILLING_PERIOD_OVERLAP = "ERR_BILLING_PERIOD_OVERLAP"
ERR_NOTICE_LEAD_TIME_INSUFFICIENT = "ERR_NOTICE_LEAD_TIME_INSUFFICIENT"

# --- constraint band ---------------------------------------------------------
ERR_REINSTATEMENT_WINDOW_EXPIRED = "ERR_REINSTATEMENT_WINDOW_EXPIRED"
ERR_EXPENSE_OUTSIDE_PLAN_YEAR = "ERR_EXPENSE_OUTSIDE_PLAN_YEAR"
ERR_DUPLICATE_PLAN_YEAR = "ERR_DUPLICATE_PLAN_YEAR"
ERR_DUPLICATE_PLAN_CODE = "ERR_DUPLICATE_PLAN_CODE"
ERR_DUPLICATE_HRA_ACCOUNT = "ERR_DUPLICATE_HRA_ACCOUNT"
ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED = "ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED"
ERR_OUTSTANDING_PREMIUM_BALANCE = "ERR_OUTSTANDING_PREMIUM_BALANCE"

# --- money availability ------------------------------------------------------
ERR_HRA_BALANCE_INSUFFICIENT = "ERR_HRA_BALANCE_INSUFFICIENT"
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"


HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_PLAN_YEAR_NOT_FOUND: 404,
    ERR_RETIREE_NOT_FOUND: 404,
    ERR_PLAN_OPTION_NOT_FOUND: 404,
    ERR_DETERMINATION_NOT_FOUND: 404,
    ERR_ELECTION_EVENT_NOT_FOUND: 404,
    ERR_ENROLLMENT_NOT_FOUND: 404,
    ERR_HRA_ACCOUNT_NOT_FOUND: 404,
    ERR_CLAIM_NOT_FOUND: 404,
    ERR_INVOICE_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_PAGINATION: 400,
    ERR_STALE_RETIREE_VERSION: 412,
    ERR_STALE_HRA_ACCOUNT_VERSION: 412,
    ERR_INVALID_PLAN_YEAR_TRANSITION: 409,
    ERR_PLAN_YEAR_NOT_OPEN: 409,
    ERR_PLAN_OPTION_NOT_ACTIVE: 409,
    ERR_INVALID_DETERMINATION_STATE: 409,
    ERR_INVALID_ELECTION_STATE: 409,
    ERR_INVALID_ENROLLMENT_STATE: 409,
    ERR_HRA_ACCOUNT_NOT_OPEN: 409,
    ERR_INVALID_CLAIM_STATE: 409,
    ERR_INVOICE_ALREADY_SETTLED: 409,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_ACTUARIAL_GROSS_TEST_FAILED: 422,
    ERR_ACTUARIAL_NET_TEST_FAILED: 422,
    ERR_SUBSIDY_NOT_CERTIFIED: 409,
    ERR_DETERMINATION_NOT_CERTIFIED: 409,
    ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL: 422,
    ERR_ELECTION_WINDOW_CLOSED: 422,
    ERR_LIFE_EVENT_WINDOW_EXPIRED: 422,
    ERR_PLAN_CLASS_MISMATCH: 422,
    ERR_MEDICARE_PART_B_REQUIRED: 422,
    ERR_GRANDFATHER_GROUP_NOT_PERMITTED: 422,
    ERR_DUPLICATE_ENROLLMENT_PERIOD: 409,
    ERR_BILLING_PERIOD_OVERLAP: 409,
    ERR_NOTICE_LEAD_TIME_INSUFFICIENT: 422,
    ERR_REINSTATEMENT_WINDOW_EXPIRED: 422,
    ERR_EXPENSE_OUTSIDE_PLAN_YEAR: 422,
    ERR_DUPLICATE_PLAN_YEAR: 409,
    ERR_DUPLICATE_PLAN_CODE: 409,
    ERR_DUPLICATE_HRA_ACCOUNT: 409,
    ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED: 409,
    ERR_OUTSTANDING_PREMIUM_BALANCE: 409,
    ERR_HRA_BALANCE_INSUFFICIENT: 422,
    ERR_PAYMENT_EXCEEDS_BALANCE: 422,
}

_DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Authentication headers are missing, empty or name an undeclared role.",
    ERR_UNAUTHORIZED: "The acting role is not authorized for this operation.",
    ERR_PLAN_YEAR_NOT_FOUND: "The referenced plan year does not exist.",
    ERR_RETIREE_NOT_FOUND: "The referenced retiree does not exist.",
    ERR_PLAN_OPTION_NOT_FOUND: "The referenced plan option does not exist.",
    ERR_DETERMINATION_NOT_FOUND: "The referenced eligibility determination does not exist.",
    ERR_ELECTION_EVENT_NOT_FOUND: "The referenced election event does not exist.",
    ERR_ENROLLMENT_NOT_FOUND: "The referenced enrollment does not exist.",
    ERR_HRA_ACCOUNT_NOT_FOUND: "The referenced reimbursement account does not exist.",
    ERR_CLAIM_NOT_FOUND: "The referenced reimbursement claim does not exist.",
    ERR_INVOICE_NOT_FOUND: "The referenced premium invoice does not exist.",
    ERR_INVALID_REQUEST: "The request body failed shape validation.",
    ERR_INVALID_PAGINATION: "limit must be an integer in [1, 100] and offset an integer of at least 0.",
    ERR_STALE_RETIREE_VERSION: "expected_retiree_version does not match the retiree's current version.",
    ERR_STALE_HRA_ACCOUNT_VERSION: "expected_hra_account_version does not match the account's current version.",
    ERR_INVALID_PLAN_YEAR_TRANSITION: "The requested plan year status is not the legal successor of the current status.",
    ERR_PLAN_YEAR_NOT_OPEN: "The governing plan year is not in an acceptable status for this operation.",
    ERR_PLAN_OPTION_NOT_ACTIVE: "The plan option availability status does not permit this operation.",
    ERR_INVALID_DETERMINATION_STATE: "The determination status does not permit the requested move.",
    ERR_INVALID_ELECTION_STATE: "The election event status does not permit the requested move.",
    ERR_INVALID_ENROLLMENT_STATE: "The enrollment state does not permit the requested move.",
    ERR_HRA_ACCOUNT_NOT_OPEN: "The reimbursement account is not OPEN.",
    ERR_INVALID_CLAIM_STATE: "The claim status does not permit the requested move.",
    ERR_INVOICE_ALREADY_SETTLED: "The invoice accepts no further payment.",
    ERR_SEGREGATION_OF_DUTIES: "The acting user may not approve their own work.",
    ERR_ACTUARIAL_GROSS_TEST_FAILED: "The attested gross prescription-drug value is below the standard benchmark.",
    ERR_ACTUARIAL_NET_TEST_FAILED: "The attested net prescription-drug value is below the standard net benchmark.",
    ERR_SUBSIDY_NOT_CERTIFIED: "The plan option's subsidy election is not certified.",
    ERR_DETERMINATION_NOT_CERTIFIED: "The retiree holds no CERTIFIED determination for this plan year.",
    ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL: "The certified determination outcome is INELIGIBLE.",
    ERR_ELECTION_WINDOW_CLOSED: "The logical clock lies outside the annual election window.",
    ERR_LIFE_EVENT_WINDOW_EXPIRED: "The logical clock lies outside the life-event window.",
    ERR_PLAN_CLASS_MISMATCH: "The option's coverage class does not match the retiree's Medicare posture.",
    ERR_MEDICARE_PART_B_REQUIRED: "The option requires Medicare Part B coverage in force.",
    ERR_GRANDFATHER_GROUP_NOT_PERMITTED: "The retiree's grandfather cohort may not elect this option.",
    ERR_DUPLICATE_ENROLLMENT_PERIOD: "The proposed coverage interval collides with an existing enrollment.",
    ERR_BILLING_PERIOD_OVERLAP: "The proposed billing period collides with an existing invoice period.",
    ERR_NOTICE_LEAD_TIME_INSUFFICIENT: "The plan change notice does not satisfy the required lead time.",
    ERR_REINSTATEMENT_WINDOW_EXPIRED: "The reinstatement window has expired.",
    ERR_EXPENSE_OUTSIDE_PLAN_YEAR: "The service date falls outside the account's plan-year expense window.",
    ERR_DUPLICATE_PLAN_YEAR: "Another plan year already carries the requested year.",
    ERR_DUPLICATE_PLAN_CODE: "Another plan option in this plan year already carries the requested plan code.",
    ERR_DUPLICATE_HRA_ACCOUNT: "A reimbursement account already exists for this retiree and plan year, or the prior-year account reference is invalid.",
    ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED: "The prior-year reimbursement account is not CLOSED.",
    ERR_OUTSTANDING_PREMIUM_BALANCE: "Another enrollment of this retiree carries a past-due balance.",
    ERR_HRA_BALANCE_INSUFFICIENT: "The reimbursement account has no available balance to hold against this claim.",
    ERR_PAYMENT_EXCEEDS_BALANCE: "The payment exceeds the invoice's remaining balance.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP_STATUS[error_id], message)
