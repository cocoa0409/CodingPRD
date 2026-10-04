"""Listing product endpoints (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import listing as ser_listing

bp = Blueprint("listings", __name__, url_prefix="/data-research")

LISTING_TYPES = {"AVAILABLE", "LEASED", "SOLD"}
RENT_CAPPED_TYPES = {"OFFICE", "INDUSTRIAL"}


def _licensed_markets_of(organization_id):
    markets = set()
    for contract in lookups.contracts_of(organization_id):
        if contract["status"] in lookups.AUTHORIZED_MARKET_STATUSES:
            markets.update(contract["licensed_markets"])
    return markets


def _rent_cap_guard(prop, rent_psf):
    if prop["property_type"] in RENT_CAPPED_TYPES and core.dec(rent_psf) > core.OFFICE_INDUSTRIAL_RENT_CAP:
        raise core.ApiError(
            "ERR_UNAUTHORIZED_REDISTRIBUTION",
            "An OFFICE or INDUSTRIAL property may not be marketed above 500.00 psf.")


@bp.post("/properties/<property_id>/listings")
def create_listing(property_id):
    actor = auth.authorize(["BrokerPublisher"])
    payload = core.body_of(request)
    organization_id = core.require_string(payload, "organization_id")
    listing_type = core.require_enum(payload, "listing_type", LISTING_TYPES)
    monthly_rent_psf = core.optional_number(payload, "monthly_rent_psf", None)
    if monthly_rent_psf is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "Missing required field 'monthly_rent_psf'.")
    available_sqft = core.require_int(payload, "available_sqft")
    duration_days = core.require_int(payload, "duration_days")
    prop = lookups.get_property(property_id)
    org = lookups.get_organization(organization_id)

    if available_sqft <= 0:
        raise core.ApiError("ERR_INVALID_REQUEST", "available_sqft must be greater than zero.")
    if duration_days < 1:
        raise core.ApiError("ERR_INVALID_REQUEST", "duration_days must be at least one.")

    record = {
        "property_id": prop["id"],
        "organization_id": org["id"],
        "listing_type": listing_type,
        "monthly_rent_psf": float(monthly_rent_psf),
        "available_sqft": available_sqft,
        "duration_days": duration_days,
        "published_at": None,
        "expires_at": None,
        "redistributed_markets": [],
        "status": "DRAFT",
    }
    core.stamp_created(record)
    core.listings[record["id"]] = record
    return responses.ok_object(ser_listing(record), 201)


@bp.get("/listings")
def list_listings():
    auth.authorize(["BrokerPublisher", "ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.listings.values())
    for param, field in (
        ("property_id", "property_id"),
        ("organization_id", "organization_id"),
        ("status", "status"),
    ):
        wanted = request.args.get(param)
        if wanted:
            rows = [l for l in rows if l[field] == wanted]
    return responses.paged(rows, limit, offset, ser_listing)


@bp.get("/listings/<listing_id>")
def get_listing(listing_id):
    auth.authorize(["BrokerPublisher", "ResearchAnalyst", "LicensingAdmin"])
    record = lookups.get_listing(listing_id)
    return responses.ok_object(ser_listing(record))


def _publish_guards(record, actor):
    prop = lookups.get_property(record["property_id"])
    # PRD 2.14 precedence: authorization, then state, then business safety.
    # PRD 3.8: "The listing must currently hold DRAFT, or the request is refused
    # with ERR_INVALID_STATE" precedes the redistribution control.
    if actor.organization_id is None or record["organization_id"] != actor.organization_id:
        raise core.ApiError("ERR_UNAUTHORIZED",
                            "The listing belongs to a different organization.")
    if record["status"] != "DRAFT":
        raise core.ApiError("ERR_INVALID_STATE")
    # absolute guardrail, never relaxed by role
    _rent_cap_guard(prop, record["monthly_rent_psf"])
    # redistribution: the origin market must lie inside the publisher's licensed reach
    if prop["market"] not in _licensed_markets_of(record["organization_id"]):
        raise core.ApiError("ERR_UNAUTHORIZED_REDISTRIBUTION")
    if prop["land_posture"] == "FROZEN":
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["land_posture"] == "RESTRICTED":
        raise core.ApiError("ERR_PROPERTY_RESTRICTED")
    return prop


def _intervals_overlap(prop, start, end):
    """PRD 3.8: "No other PUBLISHED listing of the same property may hold an
    availability interval overlapping the interval from published_at to
    expires_at."

    Occupancy is half-open and judged against the live interval: a listing whose
    expires_at has already been reached by the logical clock has released the
    interval and no longer blocks a fresh publication.
    """
    now = core.clock.now()
    for other in core.listings.values():
        if other["property_id"] != prop["id"] or other["status"] != "PUBLISHED":
            continue
        if other["published_at"] is None or other["expires_at"] is None:
            continue
        other_end = core.parse_dt(other["expires_at"])
        if other_end <= now:
            continue
        other_start = core.parse_dt(other["published_at"])
        if start < other_end and other_start < end:
            return True
    return False


def _reconcile_property_attributes(prop, record):
    """A published availability becomes research input (PRD 3.8): the property's
    asking_rent_psf and available_sqft attributes are updated from the listing."""
    for at in lookups.attributes_of(prop["id"]):
        if at["field_name"] == "asking_rent_psf":
            at["value"] = str(record["monthly_rent_psf"])
        elif at["field_name"] == "available_sqft":
            at["value"] = str(record["available_sqft"])
        else:
            continue
        if at["proposed_status"] == "PENDING":
            at["proposed_status"] = "NONE"
            at["proposed_value"] = None
        core.touch(at)
    _ensure_availability_attributes(prop, record)


def _ensure_availability_attributes(prop, record):
    """Materialise the two listing-sourced attributes when the record lacks them."""
    existing = {at["field_name"] for at in lookups.attributes_of(prop["id"])}
    wanted = (
        ("asking_rent_psf", str(record["monthly_rent_psf"])),
        ("available_sqft", str(record["available_sqft"])),
    )
    if all(name in existing for name, _value in wanted):
        return
    sources = lookups.sources_of(prop["id"])
    if not sources:
        return
    source_id = sources[0]["id"]
    for field_name, value in wanted:
        if field_name in existing:
            continue
        attr = {
            "property_id": prop["id"],
            "source_document_id": source_id,
            "field_name": field_name,
            "value": value,
            "proposed_value": None,
            "proposed_status": "NONE",
            "created_by_user_id": record.get("_publisher_user_id"),
            "verifier_user_id": None,
            "last_verified_at": None,
            "attribute_market": prop["market"],
            "from_third_party": False,
            "third_party_approved": False,
            "revision_index": 1,
        }
        core.stamp_created(attr)
        core.attributes[attr["id"]] = attr
    calc.refresh_property_state(prop, "PROVISIONAL")


@bp.post("/listings/<listing_id>/publication")
def publish_listing(listing_id):
    actor = auth.authorize(["BrokerPublisher"])
    core.body_of(request)
    record = lookups.get_listing(listing_id)
    prop = _publish_guards(record, actor)

    published_at = core.clock.now()
    expires_at = published_at + timedelta(days=record["duration_days"])
    if _intervals_overlap(prop, published_at, expires_at):
        raise core.ApiError("ERR_LISTING_OVERLAP")

    record["status"] = "PUBLISHED"
    record["published_at"] = core.fmt_dt(published_at)
    record["expires_at"] = core.fmt_dt(expires_at)
    record["_publisher_user_id"] = actor.user_id
    core.touch(record)
    _reconcile_property_attributes(prop, record)
    return responses.ok_object(ser_listing(record))


@bp.post("/listings/<listing_id>/withdrawals")
def withdraw_listing(listing_id):
    actor = auth.authorize(["BrokerPublisher"])
    core.body_of(request)
    record = lookups.get_listing(listing_id)
    if actor.organization_id is not None and record["organization_id"] != actor.organization_id:
        raise core.ApiError("ERR_UNAUTHORIZED")
    if record["status"] != "PUBLISHED":
        raise core.ApiError("ERR_INVALID_STATE")
    record["status"] = "WITHDRAWN"
    core.touch(record)
    return responses.ok_object(ser_listing(record))


@bp.post("/listings/<listing_id>/syndication")
def syndicate_listing(listing_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer"])
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    record = lookups.get_listing(listing_id)
    prop = lookups.get_property(record["property_id"])

    _rent_cap_guard(prop, record["monthly_rent_psf"])
    if record["status"] != "PUBLISHED":
        raise core.ApiError("ERR_INVALID_STATE")
    if market not in record["redistributed_markets"]:
        record["redistributed_markets"] = record["redistributed_markets"] + [market]
    core.touch(record)
    return responses.ok_object(ser_listing(record))