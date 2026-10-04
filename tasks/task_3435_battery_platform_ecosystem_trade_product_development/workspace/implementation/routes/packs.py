"""Battery packs and chargers: catalog, certification pipeline, charge
estimates, and the pack-scoped counterfeit-case listing."""
from flask import Blueprint, request

import db
from constants import API_PREFIX, CELL_FORMATS, CERT_DECISIONS, ROLES
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    ok_list,
    ok_object,
    pagination,
    page_window,
    req_field,
    req_int,
    req_num,
    req_str,
)
from services import (
    bump,
    charge_estimate_fields,
    make_entity,
    platform_current_generation,
)
from views import view_case, view_charger, view_pack

bp = Blueprint("packs", __name__)


def _get_pack_or_404(pack_id):
    pack = db.STORE["packs"].get(pack_id)
    if pack is None:
        fail("ERR_NOT_FOUND", "Battery pack not found")
    return pack


@bp.route(f"{API_PREFIX}/battery-packs", methods=["POST"])
def create_pack():
    authorize(["ProductEngineer"])
    data = body()
    # Priority 4: body FK existence (platform_id)
    platform_id = req_field(data, "platform_id")
    platform = db.STORE["platforms"].get(platform_id)
    if platform is None:
        fail("ERR_NOT_FOUND", "platform_id does not reference an existing platform")
    # Priority 5: request shape
    sku = req_str(data, "sku")
    pack_generation = req_int(data, "pack_generation", minimum=1)
    cell_supplier_code = req_str(data, "cell_supplier_code")
    cell_format = req_str(data, "cell_format")
    if cell_format not in CELL_FORMATS:
        fail("ERR_VALIDATION", "cell_format must be C18650, C21700, or TABLESS")
    rated_capacity_wh = req_num(data, "rated_capacity_wh", gt=0)
    max_charge_rate_w = req_num(data, "max_charge_rate_w", gt=0)
    replacement_price_cents = req_int(data, "replacement_price_cents", minimum=0)
    warranty_days = req_int(data, "warranty_days", gt=0, multiple_of=30)
    free_replacement_days = req_int(data, "free_replacement_days", minimum=0)
    if free_replacement_days > warranty_days:
        fail("ERR_VALIDATION", "free_replacement_days may not exceed warranty_days")
    # Priority 11: uniqueness of sku
    for p in db.STORE["packs"].values():
        if p["sku"] == sku:
            fail("ERR_DUPLICATE_SKU", "A battery pack with this sku already exists")
    # Priority 12: generation ratchet
    if pack_generation > platform_current_generation(platform["id"]) + 1:
        fail("ERR_PACK_GENERATION_VIOLATION", "pack_generation exceeds the ratchet window")
    # Priority 17: RETIRED platform blocks pack creation
    if platform["status"] == "RETIRED":
        fail("ERR_PLATFORM_RETIRED", "Platform is RETIRED")
    pack = make_entity(
        {
            "platform_id": platform["id"],
            "sku": sku,
            "pack_generation": pack_generation,
            "cell_supplier_code": cell_supplier_code,
            "cell_format": cell_format,
            "rated_capacity_wh": rated_capacity_wh,
            "max_charge_rate_w": max_charge_rate_w,
            "replacement_price_cents": replacement_price_cents,
            "warranty_days": warranty_days,
            "free_replacement_days": free_replacement_days,
            "certification_status": "DESIGN",
            "submitted_by_user_id": None,
            "safety_hold": False,
        }
    )
    db.STORE["packs"][pack["id"]] = pack
    return ok_object(view_pack(pack), 201)


@bp.route(f"{API_PREFIX}/battery-packs/<pack_id>", methods=["GET"])
def get_pack(pack_id):
    authorize(ROLES)
    pack = _get_pack_or_404(pack_id)
    extra = None
    charger_id = request.args.get("charger_id")
    if charger_id:
        charger = db.STORE["chargers"].get(charger_id)
        if charger is None:
            fail("ERR_NOT_FOUND", "charger_id does not reference an existing charger")
        # Priority 10: cross-entity reference coherence
        if charger["platform_id"] != pack["platform_id"]:
            fail("ERR_INCOMPATIBLE_PAIRING", "Charger and pack belong to different platforms")
        extra = charge_estimate_fields(pack, charger)
    return ok_object(view_pack(pack, extra))


