"""Members, membership lifecycle, fee settlements and the fee ledger."""
from flask import Blueprint

import calc
import serialize
import services
from core import (CATEGORIES, DB, LEDGER_KINDS, MEMBER_STATUSES, RISK_VARIANTS,
                  fail, ok, ok_list)
from guards import (begin, body_json, check_duplicate, enum_query, fk, lookup,
                    pagination, paginate, require_own_member_id, require_owner,
                    sort_rows, str_query, validate)

bp = Blueprint("members", __name__)

RISK_BANDS = ["LOW", "ELEVATED", "HIGH"]


def _reject_terminal(member):
    if member["status"] == "CANCELLED":
        fail("ERR_RESOURCE_TERMINAL", "Membership is CANCELLED")


# ---------------------------------------------------------------------------
# Enrolment and reads
# ---------------------------------------------------------------------------
@bp.post("/members")
def create_member():
    begin(["PlatformAdmin"])
    body = body_json()
    plan = fk(body, "membership_plan_id", "membership_plans", "ERR_PLAN_NOT_FOUND")
    data = validate(body, [
        {"name": "membership_plan_id", "kind": "str", "required": True},
        {"name": "email", "kind": "str", "required": True, "minlen": 1},
        {"name": "full_name", "kind": "str", "required": True, "minlen": 1},
        {"name": "waiver_active", "kind": "bool", "default": False},
        {"name": "preferred_categories", "kind": "enum_list", "values": CATEGORIES,
         "default": []},
        {"name": "size_profile", "kind": "str", "maxlen": 8, "default": ""},
    ])
    if "@" not in data["email"]:
        fail("ERR_INVALID_REQUEST", "Field 'email' must contain an at-sign")
    check_duplicate("members", "email", data["email"])
    row = services.base_row("members")
    row.update({
        "membership_plan_id": plan["id"],
        "email": data["email"],
        "full_name": data["full_name"],
        "status": "ACTIVE",
        "waiver_active": data["waiver_active"],
        "preferred_categories": list(data["preferred_categories"]),
        "size_profile": data["size_profile"],
    })
    DB["members"][row["id"]] = row
    return ok(serialize.member_out(row), 201)


@bp.get("/members/<member_id>")
def get_member(member_id):
    ctx = begin(["Member", "ClaimsAdjuster", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    row = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(serialize.member_out(row))


@bp.get("/members")
def list_members():
    begin(["ClaimsAdjuster", "PlatformAdmin"])
    status = enum_query("status", MEMBER_STATUSES)
    band = enum_query("damage_risk_band", RISK_BANDS)
    plan_id = str_query("membership_plan_id")
    limit, offset = pagination()
    rows = []
    for r in DB["members"].values():
        if plan_id is not None and r["membership_plan_id"] != plan_id:
            continue
        if status is not None and r["status"] != status:
            continue
        if band is not None and calc.damage_risk(r, "LIFETIME")["damage_risk_band"] != band:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.member_out)
    return ok_list(items, limit, offset, total)


@bp.patch("/members/<member_id>/style-preferences")
def patch_preferences(member_id):
    ctx = begin(["Member"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "preferred_categories", "kind": "enum_list", "values": CATEGORIES},
        {"name": "size_profile", "kind": "str", "maxlen": 8},
    ])
    _reject_terminal(member)
    if "preferred_categories" in data:
        member["preferred_categories"] = list(data["preferred_categories"])
    if "size_profile" in data:
        member["size_profile"] = data["size_profile"]
    services.touch(member)
    return ok(serialize.member_out(member))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
