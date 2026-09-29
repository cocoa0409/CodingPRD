"""Helpers shared by the route modules (PRD 2.11 precedence steps 3, 7, 13)."""
import auth
import clock
import db
from errors import fail

NOT_FOUND = {
    "desk_policies": "ERR_DESK_POLICY_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "quote_lines": "ERR_QUOTE_LINE_NOT_FOUND",
    "nonstandard_terms": "ERR_TERM_NOT_FOUND",
    "competitive_exceptions": "ERR_EXCEPTION_NOT_FOUND",
    "revrec_assessments": "ERR_REVREC_NOT_FOUND",
    "approval_steps": "ERR_APPROVAL_STEP_NOT_FOUND",
    "delegation_grants": "ERR_DELEGATION_NOT_FOUND",
    "order_forms": "ERR_ORDER_FORM_NOT_FOUND",
}


def must_get(collection, record_id):
    record = db.get(collection, record_id)
    if record is None:
        fail(NOT_FOUND[collection])
    return record


def policy_of(quote):
    return db.policy(quote["desk_policy_id"])


def require_owner(quote):
    """PRD 2.11 step 7: X-User-ID equals Quote.owner_rep_user_id."""
    if auth.current_user_id() != quote["owner_rep_user_id"]:
        fail("ERR_NOT_QUOTE_OWNER", "Only the owning SalesRep may perform this operation.")


def require_not_expired(quote):
    """PRD 3.8: expiry is strict, so equality with expires_at is on time."""
    if quote["expires_at"] is not None and clock.now() > quote["expires_at"]:
        fail("ERR_QUOTE_EXPIRED", "The logical clock is past the quote's expires_at.")


def require_status(quote, statuses, error_id):
    if quote["status"] not in statuses:
        fail(error_id)
