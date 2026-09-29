"""Bin designs: geometry, loading, the analysis register and the seal cycle."""
from flask import Blueprint, request

import calc
import serializers
import store
from authz import ALL_ROLES, authorize
from common import add_days
from envelope import created, ok, paginated
from errors import ApiError
from routes_config import find_config
from routes_parties import find_dealer
from shape import body, req_enum, req_int, req_int_enum, req_num, req_str
from store import insert, touch

bp = Blueprint("designs", __name__)

DESIGN_METHODS = ("ASD", "LRFD")
ROOF_PITCHES = (25, 30, 35)


def find_design(row_id):
    row = store.bin_designs.get(row_id)
    if row is None:
        raise ApiError("ERR_BIN_DESIGN_NOT_FOUND")
    return row


def acting_engineer(user_id):
    """Ladder step 6: the entity-backed engineer identity must resolve."""
    row = store.engineers.get(user_id)
    if row is None:
        raise ApiError("ERR_ENGINEER_SCOPE_VIOLATION")
    return row


def check_licensure(engineer, jurisdiction):
    """Ladder step 15: licence standing then jurisdiction licensure."""
    if engineer["status"] != "ACTIVE":
        raise ApiError("ERR_ENGINEER_LICENSE_LAPSED")
    if jurisdiction["code"] not in engineer["licensed_jurisdiction_codes"]:
        raise ApiError("ERR_ENGINEER_NOT_LICENSED_IN_JURISDICTION")


def check_safety_gates(moisture_pct, design_wind_speed_mph, coating, jurisdiction):
    """Ladder steps 9 and 10, in that order."""
    if moisture_pct > coating["max_ambient_moisture_pct"]:
        raise ApiError("ERR_MOISTURE_EXCEEDS_COATING_LIMIT")
    if design_wind_speed_mph < jurisdiction["min_design_wind_speed_mph"]:
        raise ApiError("ERR_WIND_BELOW_JURISDICTION_MINIMUM")


def run_pipeline(design, jurisdiction, grain_profile, coating):
    """Refresh every computed geometry and structural field on the row."""
    geometry = calc.bin_geometry(
        design["diameter_m"], design["eave_height_m"], design["roof_pitch_deg"]
    )
    design.update(geometry)
    demands = calc.load_demands(
        design["eave_height_m"],
        design["diameter_m"],
        design["design_wind_speed_mph"],
        design["moisture_pct"],
        grain_profile["bulk_density_kg_per_m3"],
        grain_profile["janssen_k_ratio"],
        grain_profile["max_safe_moisture_pct"],
        jurisdiction["seismic_design_category"],
    )
    design.update(demands)
    envelope = calc.stiffener_envelope(
        demands["governing_demand_kpa"],
        geometry["circumference_m"],
        design["design_wind_speed_mph"],
        design["design_method"],
    )
    design["required_stiffener_count"] = envelope["required_stiffener_count"]
    design["utilization_ratio"] = envelope["utilization_ratio"]
    design["sheet_gauge_mm"] = envelope["sheet_gauge_mm"]
    design["roof_ring_required"] = envelope["roof_ring_required"]
    return design


