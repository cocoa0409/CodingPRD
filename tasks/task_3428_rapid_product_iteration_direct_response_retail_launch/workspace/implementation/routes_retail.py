"""Retail domain: retail agreements (exclusive half-open windows), launch
commitments (OCC-guarded on the agreement), and rapid replenishment orders
(OCC-guarded on the variant)."""

from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import ser_agreement, ser_commitment, ser_replenishment
from services import (allocated_units, get_or_404, posture_gate, req_fk,
                      season_of_category, season_of_variant)
from state import DB, base_fields, bump, now, touch
from util import (body, by_creation, fmt_iso, ok_object, paginate, req_bool,
                  req_dt, req_int, req_string)

bp = Blueprint("retail", __name__)

RETAIL_EXEC = ("RetailExec",)
SOURCING = ("SourcingManager",)


# ---------------------------------------------------------------------------
# retail agreements
# ---------------------------------------------------------------------------


@bp.post("/retail-agreements")
def create_agreement():
    require_roles(RETAIL_EXEC)
    data = body()
    cat = req_fk(data, "category_id", DB.categories, "ERR_CATEGORY_NOT_FOUND")
    retailer_name = req_string(data, "retailer_name")
    exclusive = req_bool(data, "exclusive")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    min_launch_units = req_int(data, "min_launch_units", min_v=1)
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "window_end must be strictly after window_start")
    posture_gate(season_of_category(cat))
    a = base_fields()
    a.update({
        "category_id": cat["id"],
        "retailer_name": retailer_name,
        "exclusive": exclusive,
        "window_start": fmt_iso(window_start),
        "window_start_dt": window_start,
        "window_end": fmt_iso(window_end),
        "window_end_dt": window_end,
        "min_launch_units": min_launch_units,
        "status": "DRAFT",
        "signed_at": None,
    })
    DB.agreements[a["id"]] = a
    return ok_object(ser_agreement(a), 201)


@bp.get("/retail-agreements/<aid>")
def get_agreement(aid):
    require_roles(ALL_ROLES)
    return ok_object(ser_agreement(get_or_404(DB.agreements, aid, "ERR_AGREEMENT_NOT_FOUND")))


@bp.post("/retail-agreements/<aid>/sign")
def sign_agreement(aid):
    require_roles(RETAIL_EXEC)
    a = get_or_404(DB.agreements, aid, "ERR_AGREEMENT_NOT_FOUND")
    cat = get_or_404(DB.categories, a["category_id"], "ERR_CATEGORY_NOT_FOUND")
    # priority 4 posture (GUARDED still signs), 5 state, 7 litigation, 8 temporal
    posture_gate(season_of_category(cat))
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "only a DRAFT agreement can be signed")
    if cat["exposure_level"] == "SEVERE":
        raise ApiError("ERR_CATEGORY_LITIGATION_BLOCKED", 422,
                       "category litigation exposure is SEVERE")
    for other in DB.agreements.values():
        if other["id"] == a["id"] or other["category_id"] != a["category_id"]:
            continue
        if other["status"] != "SIGNED" or not other["exclusive"]:
            continue
        # half-open [start, end) intersection; adjacency is not a conflict
        if other["window_start_dt"] < a["window_end_dt"] and \
                a["window_start_dt"] < other["window_end_dt"]:
            raise ApiError("ERR_EXCLUSIVE_WINDOW_CONFLICT", 409,
                           "an exclusive SIGNED agreement overlaps this window")
    if a["window_end_dt"] <= now():
        raise ApiError("ERR_WINDOW_ELAPSED", 409, "the launch window has elapsed")
    a["status"] = "SIGNED"
    a["signed_at"] = fmt_iso(now())
    bump(a)
    return ok_object(ser_agreement(a))


# ---------------------------------------------------------------------------
# launch commitments
# ---------------------------------------------------------------------------


@bp.post("/launch-commitments")
def create_commitment():
    require_roles(SOURCING)
    data = body()
    agreement = req_fk(data, "agreement_id", DB.agreements, "ERR_AGREEMENT_NOT_FOUND")
    variant = req_fk(data, "variant_id", DB.variants, "ERR_VARIANT_NOT_FOUND")
    posture_gate(season_of_variant(variant))
    if agreement["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "commitments can only be placed against a SIGNED agreement")
    retail_ready = variant["lifecycle"] == "DR_TESTING" and any(
        m["variant_id"] == variant["id"] and m["status"] == "DECIDED_SCALE"
        for m in DB.media_tests.values()
    )
    if not retail_ready:
        raise ApiError("ERR_VARIANT_NOT_RETAIL_READY", 422,
                       "variant must be DR_TESTING with a DECIDED_SCALE media test")
    committed_units = req_int(data, "committed_units", min_v=1)
    need_by_dt = req_dt(data, "need_by_date")
    expected_version = req_int(data, "expected_agreement_version")
    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION", 412,
                       "expected_agreement_version does not match the agreement")
    if not (agreement["window_start_dt"] <= need_by_dt < agreement["window_end_dt"]):
        raise ApiError("ERR_COMMITMENT_OUTSIDE_WINDOW", 409,
                       "need_by_date must lie inside the agreement window")
    partner = DB.partners.get(variant.get("factory_partner_id"))
    free = partner["capacity_units_total"] - allocated_units(partner["id"])
    if committed_units > free:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "the partner's free capacity cannot cover the commitment")
    c = base_fields()
    c.update({
        "agreement_id": agreement["id"],
        "variant_id": variant["id"],
        "committed_units": committed_units,
        "need_by_date": fmt_iso(need_by_dt),
        "need_by_dt": need_by_dt,
        "status": "OPEN",
        "penalty_cents": 0,
    })
    DB.commitments[c["id"]] = c
    bump(agreement)  # OCC parent: every committed write invalidates observed versions
    return ok_object(ser_commitment(c), 201)


