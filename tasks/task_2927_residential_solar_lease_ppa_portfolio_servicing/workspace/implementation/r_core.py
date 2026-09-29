"""Homeowners, the tariff book and agreements (PRD §3.1, §3.2)."""
from decimal import Decimal

from flask import Blueprint

import calc
from core import ApiError, D, clock, fmt_date, invalid, parse_date, sorted_rows, store, stamp_new, touch
from guards import homeowner_scope, lookup
from serialize import agreement_view, homeowner_view, tariff_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("core_routes", __name__)

ALL_ROLES = ("Homeowner", "ServicingAgent", "CreditUnderwriter", "TitleAgent",
             "FieldOpsCoordinator", "PortfolioAdmin")

STATE_CODE = lambda v: len(v) == 2 and v.isalpha() and v.isupper()
UTILITY_CODE = lambda v: v.isalnum() and v.upper() == v
HAS_AT = lambda v: "@" in v

HOMEOWNER_SPECS = [
    {"name": "full_name", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 120, "nonblank": True},
    {"name": "email", "kind": "str", "required": True, "minlen": 1,
     "nonblank": True, "pattern": HAS_AT},
    {"name": "state_code", "kind": "str", "required": True, "pattern": STATE_CODE},
    {"name": "fico_score", "kind": "int", "required": True, "min": 300, "max": 850},
    {"name": "dti_ratio", "kind": "num", "required": True, "min": 0, "max": 1, "dp": 4},
    {"name": "monthly_income_cents", "kind": "int", "required": True, "min": 0},
]


@bp.post("/servicing/homeowners")
def create_homeowner():
    authenticate(("PortfolioAdmin", "ServicingAgent"))
    body = validate_body(HOMEOWNER_SPECS)
    for existing in store.homeowners.values():
        if existing["email"].lower() == body["email"].lower():
            raise ApiError("ERR_DUPLICATE_EMAIL",
                           "A homeowner with that email already exists.")
    row = dict(body)
    stamp_new(row)
    store.homeowners[row["id"]] = row
    return created(homeowner_view(row))


@bp.get("/servicing/homeowners/<homeowner_id>")
def get_homeowner(homeowner_id):
    authenticate(("PortfolioAdmin", "ServicingAgent", "CreditUnderwriter", "TitleAgent"))
    return ok(homeowner_view(lookup("homeowners", homeowner_id)))


