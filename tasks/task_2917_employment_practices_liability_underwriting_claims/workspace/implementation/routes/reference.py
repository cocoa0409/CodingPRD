"""Carrier reference data (PRD 3.1) and the logical clock (PRD 2.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import serialize
import store
from errors import ApiError
from envelope import created_response, list_response, object_response
from routes.common import ALL_STAFF, by_created, sorted_by
from services import ledger
from validate import (CODE_RE, ENUMS, F, auth, enum_filter, no_body,
                      pagination, parse_body, str_filter)

bp = Blueprint("reference", __name__)

JURISDICTION_READERS = ALL_STAFF
RATE_PLAN_READERS = ("PlatformAdmin", "Underwriter", "UnderwritingManager")
FIRM_READERS = ("PlatformAdmin", "ClaimsAdjuster", "ClaimsManager",
                "PanelCounsel")


# --------------------------------------------------------------------------
# jurisdictions
# --------------------------------------------------------------------------
@bp.get("/epli/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    auth(JURISDICTION_READERS)
    row = store.find(store.JURISDICTIONS, jurisdiction_id,
                     "ERR_JURISDICTION_NOT_FOUND")
    return object_response(serialize.jurisdiction(row))


@bp.get("/epli/jurisdictions")
def list_jurisdictions():
    auth(JURISDICTION_READERS)
    limit, offset = pagination()
    hazard_tier = enum_filter("hazard_tier", "hazard_tier")
    rows = list(store.JURISDICTIONS.values())
    if hazard_tier is not None:
        rows = [r for r in rows if r["hazard_tier"] == hazard_tier]
    rows = sorted_by(rows, [lambda r: r["code"]])
    return list_response([serialize.jurisdiction(r) for r in rows],
                         limit, offset)


@bp.post("/epli/jurisdictions")
def create_jurisdiction():
    auth(("PlatformAdmin",))
    body = parse_body([
        F("code", "str", required=True, regex=CODE_RE),
        F("name", "str", required=True),
        F("hazard_tier", "enum", required=True, values=ENUMS["hazard_tier"]),
        F("admin_agency_name", "str", required=True),
        F("pre_suit_window_days", "int", required=True, min=0),
        F("wage_hour_multiplier", "num", required=True, dp=2, min=1),
        F("class_action_propensity_pct", "num", required=True, dp=2, min=0,
          max=100),
        F("pre_suit_mediation_required", "bool", default=False),
    ])
    if store.jurisdiction_by_code(body["code"]) is not None:
        raise ApiError("ERR_DUPLICATE_JURISDICTION_CODE",
                       "Jurisdiction code '%s' is already registered."
                       % body["code"])
    row = store.new_row({
        "code": body["code"],
        "name": body["name"],
        "hazard_tier": body["hazard_tier"],
        "admin_agency_name": body["admin_agency_name"],
        "pre_suit_window_days": body["pre_suit_window_days"],
        "wage_hour_multiplier": body["wage_hour_multiplier"],
        "class_action_propensity_pct": body["class_action_propensity_pct"],
        "pre_suit_mediation_required": body["pre_suit_mediation_required"],
    })
    store.JURISDICTIONS[row["id"]] = row
    return created_response(serialize.jurisdiction(row))


# --------------------------------------------------------------------------
# rate plans
# --------------------------------------------------------------------------
@bp.get("/epli/rate-plans/<rate_plan_id>")
def get_rate_plan(rate_plan_id):
    auth(RATE_PLAN_READERS)
    row = store.find(store.RATE_PLANS, rate_plan_id, "ERR_RATE_PLAN_NOT_FOUND")
    return object_response(serialize.rate_plan(row))


@bp.get("/epli/rate-plans")
def list_rate_plans():
    auth(RATE_PLAN_READERS)
    limit, offset = pagination()
    status = enum_filter("status", "rate_plan_status")
    rows = list(store.RATE_PLANS.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response([serialize.rate_plan(r) for r in by_created(rows)],
                         limit, offset)


@bp.post("/epli/rate-plans")
def create_rate_plan():
    auth(("PlatformAdmin",))
    body = parse_body([
        F("name", "str", required=True),
        F("base_rate_per_employee_cents", "int", required=True, min=1),
        F("min_premium_cents", "int", required=True, min=1),
        F("wage_hour_sublimit_pct", "num", required=True, dp=2, max=1),
        F("third_party_sublimit_pct", "num", required=True, dp=2, max=1),
    ])
    for field in ("wage_hour_sublimit_pct", "third_party_sublimit_pct"):
        if body[field] <= Decimal("0"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' must be greater than 0." % field)
    for existing in store.RATE_PLANS.values():
        if existing["name"] == body["name"]:
            raise ApiError("ERR_DUPLICATE_RATE_PLAN_NAME",
                           "Rate plan name '%s' is already in use."
                           % body["name"])
    row = store.new_row({
        "name": body["name"],
        "base_rate_per_employee_cents": body["base_rate_per_employee_cents"],
        "min_premium_cents": body["min_premium_cents"],
        "wage_hour_sublimit_pct": body["wage_hour_sublimit_pct"],
        "third_party_sublimit_pct": body["third_party_sublimit_pct"],
        "status": "DRAFT",
    })
    store.RATE_PLANS[row["id"]] = row
    return created_response(serialize.rate_plan(row))


@bp.post("/epli/rate-plans/<rate_plan_id>/activate")
def activate_rate_plan(rate_plan_id):
    auth(("PlatformAdmin",))
    no_body()
    row = store.find(store.RATE_PLANS, rate_plan_id, "ERR_RATE_PLAN_NOT_FOUND")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_RATE_PLAN_NOT_ACTIVATABLE",
                       "Only a DRAFT rate plan may be activated.")
    row["status"] = "ACTIVE"
    store.touch(row)
    return object_response(serialize.rate_plan(row))


# --------------------------------------------------------------------------
# defense panel firms
# --------------------------------------------------------------------------
@bp.get("/epli/defense-panel-firms/<panel_firm_id>")
def get_firm(panel_firm_id):
    auth(FIRM_READERS)
    row = store.find(store.FIRMS, panel_firm_id, "ERR_PANEL_FIRM_NOT_FOUND")
    return object_response(serialize.firm(row))


@bp.get("/epli/defense-panel-firms")
def list_firms():
    auth(FIRM_READERS)
    limit, offset = pagination()
    jurisdiction_code = str_filter("jurisdiction_code")
    tier = enum_filter("tier", "firm_tier")
    status = enum_filter("status", "firm_status")
    rows = list(store.FIRMS.values())
    if jurisdiction_code is not None:
        rows = [r for r in rows
                if jurisdiction_code in r["jurisdiction_codes"]]
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by(rows, [lambda r: r["blended_rate_cents"],
                            lambda r: r["created_at"]])
    return list_response([serialize.firm(r) for r in rows], limit, offset)


@bp.post("/epli/defense-panel-firms")
def create_firm():
    auth(("PlatformAdmin",))
    body = parse_body([
        F("name", "str", required=True),
        F("tier", "enum", required=True, values=ENUMS["firm_tier"]),
        F("jurisdiction_codes", "codes", required=True),
        F("partner_rate_cents_per_hour", "int", required=True, min=1),
        F("associate_rate_cents_per_hour", "int", required=True, min=1),
        F("paralegal_rate_cents_per_hour", "int", required=True, min=1),
        F("capacity_open_matters", "int", required=True, min=1),
    ])
    for code in body["jurisdiction_codes"]:
        if store.jurisdiction_by_code(code) is None:
            raise ApiError("ERR_JURISDICTION_NOT_FOUND",
                           "Jurisdiction code '%s' is not registered." % code)
    for existing in store.FIRMS.values():
        if existing["name"] == body["name"]:
            raise ApiError("ERR_DUPLICATE_PANEL_FIRM_NAME",
                           "Panel firm name '%s' is already in use."
                           % body["name"])
    row = store.new_row({
        "name": body["name"],
        "tier": body["tier"],
        "jurisdiction_codes": body["jurisdiction_codes"],
        "partner_rate_cents_per_hour": body["partner_rate_cents_per_hour"],
        "associate_rate_cents_per_hour": body["associate_rate_cents_per_hour"],
        "paralegal_rate_cents_per_hour": body["paralegal_rate_cents_per_hour"],
        "capacity_open_matters": body["capacity_open_matters"],
        "blended_rate_cents": calc.blended_rate_cents(
            body["partner_rate_cents_per_hour"],
            body["associate_rate_cents_per_hour"],
            body["paralegal_rate_cents_per_hour"]),
        "status": "PANEL_ACTIVE",
    })
    store.FIRMS[row["id"]] = row
    return created_response(serialize.firm(row))


@bp.post("/epli/defense-panel-firms/<panel_firm_id>/suspend")
def suspend_firm(panel_firm_id):
    auth(("PlatformAdmin",))
    no_body()
    row = store.find(store.FIRMS, panel_firm_id, "ERR_PANEL_FIRM_NOT_FOUND")
    if row["status"] != "PANEL_ACTIVE":
        raise ApiError("ERR_PANEL_FIRM_NOT_SUSPENDABLE",
                       "Only a PANEL_ACTIVE firm may be suspended.")
    row["status"] = "PANEL_SUSPENDED"
    store.touch(row)
    return object_response(serialize.firm(row))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.post("/epli/_clock/set_current_utc")
def set_clock():
    auth(("PlatformAdmin",))
    body = parse_body([F("to_iso8601", "instant", required=True)])
    target = body["to_iso8601"]
    if target < store.clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "The logical clock may only move forward.")
    store.clock_set(target)

    activated = []
    expired = []
    for policy in by_created(list(store.POLICIES.values())):
        if policy["status"] == "EXPIRED":
            continue
        if policy["effective_to"] <= target:
            policy["status"] = "EXPIRED"
            store.touch(policy)
            expired.append(policy["id"])
        elif (policy["status"] == "BOUND"
              and policy["effective_from"] <= target):
            policy["status"] = "ACTIVE"
            store.touch(policy)
            activated.append(policy["id"])

    lapsed_services = []
    for service in by_created(list(store.SERVICES.values())):
        if service["status"] != "ACTIVE":
            continue
        if service["effective_to"] <= target:
            service["status"] = "LAPSED"
            store.touch(service)
            lapsed_services.append(service["id"])
            ledger.service_change_cascade(service)

    lapsed_resolutions = []
    for resolution in by_created(list(store.RESOLUTIONS.values())):
        if resolution["status"] != "OFFERED":
            continue
        if resolution["offer_expires_at"] < target:
            resolution["status"] = "LAPSED"
            store.touch(resolution)
            lapsed_resolutions.append(resolution["id"])

    return object_response({
        "current_utc": store.fmt_instant(target),
        "activated_policy_ids": activated,
        "expired_policy_ids": expired,
        "lapsed_service_ids": lapsed_services,
        "lapsed_resolution_ids": lapsed_resolutions,
    })
