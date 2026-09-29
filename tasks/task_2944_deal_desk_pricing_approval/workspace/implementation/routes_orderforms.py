"""Order forms, signature routing, booking and reversal (PRD 3.9)."""
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

bp = Blueprint("orderforms", __name__)

ALL = auth.ALL_ROLES

VOID_SUPERSEDED = "SUPERSEDED_BY_NEW_ORDER_FORM"
VOID_QUOTE_EXPIRED = "QUOTE_EXPIRED"
VOID_BOOKING_REVERSED = "BOOKING_REVERSED"
UNSIGNED_STATUSES = ("GENERATED", "OUT_FOR_SIGNATURE")

FORM_SPEC = {
    "quote_id": {"type": "string", "required": True},
    "signer_name": {"type": "string", "required": True},
    "signer_email": {"type": "string", "required": True},
    "expected_quote_version": {"type": "integer", "required": True},
}


@bp.post("/order-forms")
@require_roles("SalesRep")
def create_order_form():
    body = validate(json_body(), FORM_SPEC)
    quote = db.quote(body["quote_id"])
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND")
    common.require_owner(quote)
    if quote["status"] != "APPROVED":
        fail("ERR_QUOTE_NOT_APPROVED")
    if body["expected_quote_version"] != quote["version"]:
        fail("ERR_STALE_QUOTE_VERSION", "expected_quote_version does not match the quote.")
    common.require_not_expired(quote)

    for existing in db.order_forms_of_quote(quote["id"]):
        if existing["status"] not in UNSIGNED_STATUSES:
            continue
        existing["status"] = "VOID"
        existing["voided_at"] = clock.now()
        existing["void_reason"] = VOID_SUPERSEDED
        db.touch(existing)

    db.touch(quote)
    record = {
        "quote_id": quote["id"],
        "signer_name": body["signer_name"],
        "signer_email": body["signer_email"],
        "generated_from_quote_version": quote["version"],
        "status": "GENERATED",
        "sent_at": None,
        "signed_at": None,
        "declined_at": None,
        "booked_at": None,
        "voided_at": None,
        "signed_by_name": None,
        "void_reason": None,
        "reversal_reason": None,
        "booked_arr_cents": 0,
        "booked_tcv_cents": 0,
        "booking_reversed_at": None,
        "booking_reversal_count": 0,
    }
    db.insert("order_forms", record)
    db.mark_fresh(record)
    return response.created(record)


@bp.get("/order-forms/<form_id>")
@require_roles(ALL)
def read_order_form(form_id):
    return response.ok(common.must_get("order_forms", form_id))


