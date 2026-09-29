"""The logical clock, the brand registry, ownership entities and the existing
unit map (PRD 3.1 and 3.2)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ALL_ROLES, ROLE_BSD, ROLE_FDM, ROLE_OWNER, authenticate
from common import clock_now, clock_set, fmt_date, fmt_instant
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("core", __name__)

BRAND_TIERS = ("ECONOMY", "MIDSCALE", "UPSCALE", "LUXURY")
UNIT_STATUSES = ("OPERATING", "SUSPENDED", "TERMINATED")

BRAND_SPECS = [
    {"name": "code", "type": "string", "required": True, "min_len": 3, "max_len": 12,
     "upper_alnum": True},
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "tier", "type": "enum", "required": True, "values": BRAND_TIERS},
    {"name": "base_royalty_rate_pct", "type": "number", "required": True,
     "minimum": "0.00", "maximum": "10.00"},
    {"name": "marketing_fund_rate_pct", "type": "number", "required": True,
     "minimum": "0.00", "maximum": "5.00"},
    {"name": "protected_radius_miles", "type": "number", "required": True,
     "minimum": "0.01", "maximum": "50.00"},
    {"name": "min_room_count", "type": "integer", "required": True, "minimum": 1},
    {"name": "standard_term_years", "type": "integer", "required": True,
     "minimum": 5, "maximum": 30},
]

OWNER_PROFILE_SPECS = [
    {"name": "liquid_assets_amount", "type": "number", "required": True,
     "minimum": "0.00"},
    {"name": "net_worth_amount", "type": "number", "required": True, "minimum": "0.00"},
    {"name": "credit_score", "type": "integer", "required": True, "minimum": 300,
     "maximum": 850},
    {"name": "existing_units_count", "type": "integer", "required": True, "minimum": 0},
]

OWNER_SPECS = [
    {"name": "legal_name", "type": "string", "required": True, "min_len": 1,
     "max_len": 160},
    {"name": "contact_email", "type": "string", "required": True, "min_len": 5,
     "max_len": 160, "email": True},
] + OWNER_PROFILE_SPECS

UNIT_SPECS = [
    {"name": "brand_id", "type": "string", "required": True, "min_len": 1},
    {"name": "unit_name", "type": "string", "required": True, "min_len": 1,
     "max_len": 120},
    {"name": "market_code", "type": "string", "required": True, "min_len": 3,
     "max_len": 8, "upper_alnum": True},
    {"name": "x_miles", "type": "number", "required": True, "minimum": "-500.00",
     "maximum": "500.00"},
    {"name": "y_miles", "type": "number", "required": True, "minimum": "-500.00",
     "maximum": "500.00"},
    {"name": "room_count", "type": "integer", "required": True, "minimum": 1},
    {"name": "adr_amount", "type": "number", "required": True, "minimum": "0.00"},
    {"name": "occupancy_pct", "type": "number", "required": True, "minimum": "0.00",
     "maximum": "100.00"},
    {"name": "territory_start_date", "type": "date", "required": True},
    {"name": "territory_end_date", "type": "date", "required": True},
]


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    payload = validation.body()
    fields = validation.take(
        payload, [{"name": "to_iso8601", "type": "datetime", "required": True}]
    )
    clock_set(fields["to_iso8601"])
    return envelope.ok({"current_utc": fmt_instant(clock_now())})


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------


@bp.post("/brands")
def create_brand():
    authenticate((ROLE_BSD,))
    payload = validation.body()
    fields = validation.take(payload, BRAND_SPECS)
    for existing in store.brands.values():
        if existing["code"] == fields["code"]:
            raise ApiError("ERR_BRAND_CODE_TAKEN")
    row = store.new_row("brand")
    for spec in BRAND_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    row["operating_unit_count"] = 0
    row["open_application_count"] = 0
    store.brands[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/brands/<brand_id>")
def read_brand(brand_id):
    authenticate(ALL_ROLES)
    return envelope.ok(dump(store.get_brand(brand_id)))


@bp.get("/brands/<brand_id>/existing-units")
def list_brand_units(brand_id):
    authenticate((ROLE_FDM, ROLE_BSD))
    brand = store.get_brand(brand_id)
    limit, offset = envelope.pagination()
    status = validation.query_filter("status")
    rows = store.ordered(
        store.existing_units,
        lambda u: u["brand_id"] == brand["id"]
        and (status is None or u["status"] == status),
    )
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


# ---------------------------------------------------------------------------
# Ownership entities
# ---------------------------------------------------------------------------


@bp.post("/owners")
def create_owner():
    authenticate((ROLE_FDM,))
    payload = validation.body()
    fields = validation.take(payload, OWNER_SPECS)
    row = store.new_row("owner")
    for spec in OWNER_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    row["financial_profile_revision"] = 0
    row["status"] = "PROSPECT"
    calc.recompute_owner_capacity(row)
    store.owners[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/owners/<owner_id>")
def read_owner(owner_id):
    authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    return envelope.ok(dump(store.get_owner(owner_id)))


@bp.post("/owners/<owner_id>/financial-profile")
def reverify_owner(owner_id):
    authenticate((ROLE_FDM,))
    owner = store.get_owner(owner_id)
    payload = validation.body()
    fields = validation.take(payload, OWNER_PROFILE_SPECS)
    for spec in OWNER_PROFILE_SPECS:
        owner[spec["name"]] = fields[spec["name"]]
    owner["financial_profile_revision"] = owner["financial_profile_revision"] + 1
    calc.recompute_owner_capacity(owner)
    touch(owner)
    for application in store.ordered(
        store.applications,
        lambda a: a["owner_id"] == owner["id"]
        and a["status"] == "UNDER_REVIEW"
        and a["financial_review_status"] == "PASSED",
    ):
        application["financial_review_status"] = "STALE"
        touch(application)
    return envelope.ok(dump(owner))


# ---------------------------------------------------------------------------
# The existing unit map
# ---------------------------------------------------------------------------


@bp.post("/existing-units")
def create_unit():
    authenticate((ROLE_BSD,))
    payload = validation.body()
    brand_id = validation.fk_string(payload, "brand_id")
    brand = store.get_brand(brand_id) if brand_id is not None else None
    fields = validation.take(payload, UNIT_SPECS)
    if brand is None:
        brand = store.get_brand(fields["brand_id"])
    if fields["territory_end_date"] < fields["territory_start_date"]:
        validation.bad("territory_end_date must not precede territory_start_date.")
    row = store.new_row("existing_unit")
    for spec in UNIT_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    row["territory_start_date"] = fmt_date(fields["territory_start_date"])
    row["territory_end_date"] = fmt_date(fields["territory_end_date"])
    row["status"] = "OPERATING"
    row["status_reason"] = None
    store.existing_units[row["id"]] = row
    domain.brand_recount(brand)
    return envelope.created(dump(row))


@bp.post("/existing-units/<unit_id>/status")
def move_unit_status(unit_id):
    authenticate((ROLE_BSD,))
    unit = store.get_unit(unit_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "to_status", "type": "enum", "required": True,
             "values": UNIT_STATUSES},
            {"name": "reason", "type": "string", "required": False, "nullable": True},
        ],
    )
    target = fields["to_status"]
    if target not in domain.UNIT_STATUS_TRANSITIONS[unit["status"]]:
        raise ApiError("ERR_UNIT_STATUS_TRANSITION_INVALID")
    unit["status"] = target
    if fields["_present_reason"]:
        unit["status_reason"] = fields["reason"]
    touch(unit)
    domain.brand_recount(store.brands.get(unit["brand_id"]))
    return envelope.ok(dump(unit))
