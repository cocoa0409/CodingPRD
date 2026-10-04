from flask import Blueprint, request

import auth
import store
from domain import ser_claim
from envelope import success
from errors import err
from helpers import (
    new_row, touch, require_field, optional_field, require_enum,
    require_int, optional_int, date_to_str, d_from_str,
    whole_months_between,
)
from store import clock_today_date
from paginate import list_response

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"RATE_REDUCTION", "CLAIM_DEFERRAL", "LEASE_TERMINATION"}
SCRA_CAP_BPS = 600
MAX_RELIEF_PERIODS = 60
OPEN_ENDED_PERIODS = 12


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


def _get_claim(claim_id):
    cl = store.T["protection_claims"].get(claim_id)
    if cl is None:
        raise err("ERR_NOT_FOUND", 404, "protection claim not found")
    return cl


@bp.post("/membership/members/<member_id>/protection-claims")
def create_claim(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    obligation = require_field(body, "obligation_label")
    order_id = optional_field(body, "deployment_order_id")
    base_rate = optional_int(body, "base_rate_bps")
    monthly = optional_int(body, "monthly_interest_cents")
    if claim_type == "RATE_REDUCTION":
        if base_rate is None or monthly is None:
            raise err("ERR_INVALID_REQUEST", 400,
                      "base_rate_bps and monthly_interest_cents required for RATE_REDUCTION")

    if order_id is not None:
        o = store.T["deployment_orders"].get(order_id)
        if o is None or o["member_id"] != member_id:
            raise err("ERR_INVALID_REFERENCE", 422, "deployment_order_id does not resolve")

    row = new_row()
    row.update({
        "member_id": member_id,
        "deployment_order_id": order_id,
        "claim_type": claim_type,
        "obligation_label": obligation,
        "base_rate_bps": base_rate,
        "monthly_interest_cents": monthly,
        "periods_granted": None,
        "total_relief_cents": None,
        "approval_effective_date": None,
        "approved_by_officer_id": None,
        "status": "REQUESTED",
    })
    store.insert_row("protection_claims", row)
    return success(201, ser_claim(row), "object")


@bp.get("/membership/members/<member_id>/protection-claims")
def list_member_claims(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    rows = [x for x in store.T["protection_claims"].values() if x["member_id"] == member_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_claim(r) for r in rows], success)


@bp.get("/membership/protection-claims")
def list_claims():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    rows = list(store.T["protection_claims"].values())
    member_id = request.args.get("member_id")
    order_id = request.args.get("deployment_order_id")
    if member_id:
        rows = [x for x in rows if x["member_id"] == member_id]
    if order_id:
        rows = [x for x in rows if x["deployment_order_id"] == order_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_claim(r) for r in rows], success)


@bp.get("/membership/protection-claims/<claim_id>")
def get_claim(claim_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    cl = _get_claim(claim_id)
    if c["role"] == "Member" and c["uid"] != cl["member_id"]:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
    return success(200, ser_claim(cl), "object")


def _compute_rate_relief(claim, order, approval_date):
    """Returns (periods, total_relief_cents) or raises ERR_NO_RELIEF_AVAILABLE."""
    base = claim["base_rate_bps"]
    monthly = claim["monthly_interest_cents"]
    capped = min(base, SCRA_CAP_BPS)
    if base <= SCRA_CAP_BPS:
        raise err("ERR_NO_RELIEF_AVAILABLE", 422, "rate at or below statutory cap")
    if order["end_date"] is None:
        periods = OPEN_ENDED_PERIODS
    else:
        end_d = d_from_str(order["end_date"])
        periods = whole_months_between(approval_date, end_d)
        periods = min(periods, MAX_RELIEF_PERIODS)
    # per-period floor, then sum
    per_period = (monthly * (base - capped)) // base
    if per_period <= 0 or periods <= 0:
        raise err("ERR_NO_RELIEF_AVAILABLE", 422, "no relief available")
    return periods, per_period * periods


@bp.post("/membership/protection-claims/<claim_id>/decide")
def decide_claim(claim_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    cl = _get_claim(claim_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    optional_field(body, "decision_note")

    if cl["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "claim not in REQUESTED")

    # Priority 8: segregation of duties
    if c["uid"] == cl["member_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "officer cannot decide own claim")

    if decision == "DENY":
        cl["status"] = "DENIED"
        touch(cl)
        return success(200, ser_claim(cl), "object")

    # APPROVE ---------------------------------------------------------
    approval_date = clock_today_date()
    member = store.T["members"][cl["member_id"]]

    periods = None
    total = None
    if cl["claim_type"] == "RATE_REDUCTION":
        # Priority 17: SCRA eligibility
        order = None
        if cl["deployment_order_id"] is not None:
            order = store.T["deployment_orders"].get(cl["deployment_order_id"])
        if (order is None or order["status"] != "ACTIVE"
                or not order["scra_eligible"]):
            raise err("ERR_SCRA_NOT_ELIGIBLE", 422, "no ACTIVE scra_eligible deployment order")
        # Priority 28: positive relief (computed inside)
        periods, total = _compute_rate_relief(cl, order, approval_date)

        # Priority 18: relief cap
        exposure_cap = sum(
            e["exposure_cents"] for e in store.T["entitlements"].values()
            if e["member_id"] == member["id"] and e["status"] in ("OPEN", "GRANDFATHERED")
        )
        has_entitlements = any(
            e["member_id"] == member["id"] and e["status"] in ("OPEN", "GRANDFATHERED")
            for e in store.T["entitlements"].values()
        )
        if has_entitlements:
            gross = total
            bank_offset = sum(
                x["total_relief_cents"] for x in store.T["protection_claims"].values()
                if x["member_id"] == member["id"] and x["status"] == "APPROVED"
                and x["id"] != cl["id"]
            )
            net = max(0, gross - min(bank_offset, gross - 1))
            outstanding = sum(
                x["total_relief_cents"] for x in store.T["protection_claims"].values()
                if x["member_id"] == member["id"] and x["status"] == "APPROVED"
                and x["id"] != cl["id"]
            )
            if net + outstanding > exposure_cap:
                raise err("ERR_RELIEF_CAP_EXCEEDED", 422, "relief cap exceeded")

    cl["status"] = "APPROVED"
    cl["approval_effective_date"] = date_to_str(approval_date)
    cl["approved_by_officer_id"] = c["uid"]
    cl["periods_granted"] = periods
    cl["total_relief_cents"] = total
    touch(cl)

    # supersede cascade
    for x in store.T["protection_claims"].values():
        if (x["member_id"] == cl["member_id"]
                and x["obligation_label"] == cl["obligation_label"]
                and x["status"] == "APPROVED" and x["id"] != cl["id"]):
            x["status"] = "SUPERSEDED"
            touch(x)

    return success(200, ser_claim(cl), "object")
