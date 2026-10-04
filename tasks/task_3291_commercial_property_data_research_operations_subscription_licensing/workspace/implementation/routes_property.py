"""Property research endpoints (PRD 3.1, 3.3, 3.4)."""
from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import property as ser_property

bp = Blueprint("property", __name__, url_prefix="/data-research")

PROPERTY_TYPES = {"OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "HOSPITALITY"}
CLASSIFICATIONS = {"CLASS_A", "CLASS_B", "CLASS_C"}


def _new_property(payload, parent_property_id=None):
    market = core.require_string(payload, "market")
    address_line = core.require_string(payload, "address_line")
    property_type = core.require_enum(payload, "property_type", PROPERTY_TYPES)
    rentable_sqft = core.require_int(payload, "rentable_sqft")
    classification = core.optional_enum(payload, "classification", CLASSIFICATIONS, "CLASS_B")
    if rentable_sqft <= 0:
        raise core.ApiError("ERR_INVALID_REQUEST", "rentable_sqft must be greater than zero.")
    prop = {
        "parent_property_id": parent_property_id,
        "market": market,
        "address_line": address_line,
        "property_type": property_type,
        "rentable_sqft": rentable_sqft,
        "classification": classification,
        "research_status": "DRAFT",
        "land_posture": "OPEN",
        "attribute_verified_count": 0,
        "attribute_total_count": 0,
        "completeness_pct": 0.0,
        "stale_source_count": 0,
        "verified_sale_value_cents": 0,
    }
    core.stamp_created(prop)
    core.properties[prop["id"]] = prop
    return prop


def _land_posture_guard(prop, blocking):
    """Raise the posture error when the property blocks the operation."""
    if prop["land_posture"] == "FROZEN" and "FROZEN" in blocking:
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["land_posture"] == "RESTRICTED" and "RESTRICTED" in blocking:
        raise core.ApiError("ERR_PROPERTY_RESTRICTED")


@bp.post("/properties")
def create_property():
    actor = auth.authorize(["ResearchAnalyst", "PlatformAdmin"])
    payload = core.body_of(request)
    prop = _new_property(payload)
    return responses.ok_object(ser_property(prop), 201)


@bp.get("/properties")
def list_properties():
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.properties.values())
    market = request.args.get("market")
    status = request.args.get("research_status")
    parent = request.args.get("parent_property_id")
    if market:
        rows = [p for p in rows if p["market"] == market]
    if status:
        rows = [p for p in rows if p["research_status"] == status]
    if parent:
        rows = [p for p in rows if p["parent_property_id"] == parent]
    return responses.paged(rows, limit, offset, ser_property)


@bp.get("/properties/<property_id>")
def get_property(property_id):
    actor = auth.authorize(
        ["ResearchAnalyst", "SeatUser", "LicensingAdmin", "EnforcementOfficer"])
    prop = lookups.scoped_property(property_id, actor)
    return responses.ok_object(ser_property(prop))


@bp.post("/properties/<property_id>/research/start")
def start_research(property_id):
    actor = auth.authorize(["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)
    # PRD 3.7: "while it sits at FROZEN, finalize, the explicit start of research
    # and subdivision are all refused with ERR_PROPERTY_FROZEN (HTTP 409)".
    _land_posture_guard(prop, {"FROZEN"})
    if prop["research_status"] != "DRAFT":
        raise core.ApiError("ERR_INVALID_STATE")
    prop["research_status"] = "RESEARCHING"
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_property(prop))


@bp.post("/properties/<property_id>/finalize")
def finalize_property(property_id):
    actor = auth.authorize(["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)
    # PRD 3.1: "The path from RESEARCHING to VERIFIED runs through the same
    # finalize operation as the DRAFT to VERIFIED path" — DRAFT and RESEARCHING
    # are both entry states; anything else is the state-gate error.
    if prop["research_status"] not in ("DRAFT", "RESEARCHING"):
        raise core.ApiError("ERR_INVALID_STATE")
    _land_posture_guard(prop, {"FROZEN", "RESTRICTED"})
    if prop["attribute_total_count"] < 1:
        raise core.ApiError("ERR_EMPTY_ATTRIBUTE_SET")
    for attr in lookups.attributes_of(prop["id"]):
        if attr["proposed_status"] == "PENDING":
            raise core.ApiError("ERR_ATTRIBUTES_UNRESOLVED")
    prop["research_status"] = "VERIFIED"
    calc.refresh_property_state(prop, "FINAL")
    return responses.ok_object(ser_property(prop))


@bp.post("/properties/<property_id>/subdivision")
def subdivide_property(property_id):
    actor = auth.authorize(["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)
    if prop["land_posture"] == "FROZEN":
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["research_status"] != "DRAFT":
        raise core.ApiError("ERR_SUBDIVISION_PARENT_INVALID")
    payload = core.body_of(request)
    child = _new_property(payload, parent_property_id=prop["id"])
    core.touch(prop)
    return responses.ok_object(ser_property(child), 201)


@bp.get("/properties/<property_id>/subdivisions")
def list_subdivisions(property_id):
    actor = auth.authorize(["ResearchAnalyst", "PlatformAdmin", "LicensingAdmin"])
    lookups.get_property(property_id)
    limit, offset = core.pagination_args(request)
    return responses.paged(lookups.children_of(property_id), limit, offset, ser_property)