@bp.get("/servicing/homeowners")
def list_homeowners():
    authenticate(("PortfolioAdmin", "ServicingAgent", "CreditUnderwriter"))
    limit, offset = pagination()
    flt = filters([("state_code", "str", None), ("email", "str", None)])
    rows = apply_filters(sorted_rows(list(store.homeowners.values())), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([homeowner_view(r) for r in page], limit, offset, total)


TARIFF_SPECS = [
    {"name": "utility_code", "kind": "str", "required": True, "minlen": 2,
     "maxlen": 12, "pattern": UTILITY_CODE},
    {"name": "tariff_code", "kind": "str", "required": True, "minlen": 1, "maxlen": 40},
    {"name": "generation", "kind": "enum", "required": True,
     "values": ("NEM_1", "NEM_2", "NEM_3")},
    {"name": "retail_rate_per_kwh_millicents", "kind": "int", "required": True, "min": 1},
    {"name": "export_credit_rate_per_kwh_millicents", "kind": "int",
     "required": True, "min": 0},
    {"name": "monthly_fixed_charge_cents", "kind": "int", "required": True, "min": 0},
    {"name": "effective_from_date", "kind": "date", "required": True},
    {"name": "grandfathers_predecessors", "kind": "bool", "default": False},
]


@bp.post("/servicing/utility-tariffs")
def create_tariff():
    authenticate(("PortfolioAdmin",))
    body = validate_body(TARIFF_SPECS)
    for existing in store.tariffs.values():
        if (existing["utility_code"] == body["utility_code"]
                and existing["tariff_code"] == body["tariff_code"]):
            raise ApiError("ERR_DUPLICATE_TARIFF_CODE",
                           "That utility_code / tariff_code pair is already published.")
    row = dict(body)
    stamp_new(row, versioned=False)
    store.tariffs[row["id"]] = row
    return created(tariff_view(row))


@bp.get("/servicing/utility-tariffs/<tariff_id>")
def get_tariff(tariff_id):
    authenticate(ALL_ROLES)
    return ok(tariff_view(lookup("tariffs", tariff_id)))


@bp.get("/servicing/utility-tariffs")
def list_tariffs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    flt = filters([("utility_code", "str", None),
                   ("generation", "enum", ("NEM_1", "NEM_2", "NEM_3"))])
    rows = apply_filters(sorted_rows(list(store.tariffs.values())), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([tariff_view(r) for r in page], limit, offset, total)


AGREEMENT_SPECS = [
    {"name": "homeowner_id", "kind": "id", "required": True},
    {"name": "tariff_id", "kind": "id", "required": True},
    {"name": "site_address", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 200, "nonblank": True},
    {"name": "state_code", "kind": "str", "required": True, "pattern": STATE_CODE},
    {"name": "product_type", "kind": "enum", "required": True,
     "values": ("LEASE", "PPA")},
    {"name": "term_years", "kind": "int", "required": True,
     "one_of": (10, 15, 20, 25)},
    {"name": "contract_start_date", "kind": "date", "required": True},
    {"name": "escalator_pct", "kind": "num", "required": True, "min": 0,
     "max": D("0.05"), "dp": 4},
    {"name": "guaranteed_annual_kwh", "kind": "int", "required": True, "min": 1},
    # strictly positive with at most 2 decimal places => minimum is 0.01
    {"name": "system_dc_kw", "kind": "num", "required": True, "min": D("0.01"),
     "dp": 2},
    {"name": "guarantee_band_pct", "kind": "num", "min": 0, "max": D("0.2"),
     "dp": 4, "default": D("0.05")},
    {"name": "base_monthly_lease_cents", "kind": "int", "min": 0},
    {"name": "base_ppa_rate_per_kwh_millicents", "kind": "int", "min": 0},
]

PRODUCT_TYPES = ("LEASE", "PPA")
LIFECYCLE_STATES = ("DRAFT", "ACTIVE", "TRANSFER_PENDING", "END_OF_TERM_PENDING",
                    "PREPAID_CLOSED", "PURCHASED_CLOSED", "REMOVED_CLOSED",
                    "RELOCATED_CLOSED")
MONITORING_STATUSES = ("MONITORING_OK", "OUTAGE_OPEN", "TRUCK_ROLL_DISPATCHED")
SERVICE_STATUSES = ("IN_SERVICE", "ROOF_WORK_SUSPENDED", "DECOMMISSION_PENDING",
                    "DECOMMISSIONED")


def check_product_terms(product_type, lease_cents, ppa_rate):
    """Rung 13 — ERR_PRODUCT_TERMS_MISMATCH (PRD §3.1, re-applied at activation)."""
    if product_type == "LEASE":
        bad = lease_cents is None or ppa_rate is not None
    else:
        bad = ppa_rate is None or lease_cents is not None
    if bad:
        raise ApiError("ERR_PRODUCT_TERMS_MISMATCH",
                       "The base-rate fields do not match product_type %s."
                       % product_type)


@bp.post("/servicing/agreements")
def create_agreement():
    authenticate(("PortfolioAdmin", "ServicingAgent"))
    body = validate_body(AGREEMENT_SPECS)
    start = parse_date(body["contract_start_date"])
    if start.day != 1:
        raise invalid("contract_start_date must fall on the first of the month.")
    # rung 5: body FK existence, in the endpoint's declared input order
    homeowner = lookup("homeowners", body["homeowner_id"])
    tariff = lookup("tariffs", body["tariff_id"])
    # rung 13
    check_product_terms(body["product_type"],
                        body.get("base_monthly_lease_cents"),
                        body.get("base_ppa_rate_per_kwh_millicents"))

    ag = {
        "homeowner_id": homeowner["id"],
        "tariff_id": tariff["id"],
        "relocated_from_agreement_id": None,
        "site_address": body["site_address"],
        "state_code": body["state_code"],
        "product_type": body["product_type"],
        "term_years": body["term_years"],
        "contract_start_date": body["contract_start_date"],
        "contract_end_date": None,
        "escalator_pct": body["escalator_pct"],
        "base_monthly_lease_cents": body.get("base_monthly_lease_cents"),
        "base_ppa_rate_per_kwh_millicents": body.get("base_ppa_rate_per_kwh_millicents"),
        "guaranteed_annual_kwh": body["guaranteed_annual_kwh"],
        "guarantee_band_pct": body["guarantee_band_pct"],
        "system_dc_kw": body["system_dc_kw"],
        "lifecycle_state": "DRAFT",
        "monitoring_status": "MONITORING_OK",
        "service_status": "IN_SERVICE",
        "current_contract_year": 1,
        "credit_earned_cents": 0,
        "credit_applied_cents": 0,
        "credit_balance_cents": 0,
        "grandfathered_export_rate_millicents": 0,
        "tariff_grandfathered": False,
        "renewal_count": 0,
        "open_outage_count": 0,
        "excused_downtime_minutes": 0,
    }
    ag["contract_end_date"] = fmt_date(calc.derive_contract_end_date(ag))
    stamp_new(ag)
    store.agreements[ag["id"]] = ag
    return created(agreement_view(ag))


@bp.get("/servicing/agreements/<agreement_id>")
def get_agreement(agreement_id):
    user_id, role = authenticate(ALL_ROLES)
    ag = lookup("agreements", agreement_id)
    homeowner_scope(role, user_id, ag)
    return ok(agreement_view(ag))


@bp.get("/servicing/agreements")
def list_agreements():
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = pagination()
    flt = filters([
        ("homeowner_id", "str", None),
        ("tariff_id", "str", None),
        ("relocated_from_agreement_id", "str", None),
        ("product_type", "enum", PRODUCT_TYPES),
        ("lifecycle_state", "enum", LIFECYCLE_STATES),
        ("monitoring_status", "enum", MONITORING_STATUSES),
        ("service_status", "enum", SERVICE_STATUSES),
    ])
    rows = list(store.agreements.values())
    for r in rows:
        calc.derive_monitoring(r)
    if role == "Homeowner":
        if "homeowner_id" in flt and flt["homeowner_id"] != user_id:
            raise ApiError("ERR_NOT_AGREEMENT_HOMEOWNER",
                           "A homeowner may only list their own agreements.")
        rows = [r for r in rows if r.get("homeowner_id") == user_id]
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([agreement_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(("PortfolioAdmin", "ServicingAgent"))
    validate_body([])
    ag = lookup("agreements", agreement_id)
    if ag["lifecycle_state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT agreement may be activated.")
    if parse_date(ag["contract_start_date"]) > clock.today():
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The agreement's contract_start_date is in the future.")
    check_product_terms(ag["product_type"], ag.get("base_monthly_lease_cents"),
                        ag.get("base_ppa_rate_per_kwh_millicents"))
    tariff = store.tariffs.get(ag["tariff_id"])
    ag["lifecycle_state"] = "ACTIVE"
    ag["grandfathered_export_rate_millicents"] = (
        tariff["export_credit_rate_per_kwh_millicents"] if tariff else 0)
    ag["contract_end_date"] = fmt_date(calc.derive_contract_end_date(ag))
    ag["tariff_grandfathered"] = calc.evaluate_grandfathered(ag, tariff)
    touch(ag)
    return ok(agreement_view(ag))


@bp.post("/servicing/agreements/<agreement_id>/apply-tariff")
def apply_tariff(agreement_id):
    authenticate(("PortfolioAdmin",))
    body = validate_body([{"name": "tariff_id", "kind": "id", "required": True}])
    ag = lookup("agreements", agreement_id)
    tariff = lookup("tariffs", body["tariff_id"])
    ag["tariff_id"] = tariff["id"]
    # grandfathered_export_rate_millicents is deliberately NOT re-snapshotted.
    ag["tariff_grandfathered"] = calc.evaluate_grandfathered(ag, tariff)
    touch(ag)
    return ok(agreement_view(ag))


@bp.get("/servicing/agreements/<agreement_id>/savings-projection")
def savings_projection(agreement_id):
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent", "Homeowner"))
    ag = lookup("agreements", agreement_id)
    homeowner_scope(role, user_id, ag)
    if ag["lifecycle_state"] not in ("ACTIVE", "END_OF_TERM_PENDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A savings projection is only offered for an ACTIVE or "
                       "END_OF_TERM_PENDING agreement.")
    tariff = store.tariffs.get(ag["tariff_id"])
    return ok(calc.savings_projection(ag, tariff))
