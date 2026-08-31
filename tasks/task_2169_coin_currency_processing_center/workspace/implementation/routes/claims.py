"""DiscrepancyClaim routes: filing window, review loop, and the two decisions."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    CLAIM_STATUSES,
    CLAIM_TYPES,
    CLAIM_WINDOW_HOURS,
    MAX_CLAIM_ROUNDS,
    ROLE_CUSTOMER,
    ROLE_VAULT_MANAGER,
    authorize,
    body_json,
    check_ownership,
    clock_now,
    db,
    fail,
    fmt_dt,
    get_bag,
    get_claim,
    get_pagination,
    make_row,
    ordered,
    paginate,
    parse_dt,
    query_enum,
    query_str,
    req_enum,
    req_int,
    req_str,
    respond,
    sessions_of_bag,
    touch,
)
from serializers import claim_out

bp = Blueprint("claims", __name__)


def _segregation_guard(actor, sealed_bag_id):
    for session in sessions_of_bag(sealed_bag_id):
        if session["status"] == "COMPLETED" and session["verifier_user_id"] == actor.user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The verifier of the disputed count may not decide the claim.",
            )


@bp.post("/discrepancy-claims")
def file_claim():
    actor = authorize(ROLE_CUSTOMER)
    body = body_json()
    sealed_bag_id = req_str(body, "sealed_bag_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    claimed_amount_cents = req_int(body, "claimed_amount_cents", minimum=1)

    bag = get_bag(sealed_bag_id)
    ticket = db.tickets.get(bag["deposit_ticket_id"])
    account_id = ticket["customer_account_id"] if ticket else None
    check_ownership(actor, account_id)

    # ladder 12 - the bag must have been counted
    if bag["count_status"] not in ("COUNTED", "ADJUSTED"):
        fail("ERR_BAG_NOT_COUNTED", "The bag has not been counted.")

    # ladder 27 - the claim window is half-open: counted_at .. counted_at + 24h
    counted_at = parse_dt(bag["counted_at"]) if bag["counted_at"] else None
    if counted_at is None:
        fail("ERR_BAG_NOT_COUNTED", "The bag has not been counted.")
    if clock_now() >= counted_at + timedelta(hours=CLAIM_WINDOW_HOURS):
        fail("ERR_CLAIM_WINDOW_CLOSED", "The discrepancy claim window has closed.")

    # ladder 38 - a customer cannot claim more than they declared
    if claimed_amount_cents > bag["declared_amount_cents"]:
        fail(
            "ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED",
            "claimed_amount_cents exceeds the bag's declared_amount_cents.",
        )

    row = make_row()
    row.update({
        "sealed_bag_id": sealed_bag_id,
        "customer_account_id": account_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
        "status": "SUBMITTED",
        "review_round": 1,
        "resolution_amount_cents": 0,
        "filed_at": fmt_dt(clock_now()),
        "decided_by_user_id": None,
        "info_request_note": None,
        "denial_reason": None,
    })
    db.claims[row["id"]] = row
    return respond(claim_out(row), 201)


@bp.get("/discrepancy-claims/<claim_id>")
def read_claim(claim_id):
    actor = authorize(ROLE_VAULT_MANAGER, ROLE_CUSTOMER)
    claim = get_claim(claim_id)
    check_ownership(actor, claim["customer_account_id"])
    return respond(claim_out(claim))


@bp.get("/discrepancy-claims")
def list_claims():
    authorize(ROLE_VAULT_MANAGER, ROLE_CUSTOMER)
    limit, offset = get_pagination()
    sealed_bag_id = query_str("sealed_bag_id")
    customer_account_id = query_str("customer_account_id")
    status = query_enum("status", CLAIM_STATUSES)

    rows = ordered(db.claims.values())
    if sealed_bag_id is not None:
        rows = [r for r in rows if r["sealed_bag_id"] == sealed_bag_id]
    if customer_account_id is not None:
        rows = [r for r in rows if r["customer_account_id"] == customer_account_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, claim_out)


@bp.post("/discrepancy-claims/<claim_id>/request-info")
def request_info(claim_id):
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    note = req_str(body, "info_request_note")
    claim = get_claim(claim_id)

    if claim["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Claim is not in SUBMITTED.")

    claim["info_request_note"] = note
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return respond(claim_out(claim))


@bp.post("/discrepancy-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    actor = authorize(ROLE_CUSTOMER)
    body = body_json()
    claimed_amount_cents = req_int(body, "claimed_amount_cents", minimum=1)
    claim = get_claim(claim_id)
    check_ownership(actor, claim["customer_account_id"])

    if claim["status"] != "INFO_REQUESTED":
        fail("ERR_INVALID_STATE", "Claim is not in INFO_REQUESTED.")

    # ladder 28 - the review loop is bounded
    if claim["review_round"] >= MAX_CLAIM_ROUNDS:
        fail("ERR_CLAIM_ROUND_LIMIT", "The claim has reached its review-round ceiling.")

    bag = db.bags.get(claim["sealed_bag_id"])
    declared = bag["declared_amount_cents"] if bag else 0
    if claimed_amount_cents > declared:
        fail(
            "ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED",
            "claimed_amount_cents exceeds the bag's declared_amount_cents.",
        )

    claim["claimed_amount_cents"] = claimed_amount_cents
    claim["review_round"] += 1
    claim["status"] = "SUBMITTED"
    touch(claim)
    return respond(claim_out(claim))


@bp.post("/discrepancy-claims/<claim_id>/approve")
def approve_claim(claim_id):
    actor = authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    resolution_amount_cents = req_int(body, "resolution_amount_cents", minimum=0)
    claim = get_claim(claim_id)

    if claim["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Claim is not in SUBMITTED.")

    _segregation_guard(actor, claim["sealed_bag_id"])

    # ladder 39 - a manager may grant less than was asked but never more
    if resolution_amount_cents > claim["claimed_amount_cents"]:
        fail("ERR_RESOLUTION_EXCEEDS_CLAIM", "resolution_amount_cents exceeds the claimed amount.")

    claim["resolution_amount_cents"] = resolution_amount_cents
    claim["decided_by_user_id"] = actor.user_id
    claim["status"] = "APPROVED"
    touch(claim)

    bag = db.bags.get(claim["sealed_bag_id"])
    if bag is not None:
        was_counted = bag["count_status"] == "COUNTED"
        bag["claim_adjustment_cents"] = resolution_amount_cents
        bag["count_status"] = "ADJUSTED"
        calc.recompute_bag_settlement(bag)
        touch(bag)

        ticket = db.tickets.get(bag["deposit_ticket_id"])
        if ticket is not None:
            calc.recompute_ticket_counted_total(ticket)
            if was_counted and bag["materiality_flag"]:
                ticket["material_variance_open_count"] -= 1
            touch(ticket)
    return respond(claim_out(claim))


@bp.post("/discrepancy-claims/<claim_id>/deny")
def deny_claim(claim_id):
    actor = authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    denial_reason = req_str(body, "denial_reason")
    claim = get_claim(claim_id)

    if claim["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Claim is not in SUBMITTED.")

    _segregation_guard(actor, claim["sealed_bag_id"])

    claim["denial_reason"] = denial_reason
    claim["decided_by_user_id"] = actor.user_id
    claim["status"] = "DENIED"
    touch(claim)

    account = db.customers.get(claim["customer_account_id"])
    if account is not None:
        account["denied_claim_count"] += 1
        touch(account)

    bag = db.bags.get(claim["sealed_bag_id"])
    if bag is not None and bag["materiality_flag"] and bag["count_status"] == "COUNTED":
        ticket = db.tickets.get(bag["deposit_ticket_id"])
        if ticket is not None:
            ticket["material_variance_open_count"] -= 1
            touch(ticket)
    return respond(claim_out(claim))
