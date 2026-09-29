"""Non-standard terms and legal review (PRD 3.4, 3.7)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import common
import db
import response
import validation
import workflow
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("terms", __name__)

ALL = auth.ALL_ROLES

TERM_CATEGORIES = (
    "PAYMENT_TERMS",
    "SLA_COMMITMENT",
    "INDEMNITY_CAP",
    "TERMINATION_FOR_CONVENIENCE",
    "PRICE_HOLD_RENEWAL",
)

HOLD_CATEGORY = "PRICE_HOLD_RENEWAL"
HOLD_FIELDS = ("hold_product_id", "hold_start_date", "hold_end_date")

TERM_SPEC = {
    "quote_id": {"type": "string", "required": True},
    "term_category": {"type": "enum", "required": True, "values": TERM_CATEGORIES},
    "requested_numeric_value": {"type": "number", "required": True, "ge": Decimal(0)},
    "requested_text": {"type": "string"},
    "hold_product_id": {"type": "string"},
    "hold_start_date": {"type": "date"},
    "hold_end_date": {"type": "date"},
}

LIVE_HOLD_STATES = ("PENDING", "APPROVED")


def _hold_conflict(existing_start, existing_end, start, end, cooldown_days):
    """Inclusive windows must not overlap and must respect the cooldown.

    Both windows are inclusive at both ends, so the number of days separating
    them is the count of days belonging to neither window: two abutting windows
    (one ending the day before the other starts) are separated by zero days.
    """
    if start <= existing_end and existing_start <= end:
        return True
    if start > existing_end:
        gap = (start - existing_end).days - 1
    else:
        gap = (existing_start - end).days - 1
    return gap < cooldown_days


@bp.post("/nonstandard-terms")
@require_roles("SalesRep")
def create_nonstandard_term():
    body = validate(json_body(), TERM_SPEC)
    category = body["term_category"]
    supplied = [f for f in HOLD_FIELDS if f in body]
    if category == HOLD_CATEGORY:
        if len(supplied) != len(HOLD_FIELDS):
            fail(
                "ERR_INVALID_REQUEST",
                "hold_product_id, hold_start_date and hold_end_date are required for "
                "PRICE_HOLD_RENEWAL.",
            )
        if body["hold_end_date"] < body["hold_start_date"]:
            fail("ERR_INVALID_REQUEST", "hold_end_date must be on or after hold_start_date.")
    elif supplied:
        fail(
            "ERR_INVALID_REQUEST",
            "The hold window fields are only accepted for PRICE_HOLD_RENEWAL.",
        )

    quote = db.quote(body["quote_id"])
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND")
    if category == HOLD_CATEGORY and db.product(body["hold_product_id"]) is None:
        fail("ERR_PRODUCT_NOT_FOUND")

    common.require_owner(quote)
    if quote["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_QUOTE_NOT_DRAFT")

    policy = common.policy_of(quote)
    if category == HOLD_CATEGORY:
        cooldown = int(policy["price_hold_cooldown_days"])
        for other in db.sorted_records(db.all_records("nonstandard_terms")):
            if other["term_category"] != HOLD_CATEGORY:
                continue
            if other["review_state"] not in LIVE_HOLD_STATES:
                continue
            if other["hold_product_id"] != body["hold_product_id"]:
                continue
            other_quote = db.quote(other["quote_id"])
            if other_quote is None or other_quote["account_id"] != quote["account_id"]:
                continue
            if _hold_conflict(
                other["hold_start_date"], other["hold_end_date"],
                body["hold_start_date"], body["hold_end_date"], cooldown,
            ):
                fail(
                    "ERR_PRICE_HOLD_WINDOW_CONFLICT",
                    "The hold window does not respect price_hold_cooldown_days.",
                )

    term = {
        "quote_id": quote["id"],
        "term_category": category,
        "requested_numeric_value": body["requested_numeric_value"],
        "requested_text": body.get("requested_text"),
        "hold_product_id": body.get("hold_product_id"),
        "hold_start_date": body.get("hold_start_date"),
        "hold_end_date": body.get("hold_end_date"),
        "review_state": "PENDING",
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "reviewer_note": None,
        "requires_cfo_cosign": False,
        "cfo_cosigned_at": None,
        "cfo_cosigned_by_user_id": None,
    }
    workflow.score_term(term)
    db.insert("nonstandard_terms", term)
    db.mark_fresh(term)
    workflow.rescore_quote_terms(quote, policy)
    db.touch(quote)
    return response.created(term)


@bp.get("/quotes/<quote_id>/nonstandard-terms")
@require_roles(ALL)
def list_quote_terms(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.terms_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


REVIEW_SPEC = {
    "decision": {
        "type": "enum",
        "required": True,
        "values": ("APPROVE", "REJECT", "COSIGN"),
    },
    "reviewer_note": {"type": "string"},
}


@bp.post("/nonstandard-terms/<term_id>/review")
@require_roles("LegalCounsel", "CFO")
def review_nonstandard_term(term_id):
    term = common.must_get("nonstandard_terms", term_id)
    body = validate(json_body(), REVIEW_SPEC)
    decision = body["decision"]
    role = auth.current_role()
    if decision in ("APPROVE", "REJECT") and role != "LegalCounsel":
        fail("ERR_FORBIDDEN_ROLE", "Only LegalCounsel may approve or reject a term.")
    if decision == "COSIGN" and role != "CFO":
        fail("ERR_FORBIDDEN_ROLE", "Only the CFO may co-sign a term.")

    quote = db.quote(term["quote_id"])
    policy = common.policy_of(quote)
    request_row = db.open_request_of_quote(quote["id"])

    if decision == "COSIGN":
        if term["review_state"] != "APPROVED":
            fail("ERR_TERM_NOT_LEGAL_APPROVED")
        if quote["status"] != "PENDING_APPROVAL":
            fail("ERR_QUOTE_NOT_PENDING_APPROVAL")
        if not term["requires_cfo_cosign"]:
            fail("ERR_TERM_COSIGN_NOT_REQUIRED")
        if term["cfo_cosigned_at"] is not None:
            fail("ERR_TERM_ALREADY_COSIGNED")
        term["cfo_cosigned_at"] = clock.now()
        term["cfo_cosigned_by_user_id"] = auth.current_user_id()
        db.touch(term)
        workflow.rescore_quote_terms(quote, policy)
        if request_row is not None:
            workflow.maybe_clear_terms_axis(request_row, quote, policy)
        return response.ok(term)

    if term["review_state"] != "PENDING":
        fail("ERR_TERM_ALREADY_REVIEWED")
    if quote["status"] != "PENDING_APPROVAL":
        fail("ERR_QUOTE_NOT_PENDING_APPROVAL")
    if request_row is None or request_row["terms_track_state"] != "PENDING_LEGAL":
        fail("ERR_LEGAL_REVIEW_NOT_REQUIRED")

    term["review_state"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    term["reviewed_by_user_id"] = auth.current_user_id()
    term["reviewed_at"] = clock.now()
    term["reviewer_note"] = body.get("reviewer_note")
    db.touch(term)
    workflow.rescore_quote_terms(quote, policy)

    if decision == "APPROVE":
        workflow.maybe_clear_terms_axis(request_row, quote, policy)
    else:
        request_row["terms_track_state"] = "BLOCKED"
        db.touch(request_row)
        workflow.reject_request(request_row, quote)
    return response.ok(term)
