"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6).

Every error_id, HTTP status and default message below traces verbatim to the
error catalogue of the PRD and the scaffold.  The catalogue is the single source
of truth: handlers never invent an error id or a status code.
"""

from decimal import Decimal, ROUND_HALF_UP

# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_INVALID_REQUEST": (400, "Malformed request: an unknown field, a bad value or a missing declared input field."),
    "ERR_UNAUTHENTICATED": (401, "Authentication required: X-User-Role header is missing or names an unknown role."),
    "ERR_UNAUTHORIZED": (403, "The acting role is not permitted for this operation."),
    "ERR_BRANCH_NOT_FOUND": (404, "branch_code does not resolve to a branch."),
    "ERR_ADVISOR_NOT_FOUND": (404, "advisor_code does not resolve to an advisor."),
    "ERR_NOT_FOUND": (404, "The addressed resource does not exist."),
    "ERR_STALE_VERSION": (412, "The supplied expected version is stale."),
    "ERR_CLOCK_NOT_SET": (409, "The logical clock has not been set for a window-sensitive operation."),
    "ERR_PERIOD_ALREADY_EXISTS": (409, "A payout period already exists for the same branch, year, month and period_index."),
    "ERR_PERIOD_NOT_CLOSED": (409, "A payout period tagged to the branch is still OPEN or REOPENED."),
    "ERR_PERIOD_HAS_NO_RELEASED_PRODUCTION": (409, "The period has no released production in its calendar month."),
    "ERR_PERIOD_HAS_DRAFT_ENTRIES": (409, "A revenue entry in the period's calendar month is still DRAFT."),
    "ERR_PERIOD_ALREADY_POSTED": (409, "The period is already PAID or VOID."),
    "ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH": (409, "The line's provisional base rate does not match the tier grid base rate for its projected basis."),
    "ERR_EO_COVERAGE_INSUFFICIENT": (403, "Errors-and-omissions coverage is insufficient or the office of supervisory jurisdiction is not active."),
    "ERR_BOOK_PORTABILITY_BELOW_MINIMUM": (422, "The book portability ratio is below the threshold the operation requires."),
    "ERR_PORTABILITY_PROTOCOL_FAILURE": (403, "The advisor is not a protocol signatory and the portability ratio is below the non-protocol threshold."),
    "ERR_LOAN_BALANCE_OUTSTANDING": (409, "The advisor's transition assistance loan balance is not zero."),
    "ERR_NO_TRANSITION_LOAN": (409, "No transition assistance loan is on file for the advisor."),
    "ERR_BRANCH_NOT_ACTIVE": (409, "The advisor's primary branch is not ACTIVE."),
    "ERR_INVALID_STATE": (409, "The resource is not in the state the requested transition requires."),
    "ERR_FROZEN_ACCOUNTS_REMAIN": (409, "A child row of the aggregate is still pending."),
    "ERR_TRANSITION_ALREADY_SETTLED": (409, "The transition has already SETTLED."),
    "ERR_TRANSITION_NOT_SETTLED": (409, "The transition has not SETTLED."),
    "ERR_TRANSITION_NOT_CONTESTED": (409, "The transition is not in CONTESTED status."),
    "ERR_RETENTION_TARGET_MET": (409, "The retention ratio has already reached the target."),
    "ERR_RETENTION_TARGET_MISSED": (409, "The retention ratio is below the target."),
    "ERR_RETENTION_CREDIT_EXHAUSTED": (409, "The book retention credit cap is fully consumed."),
    "ERR_TRANSFER_HOLD_PERIOD": (409, "The supervisory hold period has not elapsed."),
    "ERR_YEAR_ALREADY_LEVELIZED": (409, "Every eligible advisory account has already been levelized this calendar year."),
    "ERR_RATE_FLOOR_APPLIED": (422, "The computed grid rate was clamped to the floor."),
    "ERR_PAYOUT_CAP_REACHED": (409, "The advisor's cumulative released payout has reached the annual gross payout cap."),
}


class ApiError(Exception):
    """Carries the catalogue error id, the HTTP status and a message."""

    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request rejected."))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.7): a single round-half-up step, never banker's.
# ---------------------------------------------------------------------------

CENT = Decimal("1")


def round_half_up(value):
    """Round a Decimal (or int/str) to whole units, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))