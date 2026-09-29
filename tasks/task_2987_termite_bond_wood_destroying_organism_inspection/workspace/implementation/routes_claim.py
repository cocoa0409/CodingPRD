"""Damage claims: filing, verification pricing, adjudication and withdrawal
(PRD 3.10)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate, not_owner
from clock import clock
from common import (apply_filters, get_bond, get_claim, get_inspection, get_plan,
                    require_graphed)
from envelope import created, listing, ok
from errors import ApiError, invalid_request, invalid_state
from ledger import recompute_bond_money
from serialize import claim_out
from store import by_created, by_seq, claims_of, db, findings_of, new_row, touch

bp = Blueprint("claim", __name__)

READERS = ("ComplianceOfficer", "BranchManager", "ClaimsAdjudicator",
           "FieldInspector", "PropertyOwner")


def _damage_findings(inspection):
    return [f for f in by_seq(findings_of(inspection["id"]))
            if f["finding_type"] == "DAMAGE"]


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------

@bp.post("/damage-claims")
def file_claim():
    authenticate(("PropertyOwner",))
    payload = v.body()
    bond_id = v.get_string(payload, "bond_id")
    claim_type = v.get_enum(payload, "claim_type", calc.CLAIM_TYPES)
    claimed = v.get_money(payload, "claimed_damage_usd", minimum="0.01",
                          maximum="250000.00")
    expected = v.get_int(payload, "expected_bond_version")

    bond = get_bond(bond_id)

    if expected != bond["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_bond_version %d does not match the bond's %d"
                       % (expected, bond["version"]))
    if bond["status"] != "ACTIVE":
        raise ApiError("ERR_BOND_NOT_ACTIVE", 409,
                       "bond %s is %s and accepts no new claims"
                       % (bond["id"], bond["status"]))

    today = clock.today()
    if today < bond["current_term_start"] or today > bond["current_term_end"]:
        raise ApiError("ERR_DAMAGE_OUTSIDE_TERM", 422,
                       "the clock date falls outside the bond's current coverage window")

    row = new_row({
        "bond_id": bond["id"],
        "verifying_inspection_id": None,
        "claim_type": claim_type,
        "claimed_damage_usd": calc.r2(claimed),
        "reported_at": clock.now(),
        "status": "SUBMITTED",
        "exclusion_basis": None,
        "excluded_pre_existing_usd": calc.ZERO,
        "eligible_damage_usd": calc.ZERO,
        "deductible_usd": calc.ZERO,
        "projected_payout_usd": calc.ZERO,
        "approved_payout_usd": calc.ZERO,
        "denial_reason_code": None,
        "adjudicated_by_user_id": None,
    })
    db.claims[row["id"]] = row
    touch(bond)
    return created(claim_out(row))


@bp.get("/damage-claims/<cid>")
def read_claim(cid):
    authenticate(READERS)
    return ok(claim_out(get_claim(cid)))


@bp.get("/damage-claims")
def list_claims():
    authenticate(READERS)
    rows = apply_filters(by_created(list(db.claims.values())), {
        "bond_id": v.query_str("bond_id"),
        "verifying_inspection_id": v.query_str("verifying_inspection_id"),
        "status": v.query_str("status"),
        "claim_type": v.query_str("claim_type"),
    })
    return listing(rows, claim_out)


# --------------------------------------------------------------------------
# verification: exclusion arithmetic and the reserve
# --------------------------------------------------------------------------

@bp.post("/damage-claims/<cid>/attach-verification")
def attach_verification(cid):
    user_id, _role = authenticate(("FieldInspector",))
    claim = get_claim(cid)
    payload = v.body()
    inspection_id = v.get_string(payload, "verifying_inspection_id")
    inspection = get_inspection(inspection_id)

    # Stage 3, evaluated as soon as the graph it speaks about exists.
    if inspection["inspector_id"] != user_id:
        raise not_owner("only the inspector who signed the graph may attach it")

    bond = get_bond(claim["bond_id"])
    if claim["status"] != "SUBMITTED":
        raise invalid_state("DamageClaim",
                            "only a SUBMITTED claim may take a verifying graph")
    if bond["status"] != "ACTIVE":
        raise invalid_state("Bond", "the bond is no longer ACTIVE")

    # Stage 18.
    plan = get_plan(bond["treatment_plan_id"])
    if inspection["inspector_id"] == plan["applicator_id"]:
        raise ApiError("ERR_VERIFIER_IS_APPLICATOR", 422,
                       "the treating applicator may not certify the damage claimed "
                       "against that treatment")

    # Stage 20.
    require_graphed(inspection)
    if inspection["property_id"] != bond["property_id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the verifying graph belongs to another structure")

    # Stage 21.
    for other in claims_of(bond["id"]):
        if other["id"] != claim["id"] and other["status"] == "UNDER_ADJUDICATION":
            raise ApiError("ERR_CLAIM_ALREADY_RESERVED", 409,
                           "another claim on this bond already holds a reserve")

    # Stage 23.
    if bond["coverage_tier"] == "REPAIR_AND_RETREAT" \
            and bond["remaining_repair_cap_usd"] <= calc.ZERO:
        raise ApiError("ERR_REPAIR_CAP_EXHAUSTED", 409,
                       "the bond's repair ceiling leaves nothing to reserve against")

    basis, eligible, excluded = calc.claim_exclusion(
        claim["claimed_damage_usd"], inspection, _damage_findings(inspection))
    deductible, projected = calc.claim_waterfall(
        eligible, bond["repair_liability_cap_usd"], bond["claims_paid_to_date_usd"],
        bond["reserved_claim_amount_usd"])

    claim["verifying_inspection_id"] = inspection["id"]
    claim["exclusion_basis"] = basis
    claim["eligible_damage_usd"] = eligible
    claim["excluded_pre_existing_usd"] = excluded
    claim["deductible_usd"] = deductible
    claim["projected_payout_usd"] = projected
    claim["status"] = "UNDER_ADJUDICATION"
    touch(claim)

    recompute_bond_money(bond)
    touch(bond)
    return ok(claim_out(claim))


# --------------------------------------------------------------------------
# adjudication
# --------------------------------------------------------------------------

@bp.post("/damage-claims/<cid>/adjudicate")
def adjudicate(cid):
    user_id, _role = authenticate(("ClaimsAdjudicator",))
    claim = get_claim(cid)
    payload = v.body()
    decision = v.get_enum(payload, "decision", calc.DECISIONS)
    reason = v.get_enum(payload, "denial_reason_code", calc.DENIAL_REASONS,
                        required=False, default=None)
    if decision == "DENY" and reason is None:
        raise invalid_request("denial_reason_code is required when decision is DENY")

    bond = get_bond(claim["bond_id"])
    if claim["status"] != "UNDER_ADJUDICATION":
        raise invalid_state("DamageClaim",
                            "only an UNDER_ADJUDICATION claim may be adjudicated")
    if bond["status"] != "ACTIVE":
        raise invalid_state("Bond", "the bond is no longer ACTIVE")

    # Stage 17.
    if user_id == bond["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the underwriting operator may not adjudicate this claim")

    if decision == "APPROVE_REPAIR":
        # Stage 21 then stage 23.
        if bond["coverage_tier"] != "REPAIR_AND_RETREAT":
            raise ApiError("ERR_TIER_EXCLUDES_REPAIR", 422,
                           "a RETREAT_ONLY bond cannot pay for repairs")
        reserved_excluding_this = (bond["reserved_claim_amount_usd"]
                                  - claim["projected_payout_usd"])
        _deductible, projected = calc.claim_waterfall(
            claim["eligible_damage_usd"], bond["repair_liability_cap_usd"],
            bond["claims_paid_to_date_usd"], reserved_excluding_this)
        if projected <= calc.ZERO:
            raise ApiError("ERR_REPAIR_CAP_EXHAUSTED", 409,
                           "the projected payout came out at 0.00")
        claim["status"] = "APPROVED_REPAIR"
        claim["approved_payout_usd"] = projected
    elif decision == "APPROVE_RETREAT_ONLY":
        claim["status"] = "APPROVED_RETREAT_ONLY"
        claim["approved_payout_usd"] = calc.ZERO
        bond["retreat_required"] = True
        bond["retreat_credit_count"] = bond["retreat_credit_count"] + 1
    else:
        claim["status"] = "DENIED"
        claim["approved_payout_usd"] = calc.ZERO
        claim["denial_reason_code"] = reason

    claim["adjudicated_by_user_id"] = user_id
    touch(claim)

    recompute_bond_money(bond)
    touch(bond)
    return ok(claim_out(claim))


# --------------------------------------------------------------------------
# withdrawal
# --------------------------------------------------------------------------

@bp.post("/damage-claims/<cid>/withdraw")
def withdraw(cid):
    user_id, _role = authenticate(("PropertyOwner",))
    claim = get_claim(cid)
    bond = get_bond(claim["bond_id"])
    if bond["property_id"] != user_id:
        raise not_owner("only the covered structure's owner may withdraw this claim")

    if claim["status"] not in ("SUBMITTED", "UNDER_ADJUDICATION"):
        raise invalid_state("DamageClaim",
                            "a %s claim may not be withdrawn" % claim["status"])

    held_reserve = claim["status"] == "UNDER_ADJUDICATION"
    claim["status"] = "WITHDRAWN"
    if held_reserve:
        claim["approved_payout_usd"] = calc.ZERO
    touch(claim)

    if held_reserve:
        recompute_bond_money(bond)
        touch(bond)

    return ok(claim_out(claim))
