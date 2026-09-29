"""The reference layer of PRD 3.1 plus the logical-clock hook of PRD 2.6."""

from flask import Blueprint, request

from envelope import object_response
from errors import fail
from serialize import (account_out, crew_out, jobsite_out, municipality_out, product_out)
from services import (authenticate, committed_closure_linear_feet, contract_reconciliation,
                      enforce_scope, filter_fk, lookup, maybe_close_contract,
                      allocate_payment, recompute_account, reevaluate_billing_on_payment)
from store import store
from validation import (check_body, iso_ms, parse_pagination, query_bool, query_enum,
                        query_string)
from web import json_body, page

bp = Blueprint("reference", __name__)

READ_MUNICIPALITY_ROLES = ("PlatformAdmin", "AccountManager", "MunicipalLiaison",
                           "DispatchCoordinator", "YardAuditor")
READ_ACCOUNT_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact", "YardAuditor")
LIST_ACCOUNT_ROLES = ("PlatformAdmin", "AccountManager")
READ_PRODUCT_ROLES = ("PlatformAdmin", "AccountManager", "DispatchCoordinator", "YardAuditor")
READ_CREW_ROLES = ("PlatformAdmin", "DispatchCoordinator", "AccountManager")
READ_JOBSITE_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact",
                      "DispatchCoordinator", "MunicipalLiaison", "YardAuditor")

SITE_CONDITIONS = ("SOIL", "ASPHALT", "CONCRETE")
PRODUCT_CATEGORIES = ("FENCE_PANEL", "GATE", "BARRICADE", "WATER_BARRIER")
ADDON_CATEGORIES = ("GATE", "BARRICADE", "WATER_BARRIER")


# ---------------------------------------------------------------------------
# The logical clock — exempt from the authentication and role checks
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    parsed = check_body(json_body(), {"current_utc": {"req": True, "type": "instant"}})
    store.clock = parsed["current_utc"]
    return object_response({"current_utc": iso_ms(store.clock)}, 200)


# ---------------------------------------------------------------------------
# Municipalities
# ---------------------------------------------------------------------------

MUNICIPALITY_SPEC = {
    "name": {"req": True, "type": "string"},
    "jurisdiction_code": {"req": True, "type": "string", "min_len": 3, "max_len": 12,
                          "pattern": r"^[A-Z0-9\-]+$"},
    "permit_lead_time_days": {"req": True, "type": "int", "ge": 0},
    "max_concurrent_closure_linear_feet": {"req": True, "type": "int", "gt": 0},
    "rental_tax_rate_bp": {"req": True, "type": "int", "ge": 0, "le": 2000},
    "permit_review_rounds_allowed": {"type": "int", "ge": 0},
    "allows_solid_wind_screen": {"type": "bool"},
}


def municipality_body(row):
    return municipality_out(row, committed_closure_linear_feet(row["id"]))


@bp.post("/fence-rentals/municipalities")
def create_municipality():
    authenticate(("PlatformAdmin",))
    parsed = check_body(json_body(), MUNICIPALITY_SPEC)
    for existing in store.sorted_rows("municipalities"):
        if existing["jurisdiction_code"] == parsed["jurisdiction_code"]:
            fail("ERR_DUPLICATE_CODE", "That jurisdiction_code is already registered.")
    row = store.new_row("municipalities")
    row.update({
        "name": parsed["name"],
        "jurisdiction_code": parsed["jurisdiction_code"],
        "permit_lead_time_days": parsed["permit_lead_time_days"],
        "max_concurrent_closure_linear_feet": parsed["max_concurrent_closure_linear_feet"],
        "rental_tax_rate_bp": parsed["rental_tax_rate_bp"],
        "permit_review_rounds_allowed": parsed.get("permit_review_rounds_allowed", 2),
        "allows_solid_wind_screen": parsed.get("allows_solid_wind_screen", True),
    })
    store.municipalities[row["id"]] = row
    return object_response(municipality_body(row), 201)


@bp.get("/fence-rentals/municipalities/<row_id>")
def read_municipality(row_id):
    authenticate(READ_MUNICIPALITY_ROLES)
    row = lookup("municipalities", row_id)
    return object_response(municipality_body(row), 200)


@bp.get("/fence-rentals/municipalities")
def list_municipalities():
    authenticate(READ_MUNICIPALITY_ROLES)
    limit, offset = parse_pagination(request.args)
    code = query_string(request.args, "jurisdiction_code")
    rows = [row for row in store.sorted_rows("municipalities")
            if code is None or row["jurisdiction_code"] == code]
    return page(rows, municipality_body, limit, offset)


# ---------------------------------------------------------------------------
# Customer accounts and payments
# ---------------------------------------------------------------------------

