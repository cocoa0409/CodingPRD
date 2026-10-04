"""SourceDocument and PropertyAttribute endpoints (PRD 2.9, 2.10, 3.2, 3.3)."""
from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import attribute as ser_attribute
from serializers import source_document as ser_source

bp = Blueprint("sources", __name__, url_prefix="/data-research")

SOURCE_TYPES = {"DEED", "PUBLIC_RECORD", "DIRECT_CONTACT", "BROKER_LISTING", "THIRD_PARTY_FEED"}
CONTACT_METHODS = {"PHONE", "EMAIL", "SITE_VISIT", "RECORDS_REQUEST", "FEED_IMPORT"}


def _licensed_markets_of(organization_id):
    markets = set()
    for contract in lookups.contracts_of(organization_id):
        if contract["status"] in lookups.AUTHORIZED_MARKET_STATUSES:
            markets.update(contract["licensed_markets"])
    return markets


def _redistribution_guard(actor, markets):
    """Priority 4: a THIRD_PARTY_LICENSED claim needs licensed reach for its markets."""
    if actor.organization_id is None:
        return
    licensed = _licensed_markets_of(actor.organization_id)
    for market in markets:
        if market not in licensed:
            raise core.ApiError("ERR_UNAUTHORIZED_REDISTRIBUTION")


