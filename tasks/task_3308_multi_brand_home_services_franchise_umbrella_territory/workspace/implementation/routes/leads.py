"""Lead endpoints -- shared call-center pool and the recipient selector
(PRD 3.6).

POST /franchise/leads, GET /franchise/leads[/{id}], GET /franchise/leads/{id}/recipients
POST /franchise/leads/{id}/allocate|release|convert
"""
from flask import Blueprint

import cascades
import derived
from auth import guard, require_receiving_franchisee
from config import ALLOCATION_HOLD_HOURS, INCOME_BANDS, LEAD_SOURCES
from errors import ApiError
from fetch import get_agreement, get_franchisee, get_lead, paged
from response import created, ok
from store import common_fields, db, hours_from, now_dt, parse_instant, touch
from validate import (
    body,
    opt_id,
    reject_unknown,
    req_enum,
    req_id,
    req_int,
)
from calculations import lead_cost, lead_ranking

bp = Blueprint("leads", __name__)

CREATE_INPUT = ["brand_id", "source", "household_income_band", "estimated_value_cents"]


def _started_lead(lead_id):
    lead = get_lead(lead_id)
    if lead.get("status") in ("CONVERTED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return lead


@bp.post("/franchise/leads")
def create_lead():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    brand_id = req_id(b, "brand_id")
    source = req_enum(b, "source", LEAD_SOURCES)
    band = req_enum(b, "household_income_band", INCOME_BANDS)
    estimated_value = req_int(b, "estimated_value_cents", minimum=0)
    if db.brands.get(brand_id) is None:
        raise ApiError("ERR_BRAND_NOT_FOUND")

    record = common_fields()
    record.update({
        "_kind": "Lead",
        "brand_id": brand_id,
        "source": source,
        "household_income_band": band,
        "estimated_value_cents": estimated_value,
        "allocated_agreement_id": None,
        "received_clock_iso": derived.now_iso(),
        "allocated_clock_iso": None,
        "allocation_hold_until_iso": None,
        "released_clock_iso": None,
        "lead_cost_cents": 0,
        "status": "RECEIVED",
    })
    db.leads[record["id"]] = record
    return created(record)


@bp.get("/franchise/leads/<lead_id>")
def read_lead(lead_id):
    guard(["FranchiseAdmin", "FranchiseeOperator"])
    return ok(get_lead(lead_id))


@bp.get("/franchise/leads")
def list_leads():
    guard(["FranchiseAdmin", "FranchiseeOperator"])
    return paged(
        db.leads,
        "brand_id", "allocated_agreement_id", "status", "household_income_band",
    )


@bp.get("/franchise/leads/<lead_id>/recipients")
def preview_recipients(lead_id):
    guard(["FranchiseAdmin"])
    lead = get_lead(lead_id)
    candidate_ids, ranking_keys, selected = lead_ranking(lead)
    return ok({
        "selected_agreement_id": selected,
        "candidate_agreement_ids": candidate_ids,
        "ranking_keys": ranking_keys,
    })


@bp.post("/franchise/leads/<lead_id>/allocate")
def allocate_lead(lead_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["expected_franchisee_version", "allocated_agreement_id"])
    expected_version = req_int(b, "expected_franchisee_version", minimum=0)
    pinned_agreement_id = opt_id(b, "allocated_agreement_id")
    lead = _started_lead(lead_id)
    if lead.get("status") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")

    if pinned_agreement_id is not None:
        agreement = get_agreement(pinned_agreement_id)
    else:
        _candidate_ids, _keys, selected = lead_ranking(lead)
        if selected is None:
            raise ApiError("ERR_LEAD_POOL_EMPTY")
        agreement = get_agreement(selected)

    franchisee = get_franchisee(agreement.get("franchisee_id"))
    if expected_version != franchisee.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    # Trade qualification (rung 7) precedes the set/threshold rung.
    if lead.get("source") != "CALL_CENTER" or lead.get("brand_id") != agreement.get("brand_id"):
        raise ApiError("ERR_LEAD_BRAND_MISMATCH")
    if not franchisee.get("shared_services_enrolled"):
        raise ApiError("ERR_SHARED_SERVICES_REQUIRED")

    # The receiving agreement may not already hold a live allocation; this is
    # the same per-agreement exclusion the selector applies (PRD 3.6).
    conflict = [
        l for l in db.leads.values()
        if l["id"] != lead["id"]
        and l.get("allocated_agreement_id") == agreement["id"]
        and l.get("status") == "ALLOCATED"
        and _hold_after(l.get("allocation_hold_until_iso"))
    ]
    if conflict:
        raise ApiError("ERR_LEAD_POOL_EMPTY")

    derived.refresh_franchisee(franchisee)
    cost = lead_cost(lead, franchisee)
    lead["allocated_agreement_id"] = agreement["id"]
    lead["allocated_clock_iso"] = derived.now_iso()
    lead["allocation_hold_until_iso"] = derived.iso_of(
        hours_from(now_dt(), ALLOCATION_HOLD_HOURS))
    lead["lead_cost_cents"] = cost
    lead["status"] = "ALLOCATED"
    touch(lead)

    franchisee["lead_cost_balance_cents"] = int(
        franchisee.get("lead_cost_balance_cents") or 0) + int(cost)
    touch(franchisee)
    return ok(lead)


def _hold_after(value):
    if not isinstance(value, str):
        return False
    parsed = parse_instant(value)
    return parsed is not None and parsed > now_dt()


@bp.post("/franchise/leads/<lead_id>/release")
def release_lead(lead_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    lead = _started_lead(lead_id)
    if lead.get("status") != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    agreement = get_agreement(lead.get("allocated_agreement_id"))
    require_receiving_franchisee(uid, role, agreement)
    hold_until = parse_instant(lead.get("allocation_hold_until_iso") or "")
    if hold_until is None or not now_dt() > hold_until:
        raise ApiError("ERR_HOLD_WINDOW_ACTIVE")

    cost = int(lead.get("lead_cost_cents") or 0)
    lead["status"] = "RELEASED"
    lead["released_clock_iso"] = derived.now_iso()
    lead["lead_cost_cents"] = 0
    touch(lead)

    franchisee = db.franchisees.get(agreement.get("franchisee_id"))
    if franchisee is not None:
        derived.refresh_franchisee(franchisee)
        franchisee["lead_cost_balance_cents"] = int(
            franchisee.get("lead_cost_balance_cents") or 0) - cost
        touch(franchisee)
    return ok(lead)


@bp.post("/franchise/leads/<lead_id>/convert")
def convert_lead(lead_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    lead = _started_lead(lead_id)
    if lead.get("status") != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    agreement = get_agreement(lead.get("allocated_agreement_id"))
    lead["status"] = "CONVERTED"
    touch(lead)
    record = common_fields()
    record.update({
        "_kind": "WorkOrder",
        "agreement_id": agreement["id"],
        "source": "CALL_CENTER_LEAD",
        "national_account_id": None,
        "lead_id": lead["id"],
        "referral_id": None,
        "priority": "STANDARD",
        "service_level_hours": 1,
        "parts_cents": 0,
        "dispatched_clock_iso": None,
        "sla_due_iso": None,
        "closed_clock_iso": None,
        "labor_cents": 0,
        "revenue_cents": 0,
        "status": "CREATED",
    })
    db.work_orders[record["id"]] = record
    return ok(lead)