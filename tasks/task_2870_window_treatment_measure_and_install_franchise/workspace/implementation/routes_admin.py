"""Territories, designers, sample kits, leads and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import calc
from core import (ROLE_DESIGNER, ROLE_FRANCHISEE, ROLE_FRANCHISOR, ROLE_VENDOR_REP,
                  auth, dec_places, fail, get_body, get_designer, get_kit, get_lead,
                  get_territory, list_response, new_row, opt_bool, opt_enum,
                  opt_enum_list, opt_int, opt_num, parse_pagination, present,
                  promote_queued_lead, rederive_territory, req_enum, req_fk,
                  req_instant, req_int, req_list, req_postal, req_str, respond_object, respond_empty,
                  cancel_designer_bookings, check_postal, check_range, apply_filters,
                  require_territory_active, require_territory_ownership, respond_list,
                  serialize, sort_ledger, store, touch)

bp = Blueprint("admin", __name__)

TERRITORY_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED", "TERMINATED")
LIABILITY_WINDOWS = ("ROLLING_180D", "LIFETIME")
DESIGNER_STATUSES = ("ACTIVE", "SUSPENDED", "INACTIVE")
LEAD_SOURCES = ("NATIONAL_CALL_CENTER", "WEB_FORM", "REFERRAL", "WALK_IN")
LEDGER_ENTRY_TYPES = ("NET_SALES_ROYALTY", "ROYALTY_REVERSAL", "REMAKE_CHARGEBACK",
                      "REMEASURE_CHARGEBACK", "SAMPLE_LATE_FEE", "SAMPLE_REPLACEMENT")


# --------------------------------------------------------------------------
# Territories
# --------------------------------------------------------------------------
@bp.route("/blinds/territories", methods=["POST"])
def create_territory():
    auth(ROLE_FRANCHISOR)
    body = get_body()
    legal_name = req_str(body, "legal_name", 1, 120)
    postal_codes = req_list(body, "postal_codes", 1, 40, unique=True)
    for code in postal_codes:
        check_postal(code, "postal_codes")
    royalty = opt_num(body, "royalty_rate_pct", Decimal("0.055"))
    capacity = opt_int(body, "lead_capacity_per_week", 5)
    credit_limit = opt_int(body, "credit_limit_cents", 2000000)
    window = opt_enum(body, "liability_window", LIABILITY_WINDOWS, "ROLLING_180D")
    check_range(Decimal("0") <= royalty <= Decimal("0.15"),
                "royalty_rate_pct must be between 0 and 0.15")
    check_range(dec_places(royalty) <= 4,
                "royalty_rate_pct carries at most four decimal places")
    check_range(capacity >= 1, "lead_capacity_per_week must be at least 1")
    check_range(credit_limit >= 0, "credit_limit_cents may not be negative")
    claimed = set()
    for other in store.territories.values():
        if other["status"] != "TERMINATED":
            claimed.update(other["postal_codes"])
    for code in postal_codes:
        if code in claimed:
            fail("ERR_INVALID_REQUEST",
                 "postal code %s is already served exclusively" % code)
    row = new_row({
        "legal_name": legal_name,
        "postal_codes": list(postal_codes),
        "royalty_rate_pct": royalty,
        "lead_capacity_per_week": capacity,
        "credit_limit_cents": credit_limit,
        "liability_window": window,
        "status": "ACTIVE",
        "open_leads_count": 0,
        "net_sales_cents": 0,
        "royalty_accrued_cents": 0,
        "remake_chargeback_cents": 0,
        "open_order_exposure_cents": 0,
        "available_kit_count": 0,
        "on_loan_kit_count": 0,
        "lost_kit_count": 0,
    })
    store.territories[row["id"]] = row
    return respond_object(serialize(row), 201)


@bp.route("/blinds/territories/<territory_id>", methods=["PATCH"])
def patch_territory(territory_id):
    auth(ROLE_FRANCHISOR)
    territory = get_territory(territory_id)
    body = get_body()
    status = opt_enum(body, "status", TERRITORY_STATUSES)
    royalty = opt_num(body, "royalty_rate_pct")
    capacity = opt_int(body, "lead_capacity_per_week")
    credit_limit = opt_int(body, "credit_limit_cents")
    window = opt_enum(body, "liability_window", LIABILITY_WINDOWS)
    if royalty is not None:
        check_range(Decimal("0") <= royalty <= Decimal("0.15"),
                    "royalty_rate_pct must be between 0 and 0.15")
        check_range(dec_places(royalty) <= 4,
                    "royalty_rate_pct carries at most four decimal places")
    if capacity is not None:
        check_range(capacity >= 1, "lead_capacity_per_week must be at least 1")
    if credit_limit is not None:
        check_range(credit_limit >= 0, "credit_limit_cents may not be negative")
    if status is not None:
        territory["status"] = status
    if royalty is not None:
        territory["royalty_rate_pct"] = royalty
    if capacity is not None:
        territory["lead_capacity_per_week"] = capacity
    if credit_limit is not None:
        territory["credit_limit_cents"] = credit_limit
    if window is not None:
        territory["liability_window"] = window
    touch(territory)
    return respond_object(serialize(territory), 200)


@bp.route("/blinds/territories/<territory_id>", methods=["GET"])
def read_territory(territory_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    territory = get_territory(territory_id)
    require_territory_ownership(actor, territory["id"])
    return respond_object(serialize(territory), 200)


@bp.route("/blinds/territories/<territory_id>/ledger-entries", methods=["GET"])
def list_ledger_entries(territory_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    territory = get_territory(territory_id)
    require_territory_ownership(actor, territory["id"])
    limit, offset = parse_pagination()
    rows = [e for e in store.ledger_entries.values()
            if e["territory_id"] == territory["id"]]
    rows = apply_filters(rows, ("entry_type", "source_entity_type"))
    rows = sort_ledger(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return respond_list([serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Designers
# --------------------------------------------------------------------------
@bp.route("/blinds/designers", methods=["POST"])
def create_designer():
    actor = auth(ROLE_FRANCHISEE)
    body = get_body()
    territory = req_fk(body, "territory_id", get_territory)
    if territory is not None:
        require_territory_ownership(actor, territory["id"])
    territory_id = req_str(body, "territory_id", 1, None)
    territory = get_territory(territory_id)
    full_name = req_str(body, "full_name", 1, 120)
    home_postal_code = req_postal(body, "home_postal_code")
    certifications = opt_enum_list(body, "certifications", calc.CERTIFICATIONS, [], 0, 3)
    require_territory_active(territory)
    row = new_row({
        "territory_id": territory["id"],
        "full_name": full_name,
        "home_postal_code": home_postal_code,
        "certifications": list(certifications),
        "status": "ACTIVE",
        "remeasure_exception_count": 0,
        "late_sample_return_count": 0,
        "clean_install_count": 0,
        "remeasure_liability_score": 100,
    })
    store.designers[row["id"]] = row
    return respond_object(serialize(row), 201)


@bp.route("/blinds/designers/<designer_id>", methods=["PATCH"])
def patch_designer(designer_id):
    actor = auth(ROLE_FRANCHISEE)
    designer = get_designer(designer_id)
    require_territory_ownership(actor, designer["territory_id"])
    body = get_body()
    status = opt_enum(body, "status", DESIGNER_STATUSES)
    certifications = None
    if present(body, "certifications"):
        certifications = opt_enum_list(body, "certifications", calc.CERTIFICATIONS,
                                       [], 0, 3)
    previous = designer["status"]
    if status is not None:
        designer["status"] = status
    if certifications is not None:
        designer["certifications"] = list(certifications)
    touch(designer)
    if status is not None and status != previous and status in ("SUSPENDED", "INACTIVE"):
        cancel_designer_bookings(designer)
    return respond_object(serialize(designer), 200)


@bp.route("/blinds/designers/<designer_id>", methods=["GET"])
def read_designer(designer_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    designer = get_designer(designer_id)
    require_territory_ownership(actor, designer["territory_id"])
    return respond_object(serialize(designer), 200)


@bp.route("/blinds/designers", methods=["GET"])
def list_designers():
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    rows = list(store.designers.values())
    return list_response(rows, ("territory_id", "status"))


# --------------------------------------------------------------------------
# Sample kits
# --------------------------------------------------------------------------
@bp.route("/blinds/sample-kits", methods=["POST"])
def create_sample_kit():
    actor = auth(ROLE_FRANCHISEE)
    body = get_body()
    territory = req_fk(body, "territory_id", get_territory)
    if territory is not None:
        require_territory_ownership(actor, territory["id"])
    territory_id = req_str(body, "territory_id", 1, None)
    territory = get_territory(territory_id)
    kit_code = req_str(body, "kit_code", 1, 40)
    replacement_value = req_int(body, "replacement_value_cents")
    if replacement_value < 1:
        fail("ERR_INVALID_REQUEST", "replacement_value_cents must be at least 1")
    for other in store.sample_kits.values():
        if (other["territory_id"] == territory["id"] and other["status"] != "LOST"
                and other["kit_code"] == kit_code):
            fail("ERR_INVALID_REQUEST", "kit_code is already in use in this territory")
    require_territory_active(territory)
    row = new_row({
        "territory_id": territory["id"],
        "kit_code": kit_code,
        "replacement_value_cents": replacement_value,
        "status": "AVAILABLE",
        "loan_count": 0,
        "open_loan_count": 0,
    })
    store.sample_kits[row["id"]] = row
    rederive_territory(territory)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/sample-kits/<kit_id>", methods=["GET"])
def read_sample_kit(kit_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    kit = get_kit(kit_id)
    require_territory_ownership(actor, kit["territory_id"])
    return respond_object(serialize(kit), 200)


@bp.route("/blinds/sample-kits", methods=["GET"])
def list_sample_kits():
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    rows = list(store.sample_kits.values())
    return list_response(rows, ("territory_id", "status"))


# --------------------------------------------------------------------------
# Leads
# --------------------------------------------------------------------------
def route_lead(lead):
    """PRD 3.1: routing happens inside the intake request, exactly once."""
    postal_code = lead["postal_code"]
    covering = [t for t in store.territories.values()
                if t["status"] == "ACTIVE" and postal_code in t["postal_codes"]]
    eligible = [t for t in covering
                if t["open_leads_count"] < t["lead_capacity_per_week"]]
    if eligible:
        eligible.sort(key=lambda t: (
            -(t["lead_capacity_per_week"] - t["open_leads_count"]),
            -t["royalty_rate_pct"],
            t["created_at"],
            t["_seq"],
            t["id"],
        ))
        winner = eligible[0]
        lead["territory_id"] = winner["id"]
        lead["routed_at"] = store.clock
        lead["status"] = "ROUTED"
        rederive_territory(winner)
    elif covering:
        lead["status"] = "QUEUED"
    else:
        lead["status"] = "UNROUTABLE"
    return lead


@bp.route("/blinds/leads", methods=["POST"])
def create_lead():
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    body = get_body()
    customer_name = req_str(body, "customer_name", 1, 120)
    postal_code = req_postal(body, "postal_code")
    source = req_enum(body, "source", LEAD_SOURCES)
    requested_at = req_instant(body, "requested_at")
    child_occupied = opt_bool(body, "child_occupied_dwelling", False)
    row = new_row({
        "customer_name": customer_name,
        "postal_code": postal_code,
        "source": source,
        "child_occupied_dwelling": child_occupied,
        "requested_at": requested_at,
        "territory_id": None,
        "routed_at": None,
        "status": "NEW",
    })
    store.leads[row["id"]] = row
    route_lead(row)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/leads/<lead_id>", methods=["GET"])
def read_lead(lead_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    lead = get_lead(lead_id)
    require_territory_ownership(actor, lead.get("territory_id"))
    return respond_object(serialize(lead), 200)


@bp.route("/blinds/leads", methods=["GET"])
def list_leads():
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    # PRD 2.3 defines a list result as the rows matching the request's own
    # filters; no implicit role-scoped filter is declared for any collection.
    rows = list(store.leads.values())
    return list_response(rows, ("territory_id", "status"))


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ROLE_FRANCHISOR)
    body = get_body()
    current_utc = req_instant(body, "current_utc")
    store.clock = current_utc
    return respond_empty(200)