@bp.post("/bin-designs")
def create_design():
    user_id, _ = authorize(("DesignEngineer",))
    payload = body()
    dealer_id = req_str(payload, "dealer_id")
    jurisdiction_id = req_str(payload, "jurisdiction_id")
    grain_profile_id = req_str(payload, "grain_profile_id")
    coating_spec_id = req_str(payload, "coating_spec_id")
    diameter_m = req_num(payload, "diameter_m", minimum="4.0", maximum="30.0")
    eave_height_m = req_num(payload, "eave_height_m", minimum="3.2", maximum="24.0")
    roof_pitch_deg = req_int_enum(payload, "roof_pitch_deg", ROOF_PITCHES)
    design_wind_speed_mph = req_int(payload, "design_wind_speed_mph", minimum=80, maximum=200)
    moisture_pct = req_num(payload, "moisture_pct", minimum="8.0", maximum="24.0")
    design_method = req_enum(payload, "design_method", DESIGN_METHODS)

    find_dealer(dealer_id)
    jurisdiction = find_config(store.jurisdictions, jurisdiction_id)
    grain_profile = find_config(store.grain_profiles, grain_profile_id)
    coating = find_config(store.coating_specs, coating_spec_id)

    engineer = acting_engineer(user_id)
    check_safety_gates(moisture_pct, design_wind_speed_mph, coating, jurisdiction)
    check_licensure(engineer, jurisdiction)

    design = {
        "dealer_id": dealer_id,
        "jurisdiction_id": jurisdiction_id,
        "grain_profile_id": grain_profile_id,
        "coating_spec_id": coating_spec_id,
        "author_engineer_id": user_id,
        "sealed_by_engineer_id": None,
        "diameter_m": diameter_m,
        "eave_height_m": eave_height_m,
        "roof_pitch_deg": roof_pitch_deg,
        "design_wind_speed_mph": design_wind_speed_mph,
        "moisture_pct": moisture_pct,
        "design_method": design_method,
        "seal_required": jurisdiction["seal_required"],
        "revision_round": 0,
        "sealed_at": None,
        "permit_ready_at": None,
        "status": "DRAFT",
    }
    run_pipeline(design, jurisdiction, grain_profile, coating)
    insert(store.bin_designs, design)
    return created(serializers.bin_design(design))


@bp.get("/bin-designs")
def list_designs():
    authorize(ALL_ROLES)
    rows = store.ordered(store.bin_designs)
    for field in (
        "dealer_id",
        "jurisdiction_id",
        "grain_profile_id",
        "coating_spec_id",
        "author_engineer_id",
        "sealed_by_engineer_id",
    ):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row[field] == value]
    return paginated(rows, serializers.bin_design)


@bp.get("/bin-designs/<row_id>")
def read_design(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.bin_design(find_design(row_id)))


@bp.post("/bin-designs/<row_id>/analyses")
def create_analysis(row_id):
    user_id, _ = authorize(("DesignEngineer",))
    payload = body()
    design_method = req_enum(payload, "design_method", DESIGN_METHODS)
    expected_version = req_int(payload, "expected_bin_design_version")

    design = find_design(row_id)
    acting_engineer(user_id)

    if expected_version != design["version"]:
        raise ApiError("ERR_STALE_DESIGN_VERSION")

    envelope = calc.stiffener_envelope(
        design["governing_demand_kpa"],
        design["circumference_m"],
        design["design_wind_speed_mph"],
        design_method,
    )
    existing = store.analyses_of_design(design["id"])
    next_index = max([row["analysis_index"] for row in existing], default=0) + 1

    analysis = {
        "bin_design_id": design["id"],
        "design_method": design_method,
        "allowable_kpa_m": envelope["allowable_kpa_m"],
        "governing_load_case": design["governing_load_case"],
        "governing_demand_kpa": design["governing_demand_kpa"],
        "required_stiffener_count": envelope["required_stiffener_count"],
        "utilization_ratio": envelope["utilization_ratio"],
        "verdict": envelope["verdict"],
        "analysis_index": next_index,
        "superseded": False,
    }
    insert(store.design_analyses, analysis)
    touch(design)
    return created(serializers.design_analysis(analysis))


@bp.get("/bin-designs/<row_id>/analyses")
def list_analyses(row_id):
    authorize(ALL_ROLES)
    design = find_design(row_id)
    return paginated(store.analyses_of_design(design["id"]), serializers.design_analysis)


@bp.post("/bin-designs/<row_id>/submit-review")
def submit_review(row_id):
    user_id, _ = authorize(("DesignEngineer",))
    design = find_design(row_id)
    acting_engineer(user_id)

    if design["status"] != "DRAFT":
        raise ApiError("ERR_DESIGN_STATE_INVALID")

    candidates = [
        row
        for row in store.analyses_of_design(design["id"])
        if not row["superseded"] and row["design_method"] == design["design_method"]
    ]
    if not candidates:
        raise ApiError("ERR_NO_PASSING_ANALYSIS")
    governing = max(candidates, key=lambda row: row["analysis_index"])
    if governing["verdict"] == "FAIL":
        raise ApiError("ERR_DESIGN_ANALYSIS_FAILED")

    design["status"] = "UNDER_REVIEW"
    touch(design)
    return ok(serializers.bin_design(design))