@bp.post("/members/<member_id>/pause")
def pause_member(member_id):
    ctx = begin(["Member", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if member["status"] == "CANCELLED":
        fail("ERR_RESOURCE_TERMINAL", "Membership is CANCELLED")
    if member["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Pause is not declared from %s" % member["status"])
    if calc.member_units_out(member["id"]) != 0:
        fail("ERR_UNITS_STILL_OUT", "Member still holds committed units")
    member["status"] = "PAUSED"
    services.touch(member)
    return ok(serialize.member_out(member))


@bp.post("/members/<member_id>/resume")
def resume_member(member_id):
    ctx = begin(["Member", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if member["status"] == "CANCELLED":
        fail("ERR_RESOURCE_TERMINAL", "Membership is CANCELLED")
    if member["status"] != "PAUSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Resume is not declared from %s" % member["status"])
    member["status"] = "ACTIVE"
    services.touch(member)
    return ok(serialize.member_out(member))


@bp.post("/members/<member_id>/cancellation")
def cancel_member(member_id):
    ctx = begin(["Member", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if member["status"] == "CANCELLED":
        fail("ERR_RESOURCE_TERMINAL", "Membership is CANCELLED")
    if member["status"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Cancellation is not declared from %s" % member["status"])
    if calc.member_outstanding(member["id"]) != 0:
        fail("ERR_OUTSTANDING_BALANCE", "Member still owes fees")
    from_paused = member["status"] == "PAUSED"
    member["status"] = "CANCELLED"
    services.touch(member)
    if from_paused:
        services.unwind_member_commitments(member, cancel_waitlisted=True,
                                          release_matched=False, promote=False)
    else:
        services.unwind_member_commitments(member, cancel_waitlisted=True,
                                          release_matched=True, promote=False)
    return ok(serialize.member_out(member))


@bp.post("/members/<member_id>/fee-settlements")
def settle_fees(member_id):
    ctx = begin(["Member", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "amount_cents", "kind": "int", "required": True},
        {"name": "memo", "kind": "str", "default": None},
    ])
    if member["status"] == "CANCELLED":
        fail("ERR_RESOURCE_TERMINAL", "Membership is CANCELLED")
    balance = calc.member_outstanding(member["id"])
    amount = data["amount_cents"]
    if amount <= 0 or amount > balance:
        fail("ERR_SETTLEMENT_EXCEEDS_BALANCE",
             "amount_cents must be > 0 and no greater than the outstanding balance")
    entry = services.append_ledger(member, "SETTLEMENT_PAYMENT", -amount,
                                   memo=data.get("memo"))
    services.check_delinquency_recovery(member)
    return ok(serialize.ledger_out(entry), 201)


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------
@bp.get("/members/<member_id>/damage-risk")
def member_damage_risk(member_id):
    ctx = begin(["Member", "ClaimsAdjuster", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    variant = enum_query("variant", RISK_VARIANTS) or "LIFETIME"
    risk = calc.damage_risk(member, variant)
    risk.pop("closed_reservation_count", None)
    return ok(risk)


@bp.get("/members/<member_id>/personalization-summary")
def member_personalization(member_id):
    ctx = begin(["Member", "PlatformAdmin"])
    require_own_member_id(ctx, member_id)
    member = lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(calc.personalization(member))


# ---------------------------------------------------------------------------
# Fee ledger
# ---------------------------------------------------------------------------
@bp.get("/fee-ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    ctx = begin(["Member", "ClaimsAdjuster", "PlatformAdmin"])
    row = lookup("fee_ledger_entries", entry_id, "ERR_FEE_ENTRY_NOT_FOUND")
    require_owner(ctx, row["member_id"])
    return ok(serialize.ledger_out(row))


@bp.get("/fee-ledger-entries")
def list_ledger_entries():
    ctx = begin(["Member", "ClaimsAdjuster", "PlatformAdmin"])
    kind = enum_query("kind", LEDGER_KINDS)
    member_id = str_query("member_id")
    claim_id = str_query("damage_claim_id")
    reservation_id = str_query("reservation_id")
    if ctx.role == "Member":
        if member_id is not None and member_id != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Members may only read their own entries")
        member_id = ctx.user_id
    limit, offset = pagination()
    rows = []
    for r in DB["fee_ledger_entries"].values():
        if member_id is not None and r["member_id"] != member_id:
            continue
        if claim_id is not None and r["damage_claim_id"] != claim_id:
            continue
        if reservation_id is not None and r["reservation_id"] != reservation_id:
            continue
        if kind is not None and r["kind"] != kind:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.ledger_out)
    return ok_list(items, limit, offset, total)
