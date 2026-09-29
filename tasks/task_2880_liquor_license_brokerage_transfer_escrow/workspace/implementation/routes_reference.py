"""Counties, party profiles, brokerages, license stock and the logical clock."""

from flask import Blueprint

import calc
import domain
from authz import (ALL_ROLES, BROKER, ESCROW_OFFICER, PLATFORM_ADMIN, REGULATOR,
                   SELLER, BUYER, authenticate, buyer_or_404, county_or_404,
                   license_or_404, premises_or_404, seller_or_404, brokerage_or_404)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import bump, db, iso, make_record, now, public, public_list, set_clock, sorted_by_created
from validation import F, bad, json_body, validate

bp = Blueprint("reference", __name__)

TAX_CLEARANCE = ("PENDING", "CLEARED", "DELINQUENT")
ENTITY_TYPES = ("INDIVIDUAL", "LLC", "CORP")
VALUATION_BASES = ("COMPARABLE_SALES", "INCOME_MULTIPLE")
DUAL_AGENCY_POLICIES = ("PROHIBITED", "ALLOWED_WITH_DISCLOSURE")
LICENSE_CLASSES = ("CLASS_47_ONSALE_GENERAL", "CLASS_21_OFFSALE_GENERAL",
                   "CLASS_41_ONSALE_BEER_WINE")
LICENSE_STATUSES = ("ACTIVE", "IN_ESCROW", "SAFEKEEPING", "TRANSFERRED")
REVIEW_MODES = ("PRE_CHECK", "FINAL_REVIEW")


# --- counties -------------------------------------------------------------
@bp.route("/counties", methods=["POST"])
def create_county():
    authenticate((PLATFORM_ADMIN,))
    body = json_body()
    data = validate(body, [
        F("county_code", "string", min_len=2, max_len=8),
        F("name", "string"),
        F("state_code", "state_code"),
        F("quota_licenses_total", "integer", minimum=1),
        F("permitted_zoning_codes", "string_array", required=False, default=None),
        F("distance_min_feet_school", "integer", required=False, default=600),
        F("distance_min_feet_church", "integer", required=False, default=600),
        F("posting_period_days", "integer", required=False, default=30),
        F("protest_window_days", "integer", required=False, default=30),
        F("transfer_fee_bps", "integer", required=False, default=150),
        F("default_valuation_basis", "enum", required=False, default="COMPARABLE_SALES",
          values=VALUATION_BASES),
    ])
    for existing in db.counties.values():
        if existing["county_code"] == data["county_code"]:
            bad("county_code must be unique across counties.")
    zoning = data["permitted_zoning_codes"]
    if zoning is None:
        zoning = ["C1", "C2", "MU1"]
    county = make_record({
        "county_code": data["county_code"],
        "name": data["name"],
        "state_code": data["state_code"],
        "quota_licenses_total": data["quota_licenses_total"],
        "permitted_zoning_codes": zoning,
        "distance_min_feet_school": data["distance_min_feet_school"],
        "distance_min_feet_church": data["distance_min_feet_church"],
        "posting_period_days": data["posting_period_days"],
        "protest_window_days": data["protest_window_days"],
        "transfer_fee_bps": data["transfer_fee_bps"],
        "default_valuation_basis": data["default_valuation_basis"],
        "quota_licenses_counted": 0,
        "quota_available": data["quota_licenses_total"],
        "quota_utilization_bps": 0,
        "escrow_committed_count": 0,
    })
    db.counties[county["id"]] = county
    calc.county_quota_position(county)
    return created(public(county))


@bp.route("/counties/<county_id>", methods=["GET"])
def get_county(county_id):
    authenticate(ALL_ROLES)
    return ok(public(county_or_404(county_id)))


# --- seller profiles ------------------------------------------------------
@bp.route("/seller-profiles", methods=["POST"])
def create_seller():
    authenticate((PLATFORM_ADMIN, BROKER))
    data = validate(json_body(), [
        F("legal_name", "string"),
        F("contact_email", "string"),
        F("tax_clearance_status", "enum", required=False, default="PENDING",
          values=TAX_CLEARANCE),
    ])
    seller = make_record({
        "legal_name": data["legal_name"],
        "contact_email": data["contact_email"],
        "tax_clearance_status": data["tax_clearance_status"],
    })
    db.sellers[seller["id"]] = seller
    return created(public(seller))


@bp.route("/seller-profiles/<seller_id>", methods=["GET"])
def get_seller(seller_id):
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR, ESCROW_OFFICER))
    return ok(public(seller_or_404(seller_id)))


# --- buyer profiles -------------------------------------------------------
@bp.route("/buyer-profiles", methods=["POST"])
def create_buyer():
    authenticate((PLATFORM_ADMIN, BROKER))
    data = validate(json_body(), [
        F("legal_name", "string"),
        F("entity_type", "enum", values=ENTITY_TYPES),
        F("residency_state", "state_code"),
        F("felony_disclosure", "boolean", required=False, default=False),
        F("prior_revocation_count", "integer", required=False, default=0, minimum=0),
        F("citizenship_verified", "boolean", required=False, default=False),
    ])
    buyer = make_record({
        "legal_name": data["legal_name"],
        "entity_type": data["entity_type"],
        "residency_state": data["residency_state"],
        "felony_disclosure": data["felony_disclosure"],
        "prior_revocation_count": data["prior_revocation_count"],
        "citizenship_verified": data["citizenship_verified"],
        "qualification_score": None,
        "qualification_status": "NOT_REVIEWED",
        "qualification_mode": None,
        "qualification_reviewed_at": None,
    })
    db.buyers[buyer["id"]] = buyer
    return created(public(buyer))


