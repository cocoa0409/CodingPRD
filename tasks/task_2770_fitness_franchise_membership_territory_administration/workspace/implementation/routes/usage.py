"""Cross-club guest usage batches and inter-club usage settlements."""
from flask import Blueprint

import calc
import validate as v
from auth import guard
from envelope import ok, created
from errors import ApiError
from helpers import ALL_ROLES, get_agreement, get_club, get_guest_event, get_settlement, paged
from store import db, common_fields, ledger_fields, clock_date_str, touch, by_seq

bp = Blueprint("usage", __name__)

ADMIN = ["BrandAdministrator"]


# --------------------------------------------------------------------------
# guest usage batches
# --------------------------------------------------------------------------
@bp.post("/franchise/guest-usage-events")
def create_guest_usage():
    guard(["ClubManager", "BrandAdministrator"])
    b = v.body()
    agreement_id = v.req_id(b, "agreement_id")
    host_club_id = v.req_id(b, "host_club_id")
    period_month = v.req_month(b, "period_month")
    visit_count = v.req_int(b, "visit_count", minimum=1)

    agreement = get_agreement(agreement_id)
    host_club = get_club(host_club_id)

    if host_club["status"] != "OPEN":
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")
    if host_club["equipment_compliance_state"] == "NON_COMPLIANT":
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")

    if not agreement["multi_club_access"]:
        raise ApiError("ERR_GUEST_VISIT_NOT_ALLOWED")
    if host_club_id == agreement["home_club_id"]:
        raise ApiError("ERR_GUEST_VISIT_NOT_ALLOWED")

    if period_month < agreement["signed_on"][:7]:
        raise v.bad("Field 'period_month' precedes the month the agreement was signed.")

    record = ledger_fields()
    record.update({
        "agreement_id": agreement_id,
        "host_club_id": host_club_id,
        "home_club_id_at_visit": agreement["home_club_id"],
        "period_month": period_month,
        "visit_count": visit_count,
        "guest_fee_cents_at_visit": host_club["guest_fee_cents"],
        "usage_fee_cents": visit_count * host_club["guest_fee_cents"],
        "settlement_id": None,
    })
    db.guest_usage_events[record["id"]] = record
    return created(record)


@bp.get("/franchise/guest-usage-events/<gid>")
def read_guest_usage(gid):
    guard(ALL_ROLES)
    return ok(get_guest_event(gid))


@bp.get("/franchise/guest-usage-events")
def list_guest_usage():
    guard(ALL_ROLES)
    return paged(db.guest_usage_events, "agreement_id", "host_club_id", "home_club_id_at_visit",
                 "settlement_id", "period_month")


# --------------------------------------------------------------------------
# usage settlements
# --------------------------------------------------------------------------
def _swept_rows(settlement):
    rows = [g for g in db.guest_usage_events.values()
            if g["settlement_id"] == settlement["id"]]
    return by_seq(rows)


@bp.post("/franchise/usage-settlements")
def create_settlement():
    guard(ADMIN)
    b = v.body()
    period_month = v.req_month(b, "period_month")
    home_club_id = v.req_id(b, "home_club_id")
    host_club_id = v.req_id(b, "host_club_id")

    get_club(home_club_id)
    get_club(host_club_id)

    if home_club_id == host_club_id:
        raise ApiError("ERR_SAME_CLUB_TRANSFER")

    for existing in db.usage_settlements.values():
        if (existing["period_month"] == period_month
                and existing["home_club_id"] == home_club_id
                and existing["host_club_id"] == host_club_id
                and existing["status"] in ("OPEN", "POSTED")):
            raise ApiError("ERR_DUPLICATE_SETTLEMENT_PERIOD")

    candidates = by_seq([g for g in db.guest_usage_events.values()
                         if g["settlement_id"] is None
                         and g["period_month"] == period_month
                         and g["host_club_id"] == host_club_id
                         and g["home_club_id_at_visit"] == home_club_id])
    if not candidates:
        raise ApiError("ERR_NO_SETTLEABLE_USAGE")

    gross = sum(g["usage_fee_cents"] for g in candidates)
    waterfall = calc.usage_settlement_net(gross)

    record = common_fields()
    record.update({
        "period_month": period_month,
        "home_club_id": home_club_id,
        "host_club_id": host_club_id,
        "event_count": len(candidates),
        "visit_count": sum(g["visit_count"] for g in candidates),
        "gross_fee_cents": gross,
        "admin_hold_cents": waterfall["admin_hold_cents"],
        "net_before_rebate_cents": waterfall["net_before_rebate_cents"],
        "rebate_pct": waterfall["rebate_pct"],
        "volume_rebate_cents": waterfall["volume_rebate_cents"],
        "net_payable_cents": waterfall["net_payable_cents"],
        "status": "OPEN",
        "posted_on": None,
        "reversed_on": None,
    })
    db.usage_settlements[record["id"]] = record
    for row in candidates:
        row["settlement_id"] = record["id"]
    return created(record)


@bp.post("/franchise/usage-settlements/<sid>/post")
def post_settlement(sid):
    guard(ADMIN)
    b = v.body()
    v.opt_str(b, "note")
    settlement = get_settlement(sid)

    if settlement["status"] != "OPEN":
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")

    home_club = get_club(settlement["home_club_id"])
    host_club = get_club(settlement["host_club_id"])
    amount = settlement["net_payable_cents"]
    home_club["settlement_ledger_cents"] -= amount
    host_club["settlement_ledger_cents"] += amount
    settlement["status"] = "POSTED"
    settlement["posted_on"] = clock_date_str()
    touch(home_club)
    touch(host_club)
    touch(settlement)
    return ok(settlement)


@bp.post("/franchise/usage-settlements/<sid>/reverse")
def reverse_settlement(sid):
    guard(ADMIN)
    b = v.body()
    v.req_str(b, "reason")
    settlement = get_settlement(sid)

    if settlement["status"] != "POSTED":
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")

    home_club = get_club(settlement["home_club_id"])
    host_club = get_club(settlement["host_club_id"])
    amount = settlement["net_payable_cents"]
    home_club["settlement_ledger_cents"] += amount
    host_club["settlement_ledger_cents"] -= amount
    for row in _swept_rows(settlement):
        row["settlement_id"] = None
    settlement["status"] = "REVERSED"
    settlement["reversed_on"] = clock_date_str()
    touch(home_club)
    touch(host_club)
    touch(settlement)
    return ok(settlement)


@bp.get("/franchise/usage-settlements/<sid>")
def read_settlement(sid):
    guard(ALL_ROLES)
    return ok(get_settlement(sid))


@bp.get("/franchise/usage-settlements")
def list_settlements():
    guard(ALL_ROLES)
    return paged(db.usage_settlements, "home_club_id", "host_club_id", "period_month", "status")