@bp.get("/quotes/<quote_id>/order-forms")
@require_roles(ALL)
def list_quote_order_forms(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.order_forms_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


@bp.post("/order-forms/<form_id>/send")
@require_roles("SalesRep")
def send_order_form(form_id):
    form = common.must_get("order_forms", form_id)
    validate(json_body(), {})
    quote = db.quote(form["quote_id"])
    common.require_owner(quote)
    if form["status"] != "GENERATED":
        fail("ERR_ORDER_FORM_STATE_INVALID")
    if quote["status"] != "APPROVED":
        fail("ERR_QUOTE_NOT_APPROVED")
    common.require_not_expired(quote)
    form["status"] = "OUT_FOR_SIGNATURE"
    form["sent_at"] = clock.now()
    db.touch(form)
    return response.ok(form)


SIGNATURE_SPEC = {
    "outcome": {"type": "enum", "required": True, "values": ("SIGNED", "DECLINED")},
    "signed_by_name": {"type": "string"},
}


@bp.post("/order-forms/<form_id>/signature")
@require_roles("DealDeskAnalyst")
def sign_order_form(form_id):
    form = common.must_get("order_forms", form_id)
    body = validate(json_body(), SIGNATURE_SPEC)
    quote = db.quote(form["quote_id"])
    if form["status"] != "OUT_FOR_SIGNATURE":
        fail("ERR_ORDER_FORM_STATE_INVALID")
    if quote["status"] != "APPROVED":
        fail("ERR_QUOTE_NOT_APPROVED")

    if body["outcome"] == "SIGNED":
        common.require_not_expired(quote)
        form["status"] = "SIGNED"
        form["signed_at"] = clock.now()
        form["signed_by_name"] = body.get("signed_by_name")
    else:
        form["status"] = "DECLINED"
        form["declined_at"] = clock.now()
    db.touch(form)
    return response.ok(form)


@bp.post("/order-forms/<form_id>/book")
@require_roles("DealDeskAnalyst")
def book_order_form(form_id):
    form = common.must_get("order_forms", form_id)
    validate(json_body(), {})
    quote = db.quote(form["quote_id"])
    account = db.account(quote["account_id"])

    if form["status"] != "SIGNED":
        fail("ERR_ORDER_FORM_STATE_INVALID")
    if quote["status"] != "APPROVED":
        fail("ERR_QUOTE_NOT_APPROVED")
    common.require_not_expired(quote)

    if account["credit_status"] == "HOLD":
        fail("ERR_ACCOUNT_CREDIT_HOLD")
    if form["generated_from_quote_version"] != quote["version"]:
        fail("ERR_BOOKING_CRITERIA_UNMET", "The order form no longer matches the quote version.")
    if quote["policy_revalidation_required"]:
        fail("ERR_BOOKING_CRITERIA_UNMET", "The quote requires policy revalidation.")
    if not workflow.revrec_gate_satisfied(quote):
        fail("ERR_BOOKING_CRITERIA_UNMET", "The revenue recognition gate is not satisfied.")

    figures = calc.booking_figures(quote, db.lines_of_quote(quote["id"]))
    if figures["booked_tcv_cents"] <= 0:
        fail("ERR_BOOKING_CRITERIA_UNMET", "The total contract value is not above zero.")

    instant = clock.now()
    form["status"] = "BOOKED"
    form["booked_at"] = instant
    form["booked_arr_cents"] = figures["booked_arr_cents"]
    form["booked_tcv_cents"] = figures["booked_tcv_cents"]
    db.touch(form)

    account["booked_arr_cents"] = int(account["booked_arr_cents"]) + figures["booked_arr_cents"]
    db.touch(account)

    quote["status"] = "BOOKED"
    quote["booked_at"] = instant
    quote["booked_arr_cents"] = figures["booked_arr_cents"]
    quote["booked_tcv_cents"] = figures["booked_tcv_cents"]
    db.touch(quote)
    return response.ok(form)


REVERSE_SPEC = {"reversal_reason": {"type": "string", "required": True}}


@bp.post("/order-forms/<form_id>/reverse-booking")
@require_roles("CFO")
def reverse_order_form_booking(form_id):
    form = common.must_get("order_forms", form_id)
    body = validate(json_body(), REVERSE_SPEC)
    quote = db.quote(form["quote_id"])

    if form["status"] != "BOOKED":
        fail("ERR_ORDER_FORM_STATE_INVALID")
    if quote["status"] != "BOOKED":
        fail("ERR_ORDER_FORM_STATE_INVALID", "The parent quote is not BOOKED.")

    instant = clock.now()
    form["status"] = "VOID"
    form["booking_reversed_at"] = instant
    form["voided_at"] = instant
    form["reversal_reason"] = body["reversal_reason"]
    form["void_reason"] = VOID_BOOKING_REVERSED
    form["booking_reversal_count"] = int(form["booking_reversal_count"]) + 1
    db.touch(form)

    account = db.account(quote["account_id"])
    account["booked_arr_cents"] = int(account["booked_arr_cents"]) - int(form["booked_arr_cents"])
    db.touch(account)

    quote["status"] = "APPROVED"
    quote["booked_at"] = None
    quote["booked_arr_cents"] = 0
    quote["booked_tcv_cents"] = 0
    db.touch(quote)
    return response.ok(form)