@bp.route("/buyer-profiles/<buyer_id>", methods=["GET"])
def get_buyer(buyer_id):
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, REGULATOR, ESCROW_OFFICER))
    return ok(public(buyer_or_404(buyer_id)))


@bp.route("/buyer-profiles/<buyer_id>/qualification-review", methods=["POST"])
def qualification_review(buyer_id):
    authenticate((REGULATOR,))
    data = validate(json_body(), [
        F("review_mode", "enum", values=REVIEW_MODES),
        F("premises_id", "string"),
    ])
    buyer = buyer_or_404(buyer_id)
    premises = premises_or_404(data["premises_id"])
    if premises["buyer_id"] != buyer["id"]:
        raise ApiError("ERR_PREMISES_NOT_FOUND",
                       "That premises is not registered to this buyer.")
    county = county_or_404(premises["county_id"])
    score, status = calc.buyer_qualification_score(buyer, premises, county, data["review_mode"])
    buyer["qualification_score"] = score
    buyer["qualification_status"] = status
    buyer["qualification_mode"] = data["review_mode"]
    buyer["qualification_reviewed_at"] = now()
    bump(buyer)
    return ok(public(buyer))


# --- brokerages -----------------------------------------------------------
@bp.route("/brokerages", methods=["POST"])
def create_brokerage():
    authenticate((PLATFORM_ADMIN,))
    data = validate(json_body(), [
        F("firm_name", "string"),
        F("state_broker_license_no", "string"),
        F("commission_rate_bps", "integer", minimum=100, maximum=1500),
        F("dual_agency_policy", "enum", required=False, default="ALLOWED_WITH_DISCLOSURE",
          values=DUAL_AGENCY_POLICIES),
    ])
    for existing in db.brokerages.values():
        if existing["state_broker_license_no"] == data["state_broker_license_no"]:
            bad("state_broker_license_no must be unique across brokerages.")
    brokerage = make_record({
        "firm_name": data["firm_name"],
        "state_broker_license_no": data["state_broker_license_no"],
        "commission_rate_bps": data["commission_rate_bps"],
        "dual_agency_policy": data["dual_agency_policy"],
    })
    db.brokerages[brokerage["id"]] = brokerage
    return created(public(brokerage))


@bp.route("/brokerages/<brokerage_id>", methods=["GET"])
def get_brokerage(brokerage_id):
    authenticate(ALL_ROLES)
    return ok(public(brokerage_or_404(brokerage_id)))


# --- licenses -------------------------------------------------------------
@bp.route("/licenses", methods=["POST"])
def create_license():
    authenticate((PLATFORM_ADMIN,))
    data = validate(json_body(), [
        F("county_id", "string"),
        F("owner_seller_id", "string"),
        F("license_number", "string"),
        F("license_class", "enum", values=LICENSE_CLASSES),
        F("annual_gross_receipts_cents", "integer", minimum=0),
        F("last_active_date", "date"),
        F("last_transfer_price_cents", "integer", required=False, default=None),
        F("counts_against_quota", "boolean", required=False, default=True),
    ])
    county = county_or_404(data["county_id"])
    seller_or_404(data["owner_seller_id"])
    for existing in db.licenses.values():
        if existing["license_number"] == data["license_number"]:
            bad("license_number must be unique across licenses.")
    if data["counts_against_quota"] and county["quota_available"] < 1:
        raise ApiError("ERR_COUNTY_QUOTA_EXHAUSTED",
                       "The county has no remaining quota headroom.")
    lic = make_record({
        "county_id": county["id"],
        "owner_seller_id": data["owner_seller_id"],
        "transferred_to_buyer_id": None,
        "license_number": data["license_number"],
        "license_class": data["license_class"],
        "status": "ACTIVE",
        "annual_gross_receipts_cents": data["annual_gross_receipts_cents"],
        "last_transfer_price_cents": data["last_transfer_price_cents"],
        "last_active_date": data["last_active_date"],
        "counts_against_quota": data["counts_against_quota"],
        "safekeeping_expires_at": None,
        "safekeeping_extensions_count": 0,
        "safekeeping_filing_pending": False,
    })
    db.licenses[lic["id"]] = lic
    domain.recompute_county(county)
    return created(public(lic))


@bp.route("/licenses/<license_id>", methods=["GET"])
def get_license(license_id):
    authenticate(ALL_ROLES)
    return ok(public(license_or_404(license_id)))


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    rows = apply_filters(db.licenses.values(), {
        "county_id": "county_id",
        "owner_seller_id": "owner_seller_id",
        "transferred_to_buyer_id": "transferred_to_buyer_id",
        "status": "status",
        "license_class": "license_class",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/licenses/<license_id>/safekeeping-filings", methods=["GET"])
def list_license_filings(license_id):
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    lic = license_or_404(license_id)
    limit, offset = pagination_args()
    rows = [f for f in db.filings.values() if f["license_id"] == lic["id"]]
    rows = apply_filters(rows, {"status": "status"})
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


# --- logical clock --------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate((PLATFORM_ADMIN,))
    data = validate(json_body(), [F("to_iso8601", "datetime")])
    current = set_clock(data["to_iso8601"])
    return ok({"current_utc": iso(current)})
