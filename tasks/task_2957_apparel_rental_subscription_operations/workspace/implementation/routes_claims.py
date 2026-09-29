"""Damage claims: assessment, waiver absorption, charging and disputes."""
from flask import Blueprint

import calc
import core
import serialize
import services
from core import (CLAIM_STATES, CLAIM_TERMINAL, DB, DISPUTE_WINDOW_DAYS,
                  MAX_DISPUTE_ROUNDS, RESOLUTIONS, date_add, fail, now_iso, ok,
                  ok_list, today_str)
from guards import (begin, body_json, enum_query, lookup, pagination, paginate,
                    require_owner, sort_rows, str_query, validate)

bp = Blueprint("claims", __name__)

READ_ROLES = ["Member", "WarehouseTech", "ClaimsAdjuster", "PlatformAdmin"]


def _context(claim):
    member = DB["members"].get(claim["member_id"])
    unit = DB["rental_units"].get(claim["rental_unit_id"])
    style = DB["styles"].get(unit["style_id"]) if unit is not None else None
    plan = (DB["membership_plans"].get(member["membership_plan_id"])
            if member is not None else None)
    return member, unit, style, plan


def _price(claim, exclude_self=True):
    """Apply the damage_fee_assessment arithmetic to the claim in place."""
    member, unit, style, plan = _context(claim)
    used = (calc.member_waiver_used_excluding(claim["member_id"], claim["id"])
            if exclude_self else calc.member_waiver_used(claim["member_id"]))
    priced = calc.damage_fee(style, unit, claim["severity"], member, plan, used)
    claim.update(priced)
    return priced


def _post_charge_pair(claim, member):
    services.append_ledger(member, "DAMAGE_FEE", claim["gross_fee_cents"],
                           memo="Damage fee", damage_claim_id=claim["id"])
    if claim["waiver_applied_cents"] > 0:
        services.append_ledger(member, "WAIVER_CREDIT",
                               -claim["waiver_applied_cents"],
                               memo="Damage waiver credit",
                               damage_claim_id=claim["id"])


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/damage-claims/<claim_id>")
def get_claim(claim_id):
    ctx = begin(READ_ROLES)
    row = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    require_owner(ctx, row["member_id"])
    return ok(serialize.claim_out(row))


@bp.get("/damage-claims")
def list_claims():
    ctx = begin(READ_ROLES)
    state = enum_query("state", CLAIM_STATES)
    reservation_id = str_query("reservation_id")
    unit_id = str_query("rental_unit_id")
    member_id = str_query("member_id")
    inspection_id = str_query("inspection_id")
    if ctx.role == "Member":
        if member_id is not None and member_id != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Members may only read their own rows")
        member_id = ctx.user_id
    limit, offset = pagination()
    rows = []
    for c in DB["damage_claims"].values():
        if reservation_id is not None and c["reservation_id"] != reservation_id:
            continue
        if unit_id is not None and c["rental_unit_id"] != unit_id:
            continue
        if member_id is not None and c["member_id"] != member_id:
            continue
        if inspection_id is not None and c["inspection_id"] != inspection_id:
            continue
        if state is not None and c["state"] != state:
            continue
        rows.append(c)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.claim_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------
@bp.post("/damage-claims/<claim_id>/assessment")
def assess_claim(claim_id):
    begin(["ClaimsAdjuster"])
    claim = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body_json()
    if claim["state"] in CLAIM_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Claim is %s" % claim["state"])
    if claim["state"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "An assessment is not declared from %s" % claim["state"])
    # The linked job must carry at least one inspection
    has_inspection = False
    for job in DB["reverse_logistics_jobs"].values():
        if (job["rental_unit_id"] == claim["rental_unit_id"]
                and job["reservation_id"] == claim["reservation_id"]):
            if calc.inspections_of_job(job["id"]):
                has_inspection = True
                break
    if not has_inspection:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The linked job carries no inspection to price")
    _price(claim)
    claim["state"] = "ASSESSED"
    claim["assessed_at"] = now_iso()
    services.touch(claim)
    return ok(serialize.claim_out(claim))


# ---------------------------------------------------------------------------
# Waiver absorption
# ---------------------------------------------------------------------------
@bp.post("/damage-claims/<claim_id>/waiver")
def waive_claim(claim_id):
    begin(["ClaimsAdjuster"])
    claim = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body_json()
    member, unit, style, plan = _context(claim)
    if claim["state"] in CLAIM_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Claim is %s" % claim["state"])
    if claim["state"] != "ASSESSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Absorption is not declared from %s" % claim["state"])
    # Rank 52
    used = calc.member_waiver_used(claim["member_id"])
    available = (plan["waiver_coverage_cents"] - used
                 + claim["waiver_applied_cents"])
    if not member["waiver_active"] or available < claim["gross_fee_cents"]:
        fail("ERR_WAIVER_NOT_AVAILABLE",
             "The member's damage waiver cannot absorb this claim")
    claim["state"] = "WAIVED"
    claim["waiver_applied_cents"] = claim["gross_fee_cents"]
    claim["net_fee_cents"] = 0
    services.touch(claim)
    # Audit-only zero-amount credit; the balance never moves
    services.append_ledger(member, "WAIVER_CREDIT", 0,
                           memo="Claim absorbed under the damage waiver",
                           damage_claim_id=claim["id"])
    return ok(serialize.claim_out(claim))