@bp.post("/bin-designs/<row_id>/request-revision")
def request_revision(row_id):
    user_id, _ = authorize(("SealingEngineer",))
    payload = body()
    req_str(payload, "revision_note")

    design = find_design(row_id)
    acting_engineer(user_id)

    if design["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DESIGN_STATE_INVALID")
    if user_id == design["author_engineer_id"]:
        raise ApiError("ERR_SEAL_SEGREGATION_VIOLATION")

    design["status"] = "REVISION_REQUIRED"
    touch(design)
    return ok(serializers.bin_design(design))


@bp.post("/bin-designs/<row_id>/revise")
def revise_design(row_id):
    user_id, _ = authorize(("DesignEngineer",))
    payload = body()
    diameter_m = req_num(payload, "diameter_m", required=False, minimum="4.0", maximum="30.0")
    eave_height_m = req_num(payload, "eave_height_m", required=False, minimum="3.2", maximum="24.0")
    roof_pitch_deg = req_int_enum(payload, "roof_pitch_deg", ROOF_PITCHES, required=False)
    design_wind_speed_mph = req_int(
        payload, "design_wind_speed_mph", required=False, minimum=80, maximum=200
    )
    moisture_pct = req_num(payload, "moisture_pct", required=False, minimum="8.0", maximum="24.0")
    design_method = req_enum(payload, "design_method", DESIGN_METHODS, required=False)

    design = find_design(row_id)
    engineer = acting_engineer(user_id)

    if design["status"] != "REVISION_REQUIRED":
        raise ApiError("ERR_DESIGN_STATE_INVALID")

    jurisdiction = store.jurisdictions[design["jurisdiction_id"]]
    grain_profile = store.grain_profiles[design["grain_profile_id"]]
    coating = store.coating_specs[design["coating_spec_id"]]

    merged_moisture = design["moisture_pct"] if moisture_pct is None else moisture_pct
    merged_wind = (
        design["design_wind_speed_mph"]
        if design_wind_speed_mph is None
        else design_wind_speed_mph
    )
    check_safety_gates(merged_moisture, merged_wind, coating, jurisdiction)
    check_licensure(engineer, jurisdiction)

    if diameter_m is not None:
        design["diameter_m"] = diameter_m
    if eave_height_m is not None:
        design["eave_height_m"] = eave_height_m
    if roof_pitch_deg is not None:
        design["roof_pitch_deg"] = roof_pitch_deg
    design["design_wind_speed_mph"] = merged_wind
    design["moisture_pct"] = merged_moisture
    if design_method is not None:
        design["design_method"] = design_method

    run_pipeline(design, jurisdiction, grain_profile, coating)
    design["revision_round"] = design["revision_round"] + 1
    design["author_engineer_id"] = user_id
    design["status"] = "DRAFT"
    touch(design)

    for analysis in store.analyses_of_design(design["id"]):
        analysis["superseded"] = True
        touch(analysis)

    return ok(serializers.bin_design(design))


@bp.post("/bin-designs/<row_id>/seal")
def seal_design(row_id):
    user_id, _ = authorize(("SealingEngineer",))
    design = find_design(row_id)
    engineer = acting_engineer(user_id)

    if design["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DESIGN_STATE_INVALID")
    if user_id == design["author_engineer_id"]:
        raise ApiError("ERR_SEAL_SEGREGATION_VIOLATION")

    jurisdiction = store.jurisdictions[design["jurisdiction_id"]]
    check_licensure(engineer, jurisdiction)

    sealed_at = store.clock_now()
    design["sealed_by_engineer_id"] = user_id
    design["sealed_at"] = sealed_at
    design["permit_ready_at"] = add_days(sealed_at, jurisdiction["permit_review_days"])
    design["status"] = "SEALED"
    touch(design)
    return ok(serializers.bin_design(design))
