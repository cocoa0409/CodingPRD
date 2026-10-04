"""Model versions, takeoff lines, assemblies and racks."""

from core import (CLOCK, DB, fail, new_record, num, rhu, takeoff_hash, to_dt,
                  touch)
from calculations import conduit_craft_hours

PERMITTED_CONDUIT_TYPES = (
    "MC_CABLE", "EMT_OVERHEAD", "EMT_EMBEDDED", "RIGID_RACK",
    "OVERHEAD_RACK", "UNDERGROUND_DUCTBANK", "ALUMINUM_RACEWAY",
)


# --------------------------------------------------------------------------
# ModelVersion
# --------------------------------------------------------------------------

def create_model_version(body):
    model_version = new_record(
        model_id=body.get("model_id"),
        revision_letter=body.get("revision_letter"),
        status=body.get("status") or "DRAFT",
        zone_quantity_total=0.0,
        assembly_quantity_total={},
        empty_takeoff=True,
        coordinated_at_iso=None,
    )
    DB.put("model_versions", model_version)
    return model_version


def require_model_version(model_version_id, error_id="ERR_MODEL_VERSION_NOT_FOUND"):
    if not model_version_id:
        fail(error_id)
    record = DB.find("model_versions", model_version_id)
    if record is None:
        fail(error_id)
    return record


def recompute_model_version_quantities(model_version):
    total = 0.0
    grouped = {}
    for line in DB.all("takeoff_lines"):
        if line.get("model_version_id") != model_version["id"]:
            continue
        if line.get("status") == "SUPERSEDED":
            continue
        quantity = num(line.get("quantity"), 0.0)
        total += quantity
        code = line.get("assembly_code")
        grouped[code] = rhu(num(grouped.get(code), 0.0) + quantity, 4)
    model_version["zone_quantity_total"] = rhu(total, 4)
    model_version["assembly_quantity_total"] = grouped
    model_version["empty_takeoff"] = model_version["zone_quantity_total"] <= 0
    for line in DB.all("takeoff_lines"):
        if line.get("model_version_id") == model_version["id"]:
            line["crafted_hours"] = conduit_craft_hours(line)
    return model_version


def duplicate_takeoff_hash(model_version_id, digest):
    for line in DB.all("takeoff_lines"):
        if line.get("model_version_id") == model_version_id and line.get("takeoff_hash") == digest:
            return line
    return None


def coordinate_model_version(model_version):
    if model_version.get("status") != "DRAFT":
        fail("ERR_INVALID_PREFAB_TRANSITION")
    seen = set()
    for line in DB.all("takeoff_lines"):
        if line.get("model_version_id") != model_version["id"]:
            continue
        digest = line.get("takeoff_hash")
        if digest in seen:
            fail("ERR_DUPLICATE_TAKEOFF_LINE")
        seen.add(digest)
    recompute_model_version_quantities(model_version)
    if num(model_version.get("zone_quantity_total"), 0.0) < 1 or model_version.get("empty_takeoff"):
        fail("ERR_MODEL_QUANTITY_UNRESOLVED")
    model_version["status"] = "COORDINATED"
    model_version["coordinated_at_iso"] = CLOCK.now_iso()
    recompute_model_version_quantities(model_version)
    touch(model_version)
    return model_version


def supersede_model_version(model_version):
    model_version["status"] = "SUPERSEDED"
    touch(model_version)
    return model_version


# --------------------------------------------------------------------------
# TakeoffLine
# --------------------------------------------------------------------------