@bp.get("/launch-commitments/<cid>")
def get_commitment(cid):
    require_roles(ALL_ROLES)
    return ok_object(ser_commitment(get_or_404(DB.commitments, cid, "ERR_COMMITMENT_NOT_FOUND")))


@bp.get("/launch-commitments")
def list_commitments():
    require_roles(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    variant_id = request.args.get("variant_id")
    status = request.args.get("status")
    # error catalog: ERR_COMMITMENT_NOT_FOUND also covers an unresolvable FK filter
    if agreement_id is not None and agreement_id not in DB.agreements:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", 404,
                       "agreement_id filter does not resolve")
    if variant_id is not None and variant_id not in DB.variants:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", 404,
                       "variant_id filter does not resolve")
    items = by_creation(DB.commitments.values())
    if agreement_id is not None:
        items = [c for c in items if c["agreement_id"] == agreement_id]
    if variant_id is not None:
        items = [c for c in items if c["variant_id"] == variant_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_commitment(c) for c in items])


@bp.post("/launch-commitments/<cid>/cancel")
def cancel_commitment(cid):
    require_roles(SOURCING)
    c = get_or_404(DB.commitments, cid, "ERR_COMMITMENT_NOT_FOUND")
    posture_gate(season_of_variant(DB.variants.get(c["variant_id"])))
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "only an OPEN commitment can be cancelled")
    c["status"] = "CANCELLED"
    bump(c)
    return ok_object(ser_commitment(c))


# ---------------------------------------------------------------------------
# replenishment orders
# ---------------------------------------------------------------------------


@bp.post("/replenishment-orders")
def create_replenishment():
    require_roles(RETAIL_EXEC)
    data = body()
    variant = req_fk(data, "variant_id", DB.variants, "ERR_VARIANT_NOT_FOUND")
    posture_gate(season_of_variant(variant))
    if variant["lifecycle"] != "RETAIL_LIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "replenishment requires a RETAIL_LIVE variant")
    weekly_velocity = req_int(data, "weekly_velocity", min_v=0)
    on_hand_units = req_int(data, "on_hand_units", min_v=0)
    in_transit_units = req_int(data, "in_transit_units", min_v=0)
    case_pack_units = req_int(data, "case_pack_units", min_v=1)
    expected_version = req_int(data, "expected_variant_version")
    if expected_version != variant["version"]:
        raise ApiError("ERR_STALE_VARIANT_VERSION", 412,
                       "expected_variant_version does not match the variant")
    # pinned evaluation order: velocity gate -> raw need -> case-pack rounding
    # -> capacity -> quantity
    if weekly_velocity < CONSTANTS["REPLENISH_MIN_WEEKLY_UNITS"]:
        raise ApiError("ERR_VELOCITY_BELOW_THRESHOLD", 422,
                       "weekly velocity is below the replenishment threshold")
    raw_need = (CONSTANTS["COVER_WEEKS"] * weekly_velocity
                - on_hand_units - in_transit_units)
    if raw_need <= 0:
        raise ApiError("ERR_REPLENISHMENT_NOT_NEEDED", 422,
                       "no replenishment is needed at the reported inventory")
    rounded_need = ((raw_need + case_pack_units - 1) // case_pack_units) * case_pack_units
    partner = DB.partners.get(variant.get("factory_partner_id"))
    free = partner["capacity_units_total"] - allocated_units(partner["id"])
    if rounded_need > free:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "the partner's free capacity cannot cover the order")
    r = base_fields()
    r.update({
        "variant_id": variant["id"],
        "weekly_velocity": weekly_velocity,
        "on_hand_units": on_hand_units,
        "in_transit_units": in_transit_units,
        "case_pack_units": case_pack_units,
        "quantity_units": rounded_need,
        "status": "OPEN",
        "superseded_by_id": None,
    })
    DB.replenishments[r["id"]] = r
    # a new OPEN order supersedes any prior OPEN order for the same variant
    for old in DB.replenishments.values():
        if old["id"] != r["id"] and old["variant_id"] == variant["id"] \
                and old["status"] == "OPEN":
            old["status"] = "SUPERSEDED"
            old["superseded_by_id"] = r["id"]
            touch(old)
    bump(variant)  # OCC parent
    return ok_object(ser_replenishment(r), 201)
