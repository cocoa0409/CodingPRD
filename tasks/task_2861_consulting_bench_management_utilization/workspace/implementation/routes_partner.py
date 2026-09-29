"""Partner sourcing: subcontractor firms and external placements (PRD 3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import serial
from derive import SCARCITY_CARVE_OUT, effective_rate, group_posture
from envelope import collection, obj
from errors import bad_request, fail
from helpers import q4
from ops import need, settle, today
from reqctx import (
    GEOGRAPHIES,
    begin,
    body,
    filter_enum,
    filter_value,
    opt_dec,
    opt_enum,
    opt_int,
    opt_str,
    pagination,
    present,
    req_date,
    req_dec,
    req_enum,
    req_id,
    req_int,
    req_str,
    window,
)
from store import bump, db

bp = Blueprint("partner", __name__)

FIRM_READ_ROLES = ("PracticePartner", "ResourceManager", "FinanceController")
PLACEMENT_READ_ROLES = ("ResourceManager", "PracticePartner", "FinanceController")
APPROVAL_STATUSES = ("PENDING", "APPROVED", "SUSPENDED")
PLACEMENT_STATUSES = ("REQUESTED", "APPROVED", "ACTIVE", "TERMINATED")
COMMITTED = ("APPROVED", "ACTIVE")


def _unique_firm_name(name):
    for row in db.all("subcontractor_firms"):
        if row["name"] == name:
            fail("ERR_UNIQUENESS_CONFLICT", "A subcontractor firm with that name already exists.")


@bp.post("/subcontractor-firms")
def register_firm():
    begin("PracticePartner")
    payload = body(
        allowed=(
            "name",
            "geo_code",
            "max_concurrent_placements",
            "pass_through_rate_usd_per_hour",
            "markup_pct",
            "approval_status",
        ),
        required=("name", "geo_code", "max_concurrent_placements", "pass_through_rate_usd_per_hour"),
    )
    name = req_str(payload, "name", 1, 120)
    geo = req_enum(payload, "geo_code", GEOGRAPHIES)
    ceiling = req_int(payload, "max_concurrent_placements", 1, 50)
    pass_through = req_dec(payload, "pass_through_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    markup = opt_dec(payload, "markup_pct", Decimal("0.00"), Decimal("100.00"), 2, Decimal("15.00"))
    status = opt_enum(payload, "approval_status", APPROVAL_STATUSES, "APPROVED")
    _unique_firm_name(name)
    row = db.new_row("subcontractor_firms")
    row.update(
        {
            "name": name,
            "geo_code": geo,
            "max_concurrent_placements": ceiling,
            "pass_through_rate_usd_per_hour": pass_through,
            "markup_pct": markup,
            "approval_status": status,
        }
    )
    db.insert("subcontractor_firms", row)
    return obj(serial.firm(row), 201)


@bp.get("/subcontractor-firms")
def list_firms():
    begin(*FIRM_READ_ROLES)
    limit, offset = pagination()
    geo = filter_enum("geo_code", GEOGRAPHIES)
    status = filter_enum("approval_status", APPROVAL_STATUSES)
    rows = db.all("subcontractor_firms")
    if geo is not None:
        rows = [r for r in rows if r["geo_code"] == geo]
    if status is not None:
        rows = [r for r in rows if r["approval_status"] == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/subcontractor-firms/<firm_id>")
def read_firm(firm_id):
    begin(*FIRM_READ_ROLES)
    return obj(serial.firm(need("subcontractor_firms", firm_id)))


@bp.patch("/subcontractor-firms/<firm_id>")
def update_firm(firm_id):
    begin("PracticePartner")
    firm = need("subcontractor_firms", firm_id)
    payload = body(
        allowed=(
            "approval_status",
            "max_concurrent_placements",
            "markup_pct",
            "pass_through_rate_usd_per_hour",
        )
    )
    status = opt_enum(payload, "approval_status", APPROVAL_STATUSES)
    ceiling = opt_int(payload, "max_concurrent_placements", 1, 50)
    markup = opt_dec(payload, "markup_pct", Decimal("0.00"), Decimal("100.00"))
    pass_through = opt_dec(payload, "pass_through_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    if status is not None:
        firm["approval_status"] = status
    if ceiling is not None:
        firm["max_concurrent_placements"] = ceiling
    if markup is not None:
        firm["markup_pct"] = markup
    if pass_through is not None:
        firm["pass_through_rate_usd_per_hour"] = pass_through
    bump(firm)
    return obj(serial.firm(firm))


# ------------------------------------------------------------ posture gating
def _posture_gate(demand):
    group = db.get("practice_groups", demand["practice_group_id"])
    posture = group_posture(group["id"])
    if posture == "FROZEN":
        fail("ERR_PRACTICE_POSTURE_FROZEN", "A frozen practice may not source externally.")
    if posture == "CONSTRAINED":
        skill = db.get("skills", demand["required_skill_id"])
        if (skill or {}).get("scarcity_index", Decimal("0")) < SCARCITY_CARVE_OUT:
            fail(
                "ERR_PRACTICE_POSTURE_CONSTRAINED",
                "A constrained practice sources externally only for a scarce skill.",
            )
    return group


def _firm_gate(firm, demand):
    group = db.get("practice_groups", demand["practice_group_id"])
    if firm["approval_status"] != "APPROVED" or firm["geo_code"] != group["geography_code"]:
        fail("ERR_FIRM_NOT_APPROVED", "The firm is not vetted for this practice geography.")


@bp.post("/external-placements")
def request_placement():
    begin("ResourceManager")
    payload = body(
        allowed=("subcontractor_firm_id", "demand_opportunity_id", "fte", "start_date", "end_date"),
        required=("subcontractor_firm_id", "demand_opportunity_id", "fte", "start_date", "end_date"),
    )
    firm_id = req_id(payload, "subcontractor_firm_id")
    demand_id = req_id(payload, "demand_opportunity_id")
    fte = req_dec(payload, "fte", Decimal("0.25"), Decimal("10.00"))
    start = req_date(payload, "start_date")
    end = req_date(payload, "end_date")
    if end < start:
        bad_request("Field 'end_date' must be on or after 'start_date'.")
    firm = need("subcontractor_firms", firm_id)
    demand = need("demand_opportunities", demand_id)
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFIED demand may take a partner placement.")
    if demand.get("staffing_mode") is None:
        fail("ERR_STAFFING_MODE_NOT_SET", "The demand has not chosen a staffing branch yet.")
    if demand["staffing_mode"] != "EXTERNAL":
        fail("ERR_STAFFING_MODE_MISMATCH", "Only an EXTERNAL demand takes a partner placement.")
    _firm_gate(firm, demand)
    _posture_gate(demand)
    row = db.new_row("external_placements")
    row.update(
        {
            "subcontractor_firm_id": firm["id"],
            "demand_opportunity_id": demand["id"],
            "fte": fte,
            "start_date": start,
            "end_date": end,
            "pass_through_rate_usd_per_hour": firm["pass_through_rate_usd_per_hour"],
            "bill_rate_usd_per_hour": Decimal("0.00"),
            "status": "REQUESTED",
            "terminated_on": None,
        }
    )
    db.insert("external_placements", row)
    return obj(serial.placement(row), 201)


@bp.get("/external-placements")
def list_placements():
    begin(*PLACEMENT_READ_ROLES)
    limit, offset = pagination()
    firm_id = filter_value("subcontractor_firm_id")
    demand_id = filter_value("demand_opportunity_id")
    status = filter_enum("status", PLACEMENT_STATUSES)
    rows = db.all("external_placements")
    if firm_id is not None:
        rows = [r for r in rows if r["subcontractor_firm_id"] == firm_id]
    if demand_id is not None:
        rows = [r for r in rows if r["demand_opportunity_id"] == demand_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/external-placements/<placement_id>")
def read_placement(placement_id):
    begin(*PLACEMENT_READ_ROLES)
    return obj(serial.placement(need("external_placements", placement_id)))


# ------------------------------------------------------------------- ceilings
def _concurrency_exceeded(placement, firm):
    """Closed intervals on both sides: a placement ending on D and one starting
    on D collide on D (PRD 3.6)."""
    others = [
        p
        for p in db.all("external_placements")
        if p["id"] != placement["id"]
        and p["subcontractor_firm_id"] == firm["id"]
        and p["status"] in COMMITTED
    ]
    probes = [placement["start_date"]]
    for other in others:
        if placement["start_date"] <= other["start_date"] <= placement["end_date"]:
            probes.append(other["start_date"])
    for day in probes:
        overlapping = sum(
            1 for other in others if other["start_date"] <= day <= other["end_date"]
        )
        if overlapping + 1 > firm["max_concurrent_placements"]:
            return True
    return False


def _sourcing_share(group_id, placement):
    committed = Decimal("0")
    required = Decimal("0")
    qualified = [
        d
        for d in db.all("demand_opportunities")
        if d["practice_group_id"] == group_id and d["pipeline_status"] == "QUALIFIED"
    ]
    ids = set(d["id"] for d in qualified)
    for demand in qualified:
        required += demand["required_fte"]
    for row in db.all("external_placements"):
        if row["demand_opportunity_id"] in ids and row["status"] in COMMITTED:
            committed += row["fte"]
    committed += placement["fte"]
    if required == 0:
        return None
    return q4(committed / required)


@bp.post("/external-placements/<placement_id>/approve")
def approve_placement(placement_id):
    begin("PracticePartner")
    placement = need("external_placements", placement_id)
    body(allowed=())
    if placement["status"] != "REQUESTED":
        fail("ERR_PLACEMENT_STATE_INVALID", "Only a REQUESTED placement may be approved.")
    firm = db.get("subcontractor_firms", placement["subcontractor_firm_id"])
    demand = db.get("demand_opportunities", placement["demand_opportunity_id"])
    _firm_gate(firm, demand)
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The demand is no longer QUALIFIED.")
    if demand.get("staffing_mode") != "EXTERNAL":
        fail("ERR_STAFFING_MODE_MISMATCH", "Only an EXTERNAL demand takes a partner placement.")
    group = _posture_gate(demand)
    if _concurrency_exceeded(placement, firm):
        fail("ERR_FIRM_CONCURRENCY_EXCEEDED", "The firm would hold too many placements on one day.")
    share = _sourcing_share(group["id"], placement)
    if share is not None and share > q4(group["external_sourcing_cap_pct"] / Decimal(100)):
        fail(
            "ERR_EXTERNAL_SOURCING_CAP_EXCEEDED",
            "The approval would take the practice past its external sourcing cap.",
        )
    placement["status"] = "APPROVED"
    placement["bill_rate_usd_per_hour"] = effective_rate(demand)
    bump(placement)
    bump(firm)
    bump(demand)
    settle()
    return obj(serial.placement(placement))


@bp.post("/external-placements/<placement_id>/terminate")
def terminate_placement(placement_id):
    begin("PracticePartner")
    placement = need("external_placements", placement_id)
    payload = body(allowed=("reason",))
    if present(payload, "reason"):
        opt_str(payload, "reason", 1, 500)
    if placement["status"] not in COMMITTED:
        fail("ERR_PLACEMENT_STATE_INVALID", "Only an APPROVED or ACTIVE placement may be terminated.")
    placement["status"] = "TERMINATED"
    placement["terminated_on"] = today()
    bump(placement)
    bump(db.get("subcontractor_firms", placement["subcontractor_firm_id"]))
    bump(db.get("demand_opportunities", placement["demand_opportunity_id"]))
    settle()
    return obj(serial.placement(placement))
