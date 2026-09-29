"""Quote pricing, issuance and acceptance (PRD 3.2 and the first half of 3.3)."""

from flask import Blueprint, request

from calc import MINIMUM_CONSTRUCTION_TERM_MONTHS, QUOTE_VALIDITY_DAYS, price_quote
from envelope import object_response
from errors import fail
from serialize import quote_out
from services import (authenticate, enforce_scope, filter_fk, lookup,
                      municipality_of_jobsite, product_by_code)
from store import store
from validation import (check_body, check_object_list, parse_pagination, plus_days,
                        query_enum)
from web import json_body, page

bp = Blueprint("quotes", __name__)

READ_QUOTE_ROLES = ("PlatformAdmin", "AccountManager", "CustomerContact", "DispatchCoordinator")
QUOTE_STATUSES = ("DRAFT", "ISSUED", "ACCEPTED", "CONVERTED", "SUPERSEDED", "EXPIRED")
CONTRACT_TYPES = ("EVENT", "CONSTRUCTION")
WIND_SCREENS = ("NONE", "MESH_70", "SOLID_130")
ADDON_CATEGORIES = ("GATE", "BARRICADE", "WATER_BARRIER")

QUOTE_SPEC = {
    "expected_jobsite_version": {"req": True, "type": "int"},
    "contract_type": {"req": True, "type": "string", "enum": CONTRACT_TYPES},
    "linear_feet": {"req": True, "type": "int", "gt": 0},
    "panel_product_code": {"req": True, "type": "string"},
    "term_months": {"req": True, "type": "int", "gt": 0},
    "wind_screen": {"type": "string", "enum": WIND_SCREENS},
    "addon_lines": {"type": "array"},
}

ADDON_LINE_SPEC = {
    "product_code": {"req": True, "type": "string"},
    "quantity": {"req": True, "type": "int", "gt": 0},
}


@bp.post("/fence-rentals/jobsites/<row_id>/quotes")
def create_quote(row_id):
    authenticate(("AccountManager",))
    parsed = check_body(json_body(), QUOTE_SPEC)                             # rung 3
    addon_lines = check_object_list("addon_lines", parsed.get("addon_lines", []),
                                    ADDON_LINE_SPEC)
    jobsite = lookup("jobsites", row_id)                                     # rung 4
    panel_product = product_by_code(parsed["panel_product_code"])            # rung 5
    addon_products = {}
    for line in addon_lines:
        addon_products[line["product_code"]] = product_by_code(line["product_code"])
    if parsed["expected_jobsite_version"] != jobsite["version"]:             # rung 8
        fail("ERR_STALE_VERSION",
             "expected_jobsite_version does not match the jobsite's current version.")

    wind_screen = parsed.get("wind_screen", "NONE")
    municipality = municipality_of_jobsite(jobsite)
    if wind_screen == "SOLID_130" and not municipality["allows_solid_wind_screen"]:  # rung 11
        fail("ERR_WIND_LOAD_NOT_PERMITTED",
             "This jurisdiction does not permit a SOLID_130 wind screen.")
    if panel_product["category"] != "FENCE_PANEL":                           # rung 21
        fail("ERR_INVALID_ADDON_CATEGORY",
             "panel_product_code must name a FENCE_PANEL product.")
    for line in addon_lines:
        if addon_products[line["product_code"]]["category"] not in ADDON_CATEGORIES:
            fail("ERR_INVALID_ADDON_CATEGORY",
                 "An add-on line must name a GATE, BARRICADE or WATER_BARRIER product.")
    contract_type = parsed["contract_type"]
    term_months = parsed["term_months"]
    if contract_type == "CONSTRUCTION" and term_months < MINIMUM_CONSTRUCTION_TERM_MONTHS:
        fail("ERR_BELOW_MINIMUM_TERM",                                       # rung 24
             "A CONSTRUCTION configuration requires a term of at least 3 months.")
    if contract_type == "EVENT" and term_months != 1:
        fail("ERR_BELOW_MINIMUM_TERM",
             "An EVENT configuration requires a term of exactly 1 month.")

    priced = price_quote(parsed["linear_feet"], wind_screen, contract_type, term_months,
                         jobsite["site_condition"], panel_product, addon_lines,
                         addon_products)

    supersede_open_quotes(jobsite["id"])
    row = store.new_row("quotes")
    row.update({
        "jobsite_id": jobsite["id"],
        "contract_type": contract_type,
        "linear_feet": parsed["linear_feet"],
        "panel_product_code": panel_product["code"],
        "wind_screen": wind_screen,
        "term_months": term_months,
        "addon_lines": [dict(line) for line in addon_lines],
        "accepted_by_name": None,
        "status": "DRAFT",
        "panel_unit_count": priced["panel_unit_count"],
        "tier_rate_cents_per_ft": priced["tier_rate_cents_per_ft"],
        "monthly_recurring_cents": priced["monthly_recurring_cents"],
        "install_labor_cents": priced["install_labor_cents"],
        "permit_handling_fee_cents": priced["permit_handling_fee_cents"],
        "one_time_cents": priced["one_time_cents"],
        "priced_lines": priced["priced_lines"],
        "issued_at_utc": None,
        "valid_through_utc": None,
    })
    store.quotes[row["id"]] = row
    store.touch(jobsite)
    return object_response(quote_out(row), 201)