def create_takeoff_line(body):
    model_version = require_model_version(body.get("model_version_id"))

    digest = takeoff_hash(model_version["id"], body.get("zone_code"),
                          body.get("assembly_code"), body.get("quantity"))
    if duplicate_takeoff_hash(model_version["id"], digest) is not None:
        fail("ERR_DUPLICATE_TAKEOFF_LINE")

    if num(body.get("quantity"), 0.0) <= 0:
        fail("ERR_MODEL_QUANTITY_UNRESOLVED", "quantity must be positive")

    assembly = DB.find("assemblies", body.get("assembly_code"))
    ideal = (assembly or {}).get("ideal_conduit_type_codes") or []
    if body.get("conduit_run_type") not in PERMITTED_CONDUIT_TYPES:
        fail("ERR_CONDUIT_TYPE_NOT_PERMITTED")
    if assembly is None or body.get("conduit_run_type_code") not in ideal:
        fail("ERR_CONDUIT_TYPE_NOT_PERMITTED")

    line = new_record(
        model_version_id=model_version["id"],
        zone_code=body.get("zone_code"),
        assembly_code=body.get("assembly_code"),
        conduit_run_type=body.get("conduit_run_type"),
        conduit_run_type_code=body.get("conduit_run_type_code"),
        quantity=num(body.get("quantity"), 0.0),
        prefab_share_pct=num(body.get("prefab_share_pct"), 0.0),
        takeoff_hash=digest,
        status="EXTRACTED",
        crafted_hours=0.0,
    )
    DB.put("takeoff_lines", line)
    recompute_model_version_quantities(model_version)
    touch(model_version)
    line["crafted_hours"] = conduit_craft_hours(line)
    return line


def mark_line_superseded(line):
    line["status"] = "SUPERSEDED"
    line["crafted_hours"] = 0.0
    touch(line)
    return line


def find_takeoff_by_hash(digest):
    for line in DB.all("takeoff_lines"):
        if line.get("takeoff_hash") == digest:
            return line
    return None


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def create_assembly(body):
    code = body.get("assembly_code")
    record = new_record(
        assembly_code=code,
        assembly_kind=body.get("assembly_kind"),
        unit_of_measure=body.get("unit_of_measure"),
        prefab_hours_per_unit=num(body.get("prefab_hours_per_unit"), 0.0),
        field_hours_per_unit=num(body.get("field_hours_per_unit"), 0.0),
        supported_field_hours_per_unit=num(body.get("supported_field_hours_per_unit"), 0.0),
        field_productivity_factor=num(body.get("field_productivity_factor"), 1.0),
        ideal_conduit_type_codes=list(body.get("ideal_conduit_type_codes") or []),
        conduit_labor_factors=dict(body.get("conduit_labor_factors") or {}),
        material_price_cents=num(body.get("material_price_cents"), 0.0),
        core_charge_cents=num(body.get("core_charge_cents"), 0.0),
        recycled_credit_cents=num(body.get("recycled_credit_cents"), 0.0),
        is_switchgear=bool(body.get("is_switchgear", False)),
    )
    record["id"] = code
    DB.put("assemblies", record)
    return record


# --------------------------------------------------------------------------
# Rack
# --------------------------------------------------------------------------

def create_rack(body):
    model_version = require_model_version(body.get("model_version_id"))
    rack = new_record(
        model_version_id=model_version["id"],
        rack_code=body.get("rack_code"),
        zone_code=body.get("zone_code"),
        top_elevation_ft=num(body.get("top_elevation_ft"), 0.0),
        rack_hoist_date=body.get("rack_hoist_date"),
        value_capacity_cf=num(body.get("value_capacity_cf"), 0.0),
        direct_assignment=bool(body.get("direct_assignment", False)),
        ordering_strength_rule=body.get("ordering_strength_rule"),
        reserved_streams_and_phase_cf=0.0,
    )
    DB.put("racks", rack)
    return rack


def rack_unique_in_version(model_version_id, rack_code):
    for rack in DB.all("racks"):
        if rack.get("model_version_id") == model_version_id and rack.get("rack_code") == rack_code:
            return rack
    return None


def find_rack_by_code(rack_code):
    for rack in DB.all("racks"):
        if rack.get("rack_code") == rack_code:
            return rack
    return None


def filter_model_versions(args):
    records = DB.all("model_versions")
    model_id = args.get("model_id")
    if model_id:
        records = [r for r in records if r.get("model_id") == model_id]
    return records


def filter_takeoff_lines(args):
    records = DB.all("takeoff_lines")
    model_version_id = args.get("model_version_id")
    if model_version_id:
        records = [r for r in records if r.get("model_version_id") == model_version_id]
    return records


def filter_racks(args):
    records = DB.all("racks")
    model_version_id = args.get("model_version_id")
    if model_version_id:
        records = [r for r in records if r.get("model_version_id") == model_version_id]
    return records