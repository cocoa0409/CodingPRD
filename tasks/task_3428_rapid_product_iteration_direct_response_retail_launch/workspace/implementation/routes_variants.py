"""Model variants: channel-differentiated model numbers, factory tooling slots,
and the variant-scoped reverse lookups (claim studies, media tests, replenishments)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import (ser_media, ser_replenishment, ser_study, ser_variant)
from services import (get_or_404, posture_gate, req_fk, season_of_concept,
                      season_of_variant)
from state import DB, base_fields, bump, now
from util import body, by_creation, fmt_iso, ok_object, paginate, req_enum, req_string

bp = Blueprint("variants", __name__)

CHANNELS = ("AMAZON", "BIG_BOX", "CLUB", "DTC", "SPECIALTY")


@bp.post("/model-variants")
def create_variant():
    require_roles(("ProductLead",))
    data = body()
    concept = req_fk(data, "concept_id", DB.concepts, "ERR_CONCEPT_NOT_FOUND")
    model_number = req_string(data, "model_number")
    channel = req_enum(data, "channel", CHANNELS)
    posture_gate(season_of_concept(concept))
    if concept["status"] != "ENGINEERING_LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "variants can only be created from an ENGINEERING_LOCKED concept")
    if any(v["model_number"] == model_number for v in DB.variants.values()):
        raise ApiError("ERR_MODEL_NUMBER_CONFLICT", 409,
                       "model_number must be globally unique")
    v = base_fields()
    v.update({
        "concept_id": concept["id"],
        "factory_partner_id": None,
        "model_number": model_number,
        "channel": channel,
        "lifecycle": "DRAFT",
        "claim_clearance": "UNSUBSTANTIATED",
        "tooled_at": None,
        "tooled_dt": None,
        "retail_live_at": None,
        "retail_live_dt": None,
        "refresh_candidate_at": None,
        "refresh_candidate_dt": None,
        "retired_at": None,
        "retired_dt": None,
    })
    DB.variants[v["id"]] = v
    return ok_object(ser_variant(v), 201)


@bp.get("/model-variants/<vid>")
def get_variant(vid):
    require_roles(ALL_ROLES)
    return ok_object(ser_variant(get_or_404(DB.variants, vid, "ERR_VARIANT_NOT_FOUND")))


@bp.get("/model-variants")
def list_variants():
    require_roles(ALL_ROLES)
    items = by_creation(DB.variants.values())
    for param, field in (("concept_id", "concept_id"),
                         ("factory_partner_id", "factory_partner_id"),
                         ("lifecycle", "lifecycle"),
                         ("claim_clearance", "claim_clearance")):
        value = request.args.get(param)
        if value is not None:
            items = [v for v in items if v[field] == value]
    return paginate([ser_variant(v) for v in items])


@bp.post("/model-variants/<vid>/tool")
def tool_variant(vid):
    require_roles(("SourcingManager",))
    v = get_or_404(DB.variants, vid, "ERR_VARIANT_NOT_FOUND")
    data = body()
    partner = req_fk(data, "factory_partner_id", DB.partners, "ERR_PARTNER_NOT_FOUND")
    posture_gate(season_of_variant(v))
    if v["lifecycle"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "only a DRAFT variant can be tooled")
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", 409, "factory partner is not ACTIVE")
    # tooling occupies the half-open window [now, now + TOOLING_WINDOW_DAYS);
    # at most TOOLING_PARALLEL_SLOTS simultaneous engagements per partner
    window = timedelta(days=CONSTANTS["TOOLING_WINDOW_DAYS"])
    t0 = now()
    t1 = t0 + window
    overlapping = 0
    for other in DB.variants.values():
        if other["id"] == v["id"]:
            continue
        if other.get("factory_partner_id") != partner["id"]:
            continue
        opened = other.get("tooled_dt")
        if opened is None:
            continue
        if opened < t1 and t0 < opened + window:
            overlapping += 1
    if overlapping >= CONSTANTS["TOOLING_PARALLEL_SLOTS"]:
        raise ApiError("ERR_TOOLING_SLOTS_FULL", 409,
                       "the partner's parallel tooling slots are occupied")
    v["factory_partner_id"] = partner["id"]
    v["tooled_at"] = fmt_iso(t0)
    v["tooled_dt"] = t0
    v["lifecycle"] = "TOOLED"
    bump(v)
    return ok_object(ser_variant(v))


@bp.get("/model-variants/<vid>/claim-studies")
def list_variant_studies(vid):
    require_roles(ALL_ROLES)
    get_or_404(DB.variants, vid, "ERR_VARIANT_NOT_FOUND")
    items = [ser_study(s) for s in by_creation(DB.studies.values())
             if s["variant_id"] == vid]
    return paginate(items)


@bp.get("/model-variants/<vid>/media-tests")
def list_variant_media_tests(vid):
    require_roles(ALL_ROLES)
    get_or_404(DB.variants, vid, "ERR_VARIANT_NOT_FOUND")
    items = [ser_media(m) for m in by_creation(DB.media_tests.values())
             if m["variant_id"] == vid]
    return paginate(items)


@bp.get("/model-variants/<vid>/replenishments")
def list_variant_replenishments(vid):
    require_roles(ALL_ROLES)
    get_or_404(DB.variants, vid, "ERR_VARIANT_NOT_FOUND")
    items = [ser_replenishment(r) for r in by_creation(DB.replenishments.values())
             if r["variant_id"] == vid]
    return paginate(items)