ACCOUNT_SPEC = {
    "legal_name": {"req": True, "type": "string"},
    "billing_email": {"req": True, "type": "string"},
    "credit_limit_cents": {"req": True, "type": "int", "ge": 0},
}


@bp.post("/fence-rentals/accounts")
def create_account():
    authenticate(("PlatformAdmin", "AccountManager"))
    parsed = check_body(json_body(), ACCOUNT_SPEC)
    row = store.new_row("accounts")
    row.update({
        "legal_name": parsed["legal_name"],
        "billing_email": parsed["billing_email"],
        "credit_limit_cents": parsed["credit_limit_cents"],
        "open_balance_cents": 0,
        "lifetime_credited_cents": 0,
        "credit_hold_flag": False,
    })
    store.accounts[row["id"]] = row
    return object_response(account_out(row), 201)


@bp.get("/fence-rentals/accounts/<row_id>")
def read_account(row_id):
    identity = authenticate(READ_ACCOUNT_ROLES)
    row = lookup("accounts", row_id)
    enforce_scope(identity, row["id"])
    return object_response(account_out(row), 200)


@bp.get("/fence-rentals/accounts")
def list_accounts():
    authenticate(LIST_ACCOUNT_ROLES)
    limit, offset = parse_pagination(request.args)
    held = query_bool(request.args, "credit_hold_flag")
    rows = [row for row in store.sorted_rows("accounts")
            if held is None or row["credit_hold_flag"] is held]
    return page(rows, account_out, limit, offset)


@bp.post("/fence-rentals/accounts/<row_id>/payments")
def apply_payment(row_id):
    authenticate(("AccountManager",))
    parsed = check_body(json_body(), {"amount_cents": {"req": True, "type": "int", "gt": 0}})
    account = lookup("accounts", row_id)
    touched = allocate_payment(account, parsed["amount_cents"])
    recompute_account(account)
    seen = []
    for invoice in touched:
        if invoice["contract_id"] not in seen:
            seen.append(invoice["contract_id"])
    for contract_id in seen:
        contract = store.contracts.get(contract_id)
        if contract is None:
            continue
        reevaluate_billing_on_payment(contract)
        maybe_close_contract(contract)
    return object_response(account_out(account), 200)


# ---------------------------------------------------------------------------
# Catalogue products
# ---------------------------------------------------------------------------

PRODUCT_SPEC = {
    "code": {"req": True, "type": "string", "min_len": 3, "max_len": 16},
    "category": {"req": True, "type": "string", "enum": PRODUCT_CATEGORIES},
    "description": {"req": True, "type": "string"},
    "unit_monthly_rate_cents": {"req": True, "type": "int", "ge": 0},
    "replacement_cost_cents_per_unit": {"req": True, "type": "int", "gt": 0},
    "fleet_age_months": {"req": True, "type": "int", "ge": 0},
    "owned_count": {"req": True, "type": "int", "gt": 0},
    "panel_length_ft": {"type": "int", "gt": 0, "nullable": True},
    "wind_load_rating_mph": {"type": "int", "gt": 0, "nullable": True},
}


@bp.post("/fence-rentals/products")
def create_product():
    authenticate(("PlatformAdmin",))
    parsed = check_body(json_body(), PRODUCT_SPEC)
    panel_length = parsed.get("panel_length_ft")
    if parsed["category"] == "FENCE_PANEL":
        if panel_length is None:
            fail("ERR_VALIDATION", "A FENCE_PANEL product requires a positive panel_length_ft.")
        if parsed["unit_monthly_rate_cents"] != 0:
            fail("ERR_VALIDATION",
                 "A FENCE_PANEL product must carry a unit_monthly_rate_cents of exactly 0.")
    elif panel_length is not None:
        fail("ERR_VALIDATION", "A non-panel product must carry a null panel_length_ft.")
    for existing in store.sorted_rows("products"):
        if existing["code"] == parsed["code"]:
            fail("ERR_DUPLICATE_CODE", "That product code is already registered.")
    row = store.new_row("products")
    row.update({
        "code": parsed["code"],
        "category": parsed["category"],
        "description": parsed["description"],
        "panel_length_ft": panel_length,
        "unit_monthly_rate_cents": parsed["unit_monthly_rate_cents"],
        "replacement_cost_cents_per_unit": parsed["replacement_cost_cents_per_unit"],
        "fleet_age_months": parsed["fleet_age_months"],
        "wind_load_rating_mph": parsed.get("wind_load_rating_mph"),
        "owned_count": parsed["owned_count"],
        "available_count": parsed["owned_count"],
        "reserved_count": 0,
        "deployed_count": 0,
        "damaged_count": 0,
        "lost_count": 0,
    })
    store.products[row["id"]] = row
    return object_response(product_out(row), 201)