@bp.route(f"{API_PREFIX}/battery-packs", methods=["GET"])
def list_packs():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["packs"].values())
    platform_id = request.args.get("platform_id")
    if platform_id is not None:
        items = [p for p in items if p["platform_id"] == platform_id]
    cert = request.args.get("certification_status")
    if cert is not None:
        items = [p for p in items if p["certification_status"] == cert]
    page, total = page_window(items, limit, offset)
    return ok_list([view_pack(p) for p in page], total, limit, offset)


@bp.route(f"{API_PREFIX}/battery-packs/<pack_id>/submit-certification", methods=["POST"])
def submit_certification(pack_id):
    user_id, _ = authorize(["ProductEngineer"])
    pack = _get_pack_or_404(pack_id)
    # Priority 6: valid from-state (DESIGN or REJECTED)
    if pack["certification_status"] not in ("DESIGN", "REJECTED"):
        fail("ERR_INVALID_STATE", "Pack is not in DESIGN or REJECTED")
    # Priority 17: RETIRED platform blocks submission
    platform = db.STORE["platforms"][pack["platform_id"]]
    if platform["status"] == "RETIRED":
        fail("ERR_PLATFORM_RETIRED", "Platform is RETIRED")
    pack["certification_status"] = "SUBMITTED"
    pack["submitted_by_user_id"] = user_id
    bump(pack)
    return ok_object(view_pack(pack))


@bp.route(f"{API_PREFIX}/battery-packs/<pack_id>/decide-certification", methods=["POST"])
def decide_certification(pack_id):
    user_id, _ = authorize(["ComplianceEngineer"])
    pack = _get_pack_or_404(pack_id)
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", CERT_DECISIONS)
    # Priority 6: valid from-state
    if pack["certification_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Pack is not SUBMITTED")
    # Priority 7: segregation of duties
    if user_id == pack["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from the submitter")
    pack["certification_status"] = decision
    bump(pack)
    if decision == "CERTIFIED":
        # Recompute trigger for platform.current_generation: bump platform version.
        bump(db.STORE["platforms"][pack["platform_id"]])
    return ok_object(view_pack(pack))


@bp.route(f"{API_PREFIX}/battery-packs/<pack_id>/counterfeit-cases", methods=["GET"])
def list_pack_cases(pack_id):
    authorize(ROLES)
    _get_pack_or_404(pack_id)
    limit, offset = pagination()
    items = [c for c in db.STORE["cases"].values() if c["battery_pack_id"] == pack_id]
    page, total = page_window(items, limit, offset)
    return ok_list([view_case(c) for c in page], total, limit, offset)


# ------------------------------------------------------------- chargers ----
@bp.route(f"{API_PREFIX}/chargers", methods=["POST"])
def create_charger():
    authorize(["ProductEngineer"])
    data = body()
    platform_id = req_field(data, "platform_id")
    if db.STORE["platforms"].get(platform_id) is None:
        fail("ERR_NOT_FOUND", "platform_id does not reference an existing platform")
    model_code = req_str(data, "model_code")
    charger_generation = req_int(data, "charger_generation", minimum=1)
    max_charge_rate_w = req_num(data, "max_charge_rate_w", gt=0)
    for c in db.STORE["chargers"].values():
        if c["model_code"] == model_code:
            fail("ERR_DUPLICATE_SKU", "A charger with this model_code already exists")
    charger = make_entity(
        {
            "platform_id": platform_id,
            "model_code": model_code,
            "charger_generation": charger_generation,
            "max_charge_rate_w": max_charge_rate_w,
        }
    )
    db.STORE["chargers"][charger["id"]] = charger
    return ok_object(view_charger(charger), 201)


@bp.route(f"{API_PREFIX}/chargers/<charger_id>", methods=["GET"])
def get_charger(charger_id):
    authorize(ROLES)
    charger = db.STORE["chargers"].get(charger_id)
    if charger is None:
        fail("ERR_NOT_FOUND", "Charger not found")
    return ok_object(view_charger(charger))


@bp.route(f"{API_PREFIX}/chargers", methods=["GET"])
def list_chargers():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["chargers"].values())
    platform_id = request.args.get("platform_id")
    if platform_id is not None:
        items = [c for c in items if c["platform_id"] == platform_id]
    page, total = page_window(items, limit, offset)
    return ok_list([view_charger(c) for c in page], total, limit, offset)