# ---------------------------------------------------------------------------
# SourceDocument
# ---------------------------------------------------------------------------
@bp.post("/properties/<property_id>/source-documents")
def create_source_document(property_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    source_type = core.require_enum(payload, "source_type", SOURCE_TYPES)
    source_name = core.require_string(payload, "source_name")
    contact_method = core.require_enum(payload, "contact_method", CONTACT_METHODS)
    obtained_at = core.require_datetime(payload, "obtained_at")
    distributed_markets = core.optional_string_list(payload, "distributed_markets", [])
    actor = auth.authorize_as(user_id, role, ["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)

    classification = "FIRST_PARTY"
    if source_type == "THIRD_PARTY_FEED" or distributed_markets:
        classification = "THIRD_PARTY_LICENSED"

    if prop["land_posture"] == "FROZEN":
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["land_posture"] == "RESTRICTED":
        raise core.ApiError("ERR_PROPERTY_RESTRICTED")
    if obtained_at > core.clock.now():
        raise core.ApiError("ERR_SOURCE_FUTURE_DATED")

    record = {
        "property_id": prop["id"],
        "source_type": source_type,
        "source_name": source_name,
        "contact_method": contact_method,
        "distributed_markets": distributed_markets,
        "obtained_at": core.fmt_dt(obtained_at),
        "source_classification": classification,
    }
    core.stamp_created(record)
    core.source_documents[record["id"]] = record
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_source(record), 201)


@bp.get("/properties/<property_id>/source-documents")
def list_property_sources(property_id):
    auth.authorize(["ResearchAnalyst", "EnforcementOfficer", "LicensingAdmin"])
    lookups.get_property(property_id)
    limit, offset = core.pagination_args(request)
    return responses.paged(lookups.sources_of(property_id), limit, offset, ser_source)


@bp.get("/source-documents")
def list_sources():
    auth.authorize(["ResearchAnalyst", "EnforcementOfficer", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.source_documents.values())
    prop_filter = request.args.get("property_id")
    if prop_filter:
        rows = [s for s in rows if s["property_id"] == prop_filter]
    return responses.paged(rows, limit, offset, ser_source)


@bp.get("/source-documents/<source_document_id>")
def get_source(source_document_id):
    auth.authorize(["ResearchAnalyst", "EnforcementOfficer", "LicensingAdmin"])
    record = lookups.get_source_document_any(source_document_id)
    return responses.ok_object(ser_source(record))


# ---------------------------------------------------------------------------
# PropertyAttribute
# ---------------------------------------------------------------------------
@bp.post("/properties/<property_id>/attributes")
def create_attribute(property_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    source_document_id = core.require_string(payload, "source_document_id")
    field_name = core.require_string(payload, "field_name")
    value = core.require_string(payload, "value", allow_empty=True)
    attribute_market = core.require_string(payload, "attribute_market")
    from_third_party = core.optional_bool(payload, "from_third_party", False)
    third_party_approved = core.optional_bool(payload, "third_party_approved", False)
    actor = auth.authorize_as(user_id, role, ["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)

    source = core.source_documents.get(source_document_id)
    if source is None:
        raise core.ApiError("ERR_SOURCE_DOCUMENT_NOT_FOUND")

    # PRD 2.10: "when the claim derives from a THIRD_PARTY_LICENSED source,
    # from_third_party must be true and third_party_approved must also be true,
    # or the request is refused with ERR_THIRD_PARTY_UNLICENSED" — the provenance
    # of the named source document alone makes the claim third-party-derived.
    third_party_derived = from_third_party or (
        source["source_classification"] == "THIRD_PARTY_LICENSED")
    if third_party_derived and not third_party_approved:
        raise core.ApiError("ERR_THIRD_PARTY_UNLICENSED")

    # Priority 4 business-safety: third-party licensed evidence may only support a
    # claim inside the acting organization's licensed reach.
    if third_party_derived:
        _redistribution_guard(actor, [attribute_market])

    if attribute_market != prop["market"]:
        raise core.ApiError("ERR_ATTRIBUTE_MARKET_MISMATCH")
    if source["property_id"] != prop["id"]:
        raise core.ApiError("ERR_ATTRIBUTE_SOURCE_MISMATCH")

    for existing in lookups.attributes_of(prop["id"]):
        if existing["field_name"] == field_name:
            raise core.ApiError("ERR_ATTRIBUTE_DUPLICATE_FIELD")

    record = {
        "property_id": prop["id"],
        "source_document_id": source["id"],
        "field_name": field_name,
        "value": value,
        "proposed_value": None,
        "proposed_status": "NONE",
        "created_by_user_id": user_id,
        "verifier_user_id": None,
        "last_verified_at": None,
        "attribute_market": attribute_market,
        "from_third_party": from_third_party,
        "third_party_approved": third_party_approved,
        "revision_index": 1,
    }
    core.stamp_created(record)
    core.attributes[record["id"]] = record
    if prop["research_status"] == "DRAFT" and prop["land_posture"] != "FROZEN":
        prop["research_status"] = "RESEARCHING"
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_attribute(record), 201)


@bp.get("/attributes")
def list_attributes():
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin", "EnforcementOfficer"])
    limit, offset = core.pagination_args(request)
    rows = list(core.attributes.values())
    for param, field in (
        ("property_id", "property_id"),
        ("source_document_id", "source_document_id"),
        ("created_by_user_id", "created_by_user_id"),
        ("verifier_user_id", "verifier_user_id"),
        ("proposed_status", "proposed_status"),
    ):
        wanted = request.args.get(param)
        if wanted:
            rows = [a for a in rows if a[field] == wanted]
    return responses.paged(rows, limit, offset, ser_attribute)


@bp.get("/attributes/<attribute_id>")
def get_attribute(attribute_id):
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin", "EnforcementOfficer"])
    record = lookups.get_attribute_any(attribute_id)
    return responses.ok_object(ser_attribute(record))


@bp.post("/properties/<property_id>/attributes/<attribute_id>/proposals")
def propose_attribute_value(property_id, attribute_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    value = core.require_string(payload, "value", allow_empty=True)
    expected_version = core.require_int(payload, "expected_property_version")
    actor = auth.authorize_as(user_id, role, ["ResearchAnalyst"])
    prop = lookups.scoped_property(property_id, actor)
    record = lookups.get_attribute(property_id, attribute_id)

    if record["from_third_party"] and not record["third_party_approved"]:
        raise core.ApiError("ERR_THIRD_PARTY_UNLICENSED")
    if record["proposed_status"] not in ("NONE", "VERIFIED"):
        raise core.ApiError("ERR_INVALID_STATE")
    if prop["land_posture"] == "FROZEN":
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["land_posture"] == "RESTRICTED":
        raise core.ApiError("ERR_PROPERTY_RESTRICTED")
    if record["attribute_market"] != prop["market"]:
        raise core.ApiError("ERR_ATTRIBUTE_MARKET_MISMATCH")
    if expected_version != prop["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    # PRD 3.2: "Submitting a candidate for review moves the attribute from NONE to
    # PENDING". On the VERIFIED -> NONE re-open the rule is explicit that the
    # pending candidate is cleared "to null", and a client may omit `value`; in
    # that case the candidate is absent, so the status lands on NONE. Otherwise
    # the submitted candidate becomes the pending one.
    if record["proposed_status"] == "VERIFIED" and value == "":
        record["proposed_status"] = "NONE"
        record["proposed_value"] = None
    else:
        record["proposed_status"] = "PENDING"
        record["proposed_value"] = value
    core.touch(record)
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_attribute(record))


@bp.post("/attributes/<attribute_id>/verifications")
def verify_attribute(attribute_id):
    user_id, role = auth.read_headers()
    core.body_of(request)
    actor = auth.authorize_as(user_id, role, ["ResearchAnalyst"])
    record = lookups.get_attribute_any(attribute_id)
    prop = lookups.get_property(record["property_id"])

    if record["proposed_status"] != "PENDING":
        raise core.ApiError("ERR_INVALID_STATE")
    if prop["land_posture"] == "FROZEN":
        raise core.ApiError("ERR_PROPERTY_FROZEN")
    if prop["land_posture"] == "RESTRICTED":
        raise core.ApiError("ERR_PROPERTY_RESTRICTED")
    if record["created_by_user_id"] == user_id:
        raise core.ApiError("ERR_SEGREGATION_OF_DUTIES")

    # PRD 2.10: "revision_index ... advances by one on every accepted change of
    # the committed value", so promoting a reviewed candidate advances it.
    record["revision_index"] = record["revision_index"] + 1
    record["value"] = record["proposed_value"]
    record["proposed_value"] = None
    record["proposed_status"] = "VERIFIED"
    record["verifier_user_id"] = user_id
    record["last_verified_at"] = core.fmt_dt(core.clock.now())
    core.touch(record)
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_attribute(record))


@bp.post("/attributes/<attribute_id>/rejections")
def reject_attribute(attribute_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    core.optional_string(payload, "reason", None)
    actor = auth.authorize_as(user_id, role, ["ResearchAnalyst"])
    record = lookups.get_attribute_any(attribute_id)
    prop = lookups.get_property(record["property_id"])

    if record["proposed_status"] != "PENDING":
        raise core.ApiError("ERR_INVALID_STATE")

    record["proposed_value"] = None
    record["proposed_status"] = "NONE"
    core.touch(record)
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_attribute(record))