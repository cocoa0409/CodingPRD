"""Construction damage claims (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import add_days, bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("claims", __name__)

READ_ROLES = ("ProgramManager", "ClaimsAssessor", "ClaimsApprover", "Subscriber")


def _campaign_of_appointment(appointment):
    preorder = db.preorders.get(appointment["preorder_id"])
    if preorder is None:
        return None
    zone = db.build_zones.get(preorder["build_zone_id"])
    return db.campaigns.get(zone["campaign_id"]) if zone else None


@bp.post("/damage-claims")
def file_claim():
    user_id, role = auth.gate(("Subscriber",))
    data = shape.body()
    appointment = listing.resolve(data, "install_appointment_id", "install_appointments")
    address = listing.resolve(data, "service_address_id", "service_addresses")
    account = listing.resolve(data, "claimant_account_id", "accounts")
    if account is not None:
        auth.own(user_id, role, account["id"])
    shape.req_id(data, "install_appointment_id")
    shape.req_id(data, "service_address_id")
    shape.req_id(data, "claimant_account_id")
    damage_type = shape.req_enum(data, "damage_type", calc.DAMAGE_TYPES)
    claimed = shape.req_int(data, "claimed_amount_cents", 1)
    description = shape.opt_str(data, "description", 1, 500)
    max_appeals = shape.opt_int(data, "max_appeals", 0, 3, 1)
    preorder = db.preorders.get(appointment["preorder_id"])
    if preorder is None or preorder["service_address_id"] != address["id"]:
        raise ApiError(
            "ERR_ADDRESS_LINKAGE_MISMATCH",
            "the appointment does not serve the supplied address",
        )
    if appointment["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INSTALL_APPOINTMENT_STATE_INVALID",
            "a claim may only be filed against a completed visit",
        )
    campaign = _campaign_of_appointment(appointment)
    if not appointment["restoration_required"] or appointment["completed_at"] is None:
        raise ApiError(
            "ERR_CLAIM_FILING_WINDOW_EXPIRED",
            "this visit never disturbed the property",
        )
    deadline = add_days(appointment["completed_at"], campaign["claim_filing_window_days"])
    if now() > deadline:
        raise ApiError("ERR_CLAIM_FILING_WINDOW_EXPIRED", "the filing window has closed")
    row = new_row(
        {
            "install_appointment_id": appointment["id"],
            "service_address_id": address["id"],
            "claimant_account_id": account["id"],
            "damage_type": damage_type,
            "claimed_amount_cents": claimed,
            "description": description,
            "status": "FILED",
            "filed_at": now(),
            "assessed_amount_cents": None,
            "assessment_variant": None,
            "assessed_by_user_id": None,
            "decided_by_user_id": None,
            "appeal_count": 0,
            "max_appeals": max_appeals,
            "denial_reason": None,
            "paid_at": None,
        }
    )
    insert("damage_claims", row)
    return envelope.created(serialize.damage_claim(row))


@bp.get("/damage-claims/<claim_id>")
def read_claim(claim_id):
    auth.gate(READ_ROLES)
    row = must_find("damage_claims", claim_id)
    return envelope.ok(serialize.damage_claim(row))


@bp.get("/damage-claims")
def list_claims():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("damage_claims")),
        (
            listing.fk("install_appointment_id", "install_appointment_id", "install_appointments"),
            listing.fk("service_address_id", "service_address_id", "service_addresses"),
            listing.fk("claimant_account_id", "claimant_account_id", "accounts"),
            listing.enum("damage_type", "damage_type", calc.DAMAGE_TYPES),
            listing.enum("status", "status", calc.CLAIM_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.damage_claim)


@bp.post("/damage-claims/<claim_id>/assessment")
def assess(claim_id):
    user_id, _role = auth.gate(("ClaimsAssessor",))
    claim = must_find("damage_claims", claim_id)
    if claim["status"] not in ("FILED", "UNDER_ASSESSMENT"):
        raise ApiError(
            "ERR_DAMAGE_CLAIM_STATE_INVALID", "this claim is not open for assessment"
        )
    appointment = db.install_appointments.get(claim["install_appointment_id"])
    campaign = _campaign_of_appointment(appointment)
    amount, variant = calc.assess_claim(claim, appointment, campaign)
    claim["status"] = "UNDER_ASSESSMENT"
    claim["assessed_amount_cents"] = amount
    claim["assessment_variant"] = variant
    claim["assessed_by_user_id"] = user_id
    bump(claim)
    return envelope.ok(serialize.damage_claim(claim))


@bp.post("/damage-claims/<claim_id>/decision")
def decide_claim(claim_id):
    user_id, _role = auth.gate(("ClaimsApprover",))
    claim = must_find("damage_claims", claim_id)
    if claim["assessed_by_user_id"] is not None and claim["assessed_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the operator who assessed this claim may not decide it",
        )
    data = shape.body()
    decision = shape.req_enum(data, "decision", calc.CLAIM_DECISIONS)
    reason = shape.opt_str(data, "denial_reason", 1, 240)
    if decision == "DENY" and reason is None:
        shape.bad("denial_reason", "is required for a denial")
    if claim["status"] != "UNDER_ASSESSMENT":
        raise ApiError(
            "ERR_DAMAGE_CLAIM_STATE_INVALID", "only an assessed claim can be decided"
        )
    claim["decided_by_user_id"] = user_id
    if decision == "APPROVE":
        claim["status"] = "PAID"
        claim["paid_at"] = now()
        calc.append_entry(
            claim["claimant_account_id"],
            "CLAIM_PAYOUT",
            claim["assessed_amount_cents"],
            "damage claim payout",
            damage_claim_id=claim["id"],
        )
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = reason
    bump(claim)
    return envelope.ok(serialize.damage_claim(claim))


@bp.post("/damage-claims/<claim_id>/appeal")
def appeal(claim_id):
    user_id, role = auth.gate(("Subscriber",))
    claim = must_find("damage_claims", claim_id)
    auth.own(user_id, role, claim["claimant_account_id"])
    if claim["status"] != "DENIED":
        raise ApiError("ERR_DAMAGE_CLAIM_STATE_INVALID", "only a denied claim can be appealed")
    if claim["appeal_count"] >= claim["max_appeals"]:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED", "the appeal allowance is exhausted")
    claim["status"] = "UNDER_ASSESSMENT"
    claim["appeal_count"] += 1
    claim["denial_reason"] = None
    bump(claim)
    return envelope.ok(serialize.damage_claim(claim))
