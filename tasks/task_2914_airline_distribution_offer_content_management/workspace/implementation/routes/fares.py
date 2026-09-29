"""Fare filings, their lifecycle and the ancillary/bundle catalogue (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import validators as v
from auth import (ALL_ROLES, ROLE_COMPLIANCE_AUDITOR, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST, ROLE_AGENCY,
                  authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from serializers import ancillary_out, bundle_out, fare_filing_out
from services import ancillary_by_code, bundle_by_code, withdraw_offers_for_filing
from store import bump, common_fields, db, get_or_404, sort_key

bp = Blueprint("fares", __name__)

CABINS = ("ECONOMY", "PREMIUM", "BUSINESS")
FILING_STATES = ("DRAFT", "FILED", "ACTIVE", "SUSPENDED", "WITHDRAWN", "SUPERSEDED")

# PRD 3.2 filing state machine.
FILING_TRANSITIONS = {
    "DRAFT": ("FILED",),
    "FILED": ("ACTIVE", "WITHDRAWN"),
    "ACTIVE": ("SUSPENDED", "WITHDRAWN"),
    "SUSPENDED": ("ACTIVE", "WITHDRAWN"),
    "WITHDRAWN": (),
    "SUPERSEDED": (),
}


def _windows_ok(sale_from, sale_to, travel_from, travel_to):
    if sale_from >= sale_to:
        v.bad("sale_to must be strictly after sale_from.")
    if travel_from > travel_to:
        v.bad("travel_to must be at or after travel_from.")


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open windows overlap only with positive extent in common."""
    return a_from < b_to and b_from < a_to


def _check_sale_window_exclusivity(filing):
    for other in db.fare_filings.values():
        if other["id"] == filing["id"] or other["status"] != "ACTIVE":
            continue
        if (other["fare_basis_code"] != filing["fare_basis_code"]
                or other["origin"] != filing["origin"]
                or other["destination"] != filing["destination"]
                or other["cabin"] != filing["cabin"]):
            continue
        if _overlaps(filing["sale_from"], filing["sale_to"],
                     other["sale_from"], other["sale_to"]):
            raise ApiError("ERR_FARE_SALE_WINDOW_OVERLAP",
                           "Another ACTIVE filing shares this sale window.")


@bp.post("/fare-filings")
def create_fare_filing():
    actor = authenticate([ROLE_PRICING_ANALYST])
    body = v.json_body()
    fare_basis_code = v.req_string(body, "fare_basis_code", 1, 16)
    origin = v.req_station(body, "origin")
    destination = v.req_station(body, "destination")
    cabin = v.req_enum(body, "cabin", CABINS)
    base_amount_cents = v.req_int(body, "base_amount_cents", 1, None)
    sale_from = v.req_instant(body, "sale_from")
    sale_to = v.req_instant(body, "sale_to")
    travel_from = v.req_instant(body, "travel_from")
    travel_to = v.req_instant(body, "travel_to")
    min_content_tier_rank = v.opt_int(body, "min_content_tier_rank", 1, 3, 1)
    refundable = v.opt_bool(body, "refundable", True)
    is_private = v.opt_bool(body, "is_private", False)
    _windows_ok(sale_from, sale_to, travel_from, travel_to)

    filing = common_fields()
    filing.update({
        "fare_basis_code": fare_basis_code,
        "origin": origin,
        "destination": destination,
        "cabin": cabin,
        "base_amount_cents": base_amount_cents,
        "sale_from": sale_from,
        "sale_to": sale_to,
        "travel_from": travel_from,
        "travel_to": travel_to,
        "min_content_tier_rank": min_content_tier_rank,
        "refundable": refundable,
        "is_private": is_private,
        "base_filing_id": None,
        "revision_number": 0,
        "filed_by_user_id": actor.user_id,
        "status": "DRAFT",
    })
    db.fare_filings[filing["id"]] = filing
    return respond_object(fare_filing_out(filing), 201)


@bp.get("/fare-filings/<filing_id>")
def read_fare_filing(filing_id):
    authenticate(ALL_ROLES)
    filing = get_or_404(db.fare_filings, filing_id, "ERR_FARE_FILING_NOT_FOUND")
    return respond_object(fare_filing_out(filing))


@bp.get("/fare-filings")
def list_fare_filings():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    status = v.query_enum("status", FILING_STATES)
    origin = v.query_string("origin")
    destination = v.query_string("destination")
    cabin = v.query_enum("cabin", CABINS)
    base_filing_id = v.query_string("base_filing_id")

    rows = []
    for filing in db.fare_filings.values():
        if status is not None and filing["status"] != status:
            continue
        if origin is not None and filing["origin"] != origin:
            continue
        if destination is not None and filing["destination"] != destination:
            continue
        if cabin is not None and filing["cabin"] != cabin:
            continue
        if base_filing_id is not None and filing["base_filing_id"] != base_filing_id:
            continue
        rows.append(filing)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([fare_filing_out(f) for f in page], limit, offset, total)