@bp.get("/fence-rentals/products/<row_id>")
def read_product(row_id):
    authenticate(READ_PRODUCT_ROLES)
    return object_response(product_out(lookup("products", row_id)), 200)


@bp.get("/fence-rentals/products")
def list_products():
    authenticate(READ_PRODUCT_ROLES)
    limit, offset = parse_pagination(request.args)
    category = query_enum(request.args, "category", PRODUCT_CATEGORIES)
    code = query_string(request.args, "code")
    rows = []
    for row in store.sorted_rows("products"):
        if category is not None and row["category"] != category:
            continue
        if code is not None and row["code"] != code:
            continue
        rows.append(row)
    return page(rows, product_out, limit, offset)


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------

CREW_SPEC = {
    "crew_code": {"req": True, "type": "string"},
    "depot_code": {"req": True, "type": "string"},
    "daily_capacity_hours": {"req": True, "type": "number", "gt": 0},
    "certified_for_solid_screen": {"type": "bool"},
}


@bp.post("/fence-rentals/crews")
def create_crew():
    authenticate(("PlatformAdmin", "DispatchCoordinator"))
    parsed = check_body(json_body(), CREW_SPEC)
    row = store.new_row("crews")
    row.update({
        "crew_code": parsed["crew_code"],
        "depot_code": parsed["depot_code"],
        "daily_capacity_hours": parsed["daily_capacity_hours"],
        "certified_for_solid_screen": parsed.get("certified_for_solid_screen", False),
    })
    store.crews[row["id"]] = row
    return object_response(crew_out(row), 201)


@bp.get("/fence-rentals/crews/<row_id>")
def read_crew(row_id):
    authenticate(READ_CREW_ROLES)
    return object_response(crew_out(lookup("crews", row_id)), 200)


@bp.get("/fence-rentals/crews")
def list_crews():
    authenticate(READ_CREW_ROLES)
    limit, offset = parse_pagination(request.args)
    depot = query_string(request.args, "depot_code")
    certified = query_bool(request.args, "certified_for_solid_screen")
    rows = []
    for row in store.sorted_rows("crews"):
        if depot is not None and row["depot_code"] != depot:
            continue
        if certified is not None and row["certified_for_solid_screen"] is not certified:
            continue
        rows.append(row)
    return page(rows, crew_out, limit, offset)


# ---------------------------------------------------------------------------
# Jobsites
# ---------------------------------------------------------------------------

JOBSITE_SPEC = {
    "customer_account_id": {"req": True, "type": "string"},
    "municipality_id": {"req": True, "type": "string"},
    "site_label": {"req": True, "type": "string"},
    "address_line": {"req": True, "type": "string"},
    "site_condition": {"req": True, "type": "string", "enum": SITE_CONDITIONS},
    "phase_count": {"type": "int", "ge": 1},
    "requires_sidewalk_closure": {"type": "bool"},
}


@bp.post("/fence-rentals/jobsites")
def create_jobsite():
    authenticate(("PlatformAdmin", "AccountManager"))
    parsed = check_body(json_body(), JOBSITE_SPEC)
    account = lookup("accounts", parsed["customer_account_id"])
    municipality = lookup("municipalities", parsed["municipality_id"])
    row = store.new_row("jobsites")
    row.update({
        "customer_account_id": account["id"],
        "municipality_id": municipality["id"],
        "site_label": parsed["site_label"],
        "address_line": parsed["address_line"],
        "site_condition": parsed["site_condition"],
        "phase_count": parsed.get("phase_count", 1),
        "requires_sidewalk_closure": parsed.get("requires_sidewalk_closure", False),
    })
    store.jobsites[row["id"]] = row
    return object_response(jobsite_out(row), 201)


@bp.get("/fence-rentals/jobsites/<row_id>")
def read_jobsite(row_id):
    identity = authenticate(READ_JOBSITE_ROLES)
    row = lookup("jobsites", row_id)
    enforce_scope(identity, row["customer_account_id"])
    return object_response(jobsite_out(row), 200)


@bp.get("/fence-rentals/jobsites")
def list_jobsites():
    identity = authenticate(READ_JOBSITE_ROLES)
    limit, offset = parse_pagination(request.args)
    account = filter_fk(request.args, "customer_account_id", "accounts")
    municipality = filter_fk(request.args, "municipality_id", "municipalities")
    if account is not None:
        enforce_scope(identity, account["id"])
    rows = []
    for row in store.sorted_rows("jobsites"):
        if account is not None and row["customer_account_id"] != account["id"]:
            continue
        if municipality is not None and row["municipality_id"] != municipality["id"]:
            continue
        if identity.is_customer and row["customer_account_id"] != identity.user_id:
            continue
        rows.append(row)
    return page(rows, jobsite_out, limit, offset)
