"""Credit assessment + retainer deposit endpoints (PRD 3.8)."""

from flask import Blueprint, request

import db
from db import stamp_new, bump, now_iso
from errors import (
    ApiError, invalid, forbidden,
    ERR_REFUND_EXCEEDS_BALANCE,
)
from middleware import caller, admit, body
from response import ok_object, paginate, sort_by_created
from services import money
from services.validate import resolve, is_int

bp = Blueprint("credit", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")


@bp.post("/intake/matters/<mid>/credit-assessments")
def create_assessment(mid):
    _, role = caller()
    admit(role, ("BillingClerk",))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 12: score must be an integer in 300..850 inclusive.
    score = data.get("score")
    if not is_int(score) or not (300 <= score <= 850):
        raise invalid("score must be an integer in 300..850")

    assessment = stamp_new({
        "matter_id": matter["id"],
        "score": score,
        "band": money.credit_band(score),
        "assessed_at": now_iso(),
    })
    db.store.credit_assessments[assessment["id"]] = assessment

    # A new assessment recomputes the matter's retainer requirement whenever
    # a deposit already exists, and re-derives the deposit's status (which
    # may regress FUNDED -> PARTIALLY_FUNDED with no client call).
    deposit = money.deposit_for_matter(matter["id"])
    if deposit is not None:
        money.refresh_deposit(deposit)

    return ok_object(assessment, 201)


@bp.get("/intake/matters/<mid>/credit-assessments")
def list_assessments(mid):
    _, role = caller()
    admit(role, STAFF)
    resolve(db.store.matters, mid)
    rows = [a for a in db.store.credit_assessments.values()
            if a["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.get("/intake/matters/<mid>/retainer-deposits")
def list_deposits(mid):
    user_id, role = caller()
    admit(role, STAFF + ("Client",))
    matter = resolve(db.store.matters, mid)
    # Tier 5 ownership: a Client reads the deposit of its own matters only.
    if role == "Client" and user_id != matter["client_party_id"]:
        raise forbidden("Client may read only its own matters' deposits")
    rows = [d for d in db.store.retainer_deposits.values()
            if d["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/retainer-deposits/<did>/transition")
def deposit_transition(did):
    _, role = caller()
    admit(role, ("BillingClerk",))
    data = body()
    action = data.get("action")
    deposit = resolve(db.store.retainer_deposits, did)

    amount = data.get("amount_cents")

    if action == "FUND":
        # Tier 12: amount must be a positive integer.
        if not is_int(amount) or amount <= 0:
            raise invalid("amount_cents must be a positive integer")
        deposit["funded_total_cents"] += amount
        deposit["received_cents"] = (deposit["funded_total_cents"]
                                     - deposit["refunded_total_cents"])
        deposit["status"] = money.derive_deposit_status(deposit)
        bump(deposit)
        return ok_object(deposit)

    if action == "REFUND":
        # Tier 11: refund may not exceed the held balance (checked for
        # usable integer amounts; the shape tier handles the rest).
        if is_int(amount) and amount > deposit["received_cents"]:
            raise ApiError(ERR_REFUND_EXCEEDS_BALANCE, 422,
                           "REFUND amount exceeds the held balance")
        # Tier 12: amount must be a positive integer.
        if not is_int(amount) or amount <= 0:
            raise invalid("amount_cents must be a positive integer")
        deposit["refunded_total_cents"] += amount
        deposit["received_cents"] = (deposit["funded_total_cents"]
                                     - deposit["refunded_total_cents"])
        deposit["status"] = money.derive_deposit_status(deposit)
        bump(deposit)
        return ok_object(deposit)

    raise invalid("action must be FUND or REFUND")