def supersede_open_quotes(jobsite_id):
    """PRD 3.2: DRAFT and still-valid ISSUED quotes are superseded; elapsed ones expire."""
    clock = store.clock
    for quote in store.sorted_rows("quotes"):
        if quote["jobsite_id"] != jobsite_id:
            continue
        if quote["status"] == "DRAFT":
            quote["status"] = "SUPERSEDED"
            store.touch(quote)
        elif quote["status"] == "ISSUED":
            quote["status"] = ("SUPERSEDED" if clock <= quote["valid_through_utc"]
                               else "EXPIRED")
            store.touch(quote)


@bp.get("/fence-rentals/quotes/<row_id>")
def read_quote(row_id):
    identity = authenticate(READ_QUOTE_ROLES)
    quote = lookup("quotes", row_id)
    enforce_scope(identity, lookup("jobsites", quote["jobsite_id"])["customer_account_id"])
    return object_response(quote_out(quote), 200)


@bp.get("/fence-rentals/quotes")
def list_quotes():
    identity = authenticate(READ_QUOTE_ROLES)
    limit, offset = parse_pagination(request.args)
    status = query_enum(request.args, "status", QUOTE_STATUSES)
    jobsite = filter_fk(request.args, "jobsite_id", "jobsites")
    if jobsite is not None:
        enforce_scope(identity, jobsite["customer_account_id"])
    rows = []
    for quote in store.sorted_rows("quotes"):
        if jobsite is not None and quote["jobsite_id"] != jobsite["id"]:
            continue
        if status is not None and quote["status"] != status:
            continue
        if identity.is_customer:
            owner = store.jobsites[quote["jobsite_id"]]["customer_account_id"]
            if owner != identity.user_id:
                continue
        rows.append(quote)
    return page(rows, quote_out, limit, offset)


@bp.post("/fence-rentals/quotes/<row_id>/issue")
def issue_quote(row_id):
    authenticate(("AccountManager",))
    check_body(json_body(), {})
    quote = lookup("quotes", row_id)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_STATE", "Only a DRAFT quote may be issued.")
    quote["issued_at_utc"] = store.clock
    quote["valid_through_utc"] = plus_days(store.clock, QUOTE_VALIDITY_DAYS)
    quote["status"] = "ISSUED"
    store.touch(quote)
    return object_response(quote_out(quote), 200)


@bp.post("/fence-rentals/quotes/<row_id>/accept")
def accept_quote(row_id):
    identity = authenticate(("CustomerContact",))
    parsed = check_body(json_body(), {"accepted_by_name": {"type": "string"}})
    quote = lookup("quotes", row_id)
    enforce_scope(identity, lookup("jobsites", quote["jobsite_id"])["customer_account_id"])
    if quote["status"] != "ISSUED":
        fail("ERR_QUOTE_STATE", "Only an ISSUED quote may be accepted.")
    if store.clock > quote["valid_through_utc"]:
        fail("ERR_QUOTE_STATE", "The quote's validity window has elapsed.")
    if "accepted_by_name" in parsed:
        quote["accepted_by_name"] = parsed["accepted_by_name"]
    quote["status"] = "ACCEPTED"
    store.touch(quote)
    return object_response(quote_out(quote), 200)