@bp.post("/fare-filings/<filing_id>/state")
def drive_filing_state(filing_id):
    actor = authenticate([ROLE_PRICING_ANALYST, ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", FILING_STATES)
    v.opt_string(body, "reason", 0, 2000)

    # A DistributionManager shares exactly one filing edge: the suspension.
    if actor.role == ROLE_DISTRIBUTION_MANAGER and to_state != "SUSPENDED":
        raise ApiError("ERR_UNAUTHORIZED",
                       "A DistributionManager may only suspend a filing.")

    filing = get_or_404(db.fare_filings, filing_id, "ERR_FARE_FILING_NOT_FOUND")
    current = filing["status"]
    if to_state not in FILING_TRANSITIONS[current]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A filing in %s has no transition to %s." % (current, to_state))
    # Only a PricingAnalyst may return a suspended filing to sale.
    if current == "SUSPENDED" and to_state == "ACTIVE" and actor.role != ROLE_PRICING_ANALYST:
        raise ApiError("ERR_UNAUTHORIZED", "Only a PricingAnalyst may reactivate.")

    if to_state == "FILED":
        _windows_ok(filing["sale_from"], filing["sale_to"],
                    filing["travel_from"], filing["travel_to"])
    if to_state == "ACTIVE":
        _check_sale_window_exclusivity(filing)

    cascade = to_state == "SUSPENDED" or (to_state == "WITHDRAWN" and current == "ACTIVE")
    filing["status"] = to_state
    bump(filing)
    if cascade:
        withdraw_offers_for_filing(filing["id"])
    return respond_object(fare_filing_out(filing))


@bp.post("/fare-filings/<filing_id>/revisions")
def file_fare_revision(filing_id):
    actor = authenticate([ROLE_PRICING_ANALYST])
    body = v.json_body()
    base_amount_cents = v.req_int(body, "base_amount_cents", 1, None)
    sale_from = v.req_instant(body, "sale_from")
    sale_to = v.req_instant(body, "sale_to")
    expected_version = v.req_int(body, "expected_fare_filing_version", 1, None)
    if sale_from >= sale_to:
        v.bad("sale_to must be strictly after sale_from.")

    base = get_or_404(db.fare_filings, filing_id, "ERR_FARE_FILING_NOT_FOUND")
    if expected_version != base["version"]:
        raise ApiError("ERR_STALE_FARE_FILING_VERSION",
                       "expected_fare_filing_version does not match the base filing.")
    if base["status"] not in ("ACTIVE", "FILED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an ACTIVE or FILED filing may be revised.")

    revision = common_fields()
    revision.update({
        "fare_basis_code": base["fare_basis_code"],
        "origin": base["origin"],
        "destination": base["destination"],
        "cabin": base["cabin"],
        "base_amount_cents": base_amount_cents,
        "sale_from": sale_from,
        "sale_to": sale_to,
        "travel_from": base["travel_from"],
        "travel_to": base["travel_to"],
        "min_content_tier_rank": base["min_content_tier_rank"],
        "refundable": base["refundable"],
        "is_private": base["is_private"],
        "base_filing_id": base["id"],
        "revision_number": base["revision_number"] + 1,
        "filed_by_user_id": actor.user_id,
        "status": "DRAFT",
    })
    db.fare_filings[revision["id"]] = revision

    was_active = base["status"] == "ACTIVE"
    base["status"] = "SUPERSEDED"
    bump(base)
    if was_active:
        withdraw_offers_for_filing(base["id"])
    return respond_object(fare_filing_out(revision), 201)


@bp.post("/ancillary-products")
def create_ancillary_product():
    authenticate([ROLE_PRICING_ANALYST])
    body = v.json_body()
    ancillary_code = v.req_string(body, "ancillary_code", 1, 16)
    name = v.req_string(body, "name", 1, 80)
    list_amount_cents = v.req_int(body, "list_amount_cents", 1, None)
    min_content_tier_rank = v.opt_int(body, "min_content_tier_rank", 1, 3, 1)
    # Ancillaries are assumed non-refundable unless the analyst says otherwise.
    refundable = v.opt_bool(body, "refundable", False)
    if ancillary_by_code(ancillary_code) is not None:
        v.bad("ancillary_code is already published.")

    product = common_fields()
    product.update({
        "ancillary_code": ancillary_code,
        "name": name,
        "list_amount_cents": list_amount_cents,
        "min_content_tier_rank": min_content_tier_rank,
        "refundable": refundable,
    })
    db.ancillaries[product["id"]] = product
    return respond_object(ancillary_out(product), 201)


@bp.post("/bundle-definitions")
def create_bundle_definition():
    authenticate([ROLE_PRICING_ANALYST])
    body = v.json_body()
    bundle_code = v.req_string(body, "bundle_code", 1, 16)
    ancillary_codes = v.req_str_array(body, "ancillary_codes", 1, 6)
    bundle_discount_pct = v.req_decimal(body, "bundle_discount_pct",
                                       Decimal(0), Decimal("0.5"), 4)
    min_content_tier_rank = v.opt_int(body, "min_content_tier_rank", 1, 3, 1)
    if bundle_by_code(bundle_code) is not None:
        v.bad("bundle_code is already defined.")
    for code in ancillary_codes:
        if ancillary_by_code(code) is None:
            raise ApiError("ERR_ANCILLARY_NOT_FOUND",
                           "ancillary_codes names an unknown product: %s" % code)

    bundle = common_fields()
    bundle.update({
        "bundle_code": bundle_code,
        "ancillary_codes": ancillary_codes,
        "bundle_discount_pct": bundle_discount_pct,
        "min_content_tier_rank": min_content_tier_rank,
    })
    db.bundles[bundle["id"]] = bundle
    return respond_object(bundle_out(bundle), 201)
