"""Product configurations, jurisdiction programs, allocation batches, cartons."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from middleware import guard
from clockutil import parse_ts, clock, fmt
from db import STORE as D
from services import derive as _derive
from services import calc as C
from routes import common as K

bp = Blueprint("reference", __name__)

PRESENTATIONS = ["SINGLE_DOSE_VIAL", "MULTI_DOSE_VIAL"]
ALLOCATION_BASIS = ["POPULATION_SHARE", "FIXED_QUANTITY"]
SEGMENT_RULES = ["TIE_CONTINUE", "STOP"]
CAPABILITIES = ["ULTRA_COLD", "REFRIGERATED", "AMBIENT_ONLY"]
EQUIPMENT_TYPES = ["ULTRA_COLD_FREEZER", "THERMAL_SHIPPER"]
OUTCOMES = ["PASSED", "FAILED"]
BATCH_STATUSES = ["DRAFT", "RELEASED", "ALLOCATED", "DEPLETED", "EXPIRED", "RECALLED"]
CARTON_STATES = ["ULTRA_COLD", "THAWED", "REFRIGERATED", "PUNCTURED", "EXPIRED",
                 "IN_TRANSIT", "PALLET_STAGED", "DESTROYED"]


# ---------------------------------------------------------------------------
# ProductConfiguration
# ---------------------------------------------------------------------------
@bp.route("/product-configurations", methods=["POST"])
def create_product_configuration():
    guard("POST /vaccine-distribution/product-configurations")
    data = K.body()
    product_code = K.as_str(K.required(data, "product_code"), "product_code")
    for existing in h.all("product_configurations"):
        if existing.get("product_code") == product_code:
            raise ApiError("ERR_INVALID_REQUEST", "product_code must be unique.")
    presentation = K.as_enum(K.required(data, "presentation"), PRESENTATIONS, "presentation")
    doses_per_vial = K.as_int(K.required(data, "doses_per_vial"), "doses_per_vial")
    min_order_cartons = K.as_int(K.required(data, "min_order_cartons"), "min_order_cartons")

    rec = h.create("product_configurations", {
        "product_code": product_code,
        "presentation": presentation,
        "doses_per_vial": doses_per_vial,
        "vials_per_carton": K.opt_int(data, "vials_per_carton", 195),
        "cartons_per_pallet": K.opt_int(data, "cartons_per_pallet", 12),
        "ship_box_cartons": K.opt_int(data, "ship_box_cartons", 5),
        "min_order_cartons": min_order_cartons,
        "ultra_cold_min_c": K.opt_num(data, "ultra_cold_min_c", -90),
        "ultra_cold_max_c": K.opt_num(data, "ultra_cold_max_c", -60),
        "refrigerated_min_c": K.opt_num(data, "refrigerated_min_c", 2),
        "refrigerated_max_c": K.opt_num(data, "refrigerated_max_c", 8),
        "thaw_stability_hours": K.opt_int(data, "thaw_stability_hours", 120),
        "refrigerated_shelf_life_hours": K.opt_int(data, "refrigerated_shelf_life_hours", 720),
        "excursion_tolerance_min_c": K.opt_num(data, "excursion_tolerance_min_c", -50),
        "excursion_max_single_breach_minutes":
            K.opt_int(data, "excursion_max_single_breach_minutes", 180),
        "excursion_max_cumulative_minutes":
            K.opt_int(data, "excursion_max_cumulative_minutes", 360),
        "refreeze_prohibited": K.opt_bool(data, "refreeze_prohibited", True),
        "punctured_bud_hours": K.opt_int(data, "punctured_bud_hours", 6),
        "wastage_threshold_pct": K.opt_num(data, "wastage_threshold_pct", 0.05),
        "doses_per_carton": doses_per_vial * K.opt_int(data, "vials_per_carton", 195),
    })
    return K.created(rec)


@bp.route("/product-configurations", methods=["GET"])
def list_product_configurations():
    guard("GET /vaccine-distribution/product-configurations")
    return K.list_response(h.all("product_configurations"),
                           {"product_code": K.eq("product_code")})


@bp.route("/product-configurations/<pid>", methods=["GET"])
def get_product_configuration(pid):
    guard("GET /vaccine-distribution/product-configurations/{id}")
    return K.single(K.fetch("product_configurations", pid, "Product configuration"))


# ---------------------------------------------------------------------------
# JurisdictionProgram
# ---------------------------------------------------------------------------
@bp.route("/jurisdiction-programs", methods=["POST"])
def create_jurisdiction_program():
    guard("POST /vaccine-distribution/jurisdiction-programs")
    data = K.body()
    code = K.as_str(K.required(data, "jurisdiction_code"), "jurisdiction_code")
    for existing in h.all("jurisdiction_programs"):
        if existing.get("jurisdiction_code") == code:
            raise ApiError("ERR_INVALID_REQUEST", "jurisdiction_code must be unique.")
    rec = h.create("jurisdiction_programs", {
        "jurisdiction_code": code,
        "regulatory_body": K.as_str(K.required(data, "regulatory_body"), "regulatory_body"),
        "allocation_basis": K.as_enum(K.required(data, "allocation_basis"),
                                      ALLOCATION_BASIS, "allocation_basis"),
        "population_weight": K.opt_num(data, "population_weight", 0),
        "fixed_weekly_cartons": K.opt_int(data, "fixed_weekly_cartons", 0),
        "weekly_allocation_cap_cartons":
            K.as_int(K.required(data, "weekly_allocation_cap_cartons"),
                     "weekly_allocation_cap_cartons"),
        "min_order_cartons": K.opt_int(data, "min_order_cartons", 2),
        "reservable_carton_pct": K.opt_num(data, "reservable_carton_pct", 0.5),
        "acceptance_window_hours":
            K.as_int(K.required(data, "acceptance_window_hours"), "acceptance_window_hours"),
        "shipping_days": K.as_array(K.required(data, "shipping_days"), "shipping_days"),
        "shipping_cutoff_utc":
            K.as_str(K.required(data, "shipping_cutoff_utc"), "shipping_cutoff_utc"),
        "quarantine_on_review":
            K.as_bool(K.required(data, "quarantine_on_review"), "quarantine_on_review"),
        "adjudication_sla_hours":
            K.as_int(K.required(data, "adjudication_sla_hours"), "adjudication_sla_hours"),
        "segment_rule": K.as_enum(K.required(data, "segment_rule"), SEGMENT_RULES, "segment_rule"),
        "reporting_period_days":
            K.as_int(K.required(data, "reporting_period_days"), "reporting_period_days"),
        "released_cartons_to_date": 0,
        "credit_balance_cartons": 0,
        "lapsed_carton_count": 0,
        "standing_status": "OPEN",
    })
    return K.created(rec)


@bp.route("/jurisdiction-programs", methods=["GET"])
def list_jurisdiction_programs():
    guard("GET /vaccine-distribution/jurisdiction-programs")
    return K.list_response(h.all("jurisdiction_programs"),
                           {"jurisdiction_code": K.eq("jurisdiction_code")})


@bp.route("/jurisdiction-programs/<pid>", methods=["GET"])
def get_jurisdiction_program(pid):
    guard("GET /vaccine-distribution/jurisdiction-programs/{id}")
    return K.single(K.fetch("jurisdiction_programs", pid, "Jurisdiction program"))


@bp.route("/jurisdiction-programs/<pid>/sites", methods=["GET"])
def list_program_sites(pid):
    guard("GET /vaccine-distribution/jurisdiction-programs/{id}/sites")
    K.fetch("jurisdiction_programs", pid, "Jurisdiction program")
    return K.list_response(h.find("storage_sites", jurisdiction_program_id=pid))


@bp.route("/jurisdiction-programs/<pid>/standings", methods=["GET"])
def list_program_standings(pid):
    guard("GET /vaccine-distribution/jurisdiction-programs/{id}/standings")
    K.fetch("jurisdiction_programs", pid, "Jurisdiction program")
    return K.list_response(h.find("program_standings", jurisdiction_program_id=pid))


@bp.route("/jurisdiction-programs/<pid>/reporting-periods", methods=["GET"])
def list_program_periods(pid):
    guard("GET /vaccine-distribution/jurisdiction-programs/{id}/reporting-periods")
    K.fetch("jurisdiction_programs", pid, "Jurisdiction program")
    return K.list_response(h.find("reporting_periods", jurisdiction_program_id=pid))


# ---------------------------------------------------------------------------
# AllocationBatch
# ---------------------------------------------------------------------------
@bp.route("/allocation-batches", methods=["POST"])
def create_batch():
    guard("POST /vaccine-distribution/allocation-batches")
    data = K.body()
    code = K.as_str(K.required(data, "batch_code"), "batch_code")
    for existing in h.all("allocation_batches"):
        if existing.get("batch_code") == code:
            raise ApiError("ERR_INVALID_REQUEST", "batch_code must be unique.")
    product = K.fetch("product_configurations", K.required(data, "product_configuration_id"),
                      "Product configuration")
    program = K.fetch("jurisdiction_programs", K.required(data, "jurisdiction_program_id"),
                      "Jurisdiction program")
    rec = h.create("allocation_batches", {
        "batch_code": code,
        "product_configuration_id": product["id"],
        "jurisdiction_program_id": program["id"],
        "released_cartons": K.as_int(K.required(data, "released_cartons"), "released_cartons"),
        "release_date": K.as_ts(K.required(data, "release_date"), "release_date"),
        "expiry_date": K.as_ts(K.required(data, "expiry_date"), "expiry_date"),
        "status": "DRAFT",
        "allocated_cartons": 0,
        "unallocated_cartons": 0,
        "doses_released_total": 0,
        "release_cartons_at": None,
    })
    _derive.recompute_batch(rec)
    return K.created(rec)


def _batch_filters():
    return {
        "product_configuration_id": K.eq("product_configuration_id"),
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "status": K.eq("status"),
    }


@bp.route("/allocation-batches", methods=["GET"])
def list_batches():
    guard("GET /vaccine-distribution/allocation-batches")
    return K.list_response(h.all("allocation_batches"), _batch_filters())


@bp.route("/allocation-batches/<bid>", methods=["GET"])
def get_batch(bid):
    guard("GET /vaccine-distribution/allocation-batches/{id}")
    return K.single(K.fetch("allocation_batches", bid, "Allocation batch"))


@bp.route("/allocation-batches/<bid>/cartons", methods=["POST"])
def create_carton(bid):
    guard("POST /vaccine-distribution/allocation-batches/{id}/cartons")
    batch = K.fetch("allocation_batches", bid, "Allocation batch")
    data = K.body()
    serial = K.as_str(K.required(data, "carton_serial"), "carton_serial")
    for existing in h.all("cartons"):
        if existing.get("carton_serial") == serial:
            raise ApiError("ERR_INVALID_REQUEST", "carton_serial must be unique.")
    vials = K.as_int(K.required(data, "vials_per_carton"), "vials_per_carton")
    product = _derive.product_of_batch(batch)
    rec = h.create("cartons", {
        "allocation_batch_id": batch["id"],
        "cold_chain_shipper_id": None,
        "carton_serial": serial,
        "vials_per_carton": vials,
        "doses_per_carton": (product.get("doses_per_vial", 0) * vials) if product else 0,
        "temperature_state": "ULTRA_COLD",
        "thawed_at": None,
        "thaw_window_expires_at": None,
        "current_expires_at": None,
        "expired_at": None,
        "remaining_doses": (product.get("doses_per_vial", 0) * vials) if product else 0,
        "administrative_remaining_doses":
            (product.get("doses_per_vial", 0) * vials) if product else 0,
        "cumulative_released_doses": 0,
        "administrative_expired": False,
        "dose_shortfall_doses": 0,
        "_puncture_at": None,
    })
    h.touch(batch)
    _derive.recompute_sites_for_carton(rec)
    return K.created(rec)


@bp.route("/allocation-batches/<bid>/cartons", methods=["GET"])
def list_batch_cartons(bid):
    guard("GET /vaccine-distribution/allocation-batches/{id}/cartons")
    K.fetch("allocation_batches", bid, "Allocation batch")
    return K.list_response(h.find("cartons", allocation_batch_id=bid))


@bp.route("/allocation-batches/<bid>/release", methods=["POST"])
def release_batch(bid):
    guard("POST /vaccine-distribution/allocation-batches/{id}/release")
    batch = K.fetch("allocation_batches", bid, "Allocation batch")
    K.ensure_not_terminal(batch, "allocation_batches")
    if batch.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT batch may be released.")
    program = _derive.program_of_batch(batch)
    product = _derive.product_of_batch(batch)
    # 1. the owning program must not be FROZEN
    if program and program.get("standing_status") == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN")
    # 2. the batch must expire strictly after the logical clock
    expiry = parse_ts(batch.get("expiry_date"))
    if expiry is None or expiry <= clock():
        raise ApiError("ERR_BATCH_ALREADY_EXPIRED")
    # 3. released_cartons >= the product's min_order_cartons
    if product and batch.get("released_cartons", 0) < product.get("min_order_cartons", 0):
        raise ApiError("ERR_BELOW_MIN_ORDER")

    batch["status"] = "RELEASED"
    batch["release_cartons_at"] = h.now_iso()
    batch["allocated_cartons"] = 0
    batch["unallocated_cartons"] = batch.get("released_cartons", 0)
    h.touch(batch)
    _derive.recompute_batch(batch)
    return K.single(batch)


@bp.route("/allocation-batches/<bid>/recall", methods=["POST"])
def recall_batch(bid):
    guard("POST /vaccine-distribution/allocation-batches/{id}/recall")
    batch = K.fetch("allocation_batches", bid, "Allocation batch")
    data = K.body()
    if batch.get("status") not in ("DRAFT", "RELEASED", "ALLOCATED"):
        raise ApiError("ERR_BATCH_NOT_RECALLABLE")
    batch["status"] = "RECALLED"
    if K.has(data, "reason"):
        batch["recall_reason"] = K.as_str(data["reason"], "reason")
    for carton in _derive.cartons_of_batch(batch["id"]):
        if carton.get("temperature_state") == "DESTROYED":
            continue
        carton["temperature_state"] = "DESTROYED"
        # The recall appends a zero-quantity DESTROY entry for each carton it
        # destroys (PRD §3.1).  remaining_doses is zeroed rather than left at the
        # nominal pack size, because a destroyed carton carries no live doses.
        carton["remaining_doses"] = 0
        carton["administrative_remaining_doses"] = 0
        carton["current_expires_at"] = None
        carton["thaw_window_expires_at"] = None
        _append_entry(carton, "DESTROY", 0, h.now_iso())
        _derive.recompute_carton(carton)
        carton["cumulative_released_doses"] -= carton.get("cumulative_released_doses", 0)
    for ent in _derive.entitlements_of_batch(batch["id"]):
        if ent.get("available_cartons", 0) > 0:
            ent["acceptance_status"] = "LAPSED"
            ent["held_cartons"] = 0
            _derive.recompute_entitlement(ent)
    h.touch(batch)
    _derive.recompute_batch(batch)
    K.recompute_all_sites()
    return K.single(batch)


# ---------------------------------------------------------------------------
# Carton reads / actions that live on the carton resource
# ---------------------------------------------------------------------------
@bp.route("/cartons", methods=["GET"])
def list_cartons():
    guard("GET /vaccine-distribution/cartons")
    return K.list_response(h.all("cartons"), {
        "allocation_batch_id": K.eq("allocation_batch_id"),
        "cold_chain_shipper_id": K.eq("cold_chain_shipper_id"),
        "temperature_state": K.eq("temperature_state"),
    })


@bp.route("/cartons/<cid>", methods=["GET"])
def get_carton(cid):
    guard("GET /vaccine-distribution/cartons/{id}")
    return K.single(K.fetch("cartons", cid, "Carton"))


def _append_entry(carton, entry_type, quantity, occurred_at, reverses=None):
    rec = h.create("dose_ledger_entries", {
        "carton_id": carton["id"],
        "entry_type": entry_type,
        "quantity_doses": quantity,
        "occurred_at": occurred_at,
        "site_id": _site_for_carton(carton),
        "reverses_entry_id": reverses,
        "status": "RECORDED",
    })
    return rec


def _site_for_carton(carton):
    for disp in h.all("dispatch_orders"):
        if disp.get("status") in ("DELIVERED", "PACKED", "IN_TRANSIT"):
            if any(c["id"] == carton["id"] for c in _derive.cartons_of_dispatch(disp)):
                return disp.get("storage_site_id")
    for tr in h.all("site_transfers"):
        if tr.get("status") == "RECEIVED" and tr.get("carton_id") == carton["id"]:
            return tr.get("to_site_id")
    return None