"""Rejection-precedence machinery (PRD section 2.6).

Every endpoint declares the checks it participates in as (priority, callable)
pairs and hands them to :func:`run_gates`, which executes them in ascending
priority order.  The ordering is therefore a property of this module rather
than of the order the checks happen to be written in a handler, so the first
failing check always decides the response exactly as section 2.6 demands.

The numeric keys are the scaffold's validation priorities; the comment on each
constant is that rule's rank in the PRD's own 1..46 ordered list.
"""
import db
from errors import not_found, raise_err

# --- authentication and authorization (handled by middleware, always first) --
P_AUTH = 10               # PRD 1  ERR_UNAUTHENTICATED
P_ROLE = 20               # PRD 2  ERR_FORBIDDEN_ROLE
# --- existence ---------------------------------------------------------------
P_PATH = 30               # PRD 3  path ids, left to right
P_BODY_FK = 35            # PRD 4  body foreign keys, in input-list order
# --- ownership ---------------------------------------------------------------
P_OWNER = 40              # PRD 5  ERR_NOT_RESOURCE_OWNER
# --- body well-formedness ----------------------------------------------------
P_BODY = 45               # PRD 6  ERR_INVALID_REQUEST
# --- domain gates ahead of the generic state check ---------------------------
P_COMPLAINT_RESOLVED = 46  # PRD 7  ERR_COMPLAINT_ALREADY_RESOLVED
P_UNIQUE = 48             # PRD 8  natural-key uniqueness
P_AUDITION_REQUIRED = 49  # PRD 9  ERR_AUDITION_REQUIRED
# --- generic state -----------------------------------------------------------
P_STATE = 50              # PRD 10 ERR_INVALID_STATE
P_PERMIT_ACTIVE = 51      # PRD 11 ERR_PERMIT_NOT_ACTIVE
P_PERMIT_SUSPENDED = 52   # PRD 12 ERR_PERMIT_SUSPENDED
# --- optimistic concurrency --------------------------------------------------
P_OCC_APPLICATION = 54    # PRD 13 ERR_STALE_APPLICATION_VERSION
P_OCC_PERMIT = 55         # PRD 14 ERR_STALE_PERMIT_VERSION
# --- separation of duties ----------------------------------------------------
P_SOD_ADJUDICATE = 56     # PRD 15 ERR_SEGREGATION_OF_DUTIES (adjudication)
P_SOD_DECISION = 57       # PRD 16 ERR_SEGREGATION_OF_DUTIES (decision)
# --- business safety ---------------------------------------------------------
P_PANEL_INCOMPLETE = 59   # PRD 17 ERR_AUDITION_PANEL_INCOMPLETE
P_PERFORMER_BARRED = 60   # PRD 18 ERR_PERFORMER_BARRED
P_AMP_PROHIBITED = 61     # PRD 19 ERR_AMPLIFICATION_PROHIBITED
P_AMP_NOT_ENDORSED = 62   # PRD 20 ERR_AMPLIFICATION_NOT_ENDORSED
P_QUIET_HOURS = 63        # PRD 21 ERR_QUIET_HOURS_VIOLATION
P_PITCH_CLOSED = 64       # PRD 22 ERR_PITCH_CLOSED
P_PITCH_ZONE_MISMATCH = 65  # PRD 23 ERR_PITCH_ZONE_MISMATCH
P_BOOKING_PERMIT_MISMATCH = 66  # PRD 24 ERR_BOOKING_PERMIT_MISMATCH
P_SESSION_TOO_LONG = 67   # PRD 25 ERR_SESSION_TOO_LONG
P_LEAD_TIME = 68          # PRD 26 ERR_BOOKING_LEAD_TIME
P_HORIZON = 69            # PRD 27 ERR_BOOKING_HORIZON_EXCEEDED
P_READING_WINDOW = 70     # PRD 28 ERR_READING_OUTSIDE_SESSION
P_SESSION_STARTED = 71    # PRD 29 ERR_SESSION_ALREADY_STARTED
P_RENEWAL_WINDOW = 72     # PRD 30 ERR_RENEWAL_WINDOW_CLOSED
P_ENTRY_DEADLINE = 73     # PRD 31 ERR_ENTRY_DEADLINE_PASSED
P_ENTRY_DEADLINE_NOT = 74  # PRD 32 ERR_ENTRY_DEADLINE_NOT_PASSED
P_SLOT_OVERLAP = 75       # PRD 33 ERR_PITCH_SLOT_OVERLAP
P_CLOSURE_CAPACITY = 76   # PRD 34 ERR_CLOSURE_WINDOW_CONFLICT
P_DAILY_CAP = 77          # PRD 35 ERR_PITCH_DAILY_CAP_REACHED
P_NOT_PREMIUM = 78        # PRD 36 ERR_PITCH_NOT_PREMIUM
P_DUP_ENTRY = 79          # PRD 37 ERR_DUPLICATE_LOTTERY_ENTRY
P_DUP_APPLICATION = 80    # PRD 38 ERR_DUPLICATE_ACTIVE_APPLICATION
P_DUP_PANEL_SCORE = 81    # PRD 39 ERR_DUPLICATE_PANEL_SCORE
P_REVISION_LIMIT = 82     # PRD 40 ERR_REVISION_LIMIT_EXCEEDED
P_NO_ENTRIES = 83         # PRD 41 ERR_NO_ELIGIBLE_ENTRIES
P_INVOICE_PAST_DUE = 84   # PRD 42 ERR_INVOICE_PAST_DUE
P_OUTSTANDING_INVOICE = 85  # PRD 43 ERR_OUTSTANDING_INVOICE
P_RENEWAL_CONDUCT = 86    # PRD 44 ERR_RENEWAL_CONDUCT_INSUFFICIENT
P_PAYMENT_AMOUNT = 87     # PRD 45 ERR_PAYMENT_AMOUNT_MISMATCH
P_SEASON_MINUTES = 88     # PRD 46 ERR_SEASON_MINUTE_CAP_EXCEEDED


def run_gates(gates):
    """Execute (priority, callable) pairs in ascending priority order."""
    for _, check in sorted(gates, key=lambda pair: pair[0]):
        check()


def resolve(store, ident):
    """Resolve an id, raising that collection's not-found error when absent."""
    row = db.get(store, ident)
    if row is None:
        not_found(store)
    return row


def resolve_body_fk(store, body, key, required=True):
    """Resolve a body foreign key (PRD section 2.6 rule 4).

    A key that is absent or null is left to the well-formedness check at
    priority 45; a key that is supplied must resolve to a live row.
    """
    if key not in body or body.get(key) is None:
        return None
    return resolve(store, body.get(key))


def require_version(expected, actual, error_id):
    if expected != actual:
        raise_err(error_id, "The supplied version expectation is stale")