# ---------------------------------------------------------------------------
# Charge
# ---------------------------------------------------------------------------
@bp.post("/damage-claims/<claim_id>/charge")
def charge_claim(claim_id):
    begin(["ClaimsAdjuster"])
    claim = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body_json()
    member, unit, style, plan = _context(claim)
    if member is not None and member["status"] == "CANCELLED":
        fail("ERR_MEMBER_NOT_ACTIVE", "The member's subscription is CANCELLED")
    if claim["state"] in CLAIM_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Claim is %s" % claim["state"])
    if claim["state"] != "ASSESSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A charge is not declared from %s" % claim["state"])
    # Rank 53
    if claim["net_fee_cents"] <= 0:
        fail("ERR_NOTHING_TO_CHARGE", "This claim has nothing left to bill")
    claim["state"] = "CHARGED"
    claim["charged_at"] = now_iso()
    services.touch(claim)
    _post_charge_pair(claim, member)
    services.check_delinquency(member)
    return ok(serialize.claim_out(claim))


# ---------------------------------------------------------------------------
# Dispute
# ---------------------------------------------------------------------------
@bp.post("/damage-claims/<claim_id>/disputes")
def dispute_claim(claim_id):
    ctx = begin(["Member"])
    claim = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    require_owner(ctx, claim["member_id"])
    body = body_json()
    data = validate(body, [
        {"name": "dispute_reason", "kind": "str", "required": True, "minlen": 1},
    ])
    if claim["state"] in CLAIM_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Claim is %s" % claim["state"])
    if claim["state"] not in ("ASSESSED", "CHARGED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A dispute is not declared from %s" % claim["state"])
    # Rank 29
    if claim["dispute_round"] >= MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED",
             "This claim has consumed every permitted dispute round")
    # Rank 30 — inclusive boundary, and only for a charged claim
    if claim["state"] == "CHARGED" and claim["charged_at"]:
        charged_date = core.parse_instant(claim["charged_at"]).strftime("%Y-%m-%d")
        if today_str() > date_add(charged_date, DISPUTE_WINDOW_DAYS):
            fail("ERR_DISPUTE_WINDOW_CLOSED",
                 "The dispute window for this charge has closed")
    claim["state"] = "DISPUTED"
    claim["dispute_round"] += 1
    claim["dispute_reason"] = data["dispute_reason"]
    services.touch(claim)
    return ok(serialize.claim_out(claim))


# ---------------------------------------------------------------------------
# Dispute resolution
# ---------------------------------------------------------------------------
@bp.post("/damage-claims/<claim_id>/dispute-resolution")
def resolve_dispute(claim_id):
    begin(["ClaimsAdjuster"])
    claim = lookup("damage_claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "resolution", "kind": "enum", "required": True,
         "values": RESOLUTIONS},
    ])
    member, unit, style, plan = _context(claim)
    if claim["state"] in CLAIM_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Claim is %s" % claim["state"])
    if claim["state"] != "DISPUTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A dispute resolution is not declared from %s" % claim["state"])
    verdict = data["resolution"]

    if verdict == "PARTIAL":
        was_charged = claim["charged_at"] is not None
        claim["state"] = "ASSESSED"
        claim["resolution"] = "PARTIAL"
        claim["severity"] = calc.DOWNGRADE[claim["severity"]]
        _price(claim)
        services.touch(claim)
        if was_charged and member is not None:
            prior_sum = calc.claim_ledger_sum(claim["id"])
            services.append_ledger(member, "DISPUTE_REVERSAL", -prior_sum,
                                   memo="Dispute reversal",
                                   damage_claim_id=claim["id"])
            _post_charge_pair(claim, member)
            services.check_delinquency(member)
            services.check_delinquency_recovery(member)
        return ok(serialize.claim_out(claim))

    if verdict == "UPHELD":
        # Rank 53
        if claim["net_fee_cents"] <= 0:
            fail("ERR_NOTHING_TO_CHARGE", "This claim has nothing left to bill")
        claim["state"] = "CHARGED"
        claim["resolution"] = "UPHELD"
        if claim["charged_at"] is None:
            claim["charged_at"] = now_iso()
        services.touch(claim)
        if member is not None and not calc.claim_has_unreversed_damage_fee(
                claim["id"]):
            _post_charge_pair(claim, member)
            services.check_delinquency(member)
        return ok(serialize.claim_out(claim))

    # OVERTURNED
    claim["state"] = "DISMISSED"
    claim["resolution"] = "OVERTURNED"
    claim["net_fee_cents"] = 0
    services.touch(claim)
    if member is not None:
        has_fee = any(e["kind"] == "DAMAGE_FEE"
                      for e in calc.ledger_of_claim(claim["id"]))
        if has_fee:
            prior_sum = calc.claim_ledger_sum(claim["id"])
            services.append_ledger(member, "DISPUTE_REVERSAL", -prior_sum,
                                   memo="Dispute overturned",
                                   damage_claim_id=claim["id"])
        services.check_delinquency_recovery(member)
    return ok(serialize.claim_out(claim))
