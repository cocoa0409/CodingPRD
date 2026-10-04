"""Aftertreatment specs + dosing calibration (PRD §3.3, OCC per §2.7)."""
from flask import Blueprint

import calculations
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_num, get_or_404,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("aftertreatment_specs", __name__)


@bp.post("/emissions/engine-families/<familyId>/aftertreatment-specs")
def create_spec(familyId):
    auth(("CertificationEngineer",))
    b = body()
    scr = f_str(b, "scr_catalyst_part")
    dpf = f_str(b, "dpf_part")
    doser = f_str(b, "doser_part")
    nsc = f_int(b, "nox_sensor_count", min_v=1, max_v=3)
    expected_version = f_int(b, "expected_engine_family_version")  # non-optional (§2.7)
    fam = get_or_404(store.families, familyId, "EngineFamily")
    # state gate (priority 7)
    if fam["certification_status"] not in ("DESIGN", "TESTING"):
        raise ApiError("ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING", 409,
                       "Spec create requires the family in DESIGN or TESTING")
    # OCC (priority 8)
    if expected_version != fam["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_engine_family_version does not match the family's current version")
    # supersede the family's current DRAFT/ACTIVE spec (each a mutation)
    for s in store.specs.values():
        if s["engine_family_id"] == fam["id"] and s["status"] in ("DRAFT", "ACTIVE"):
            s["status"] = "SUPERSEDED"
            touch(s)
    spec_version = max(
        [s["spec_version"] for s in store.specs.values()
         if s["engine_family_id"] == fam["id"]],
        default=0) + 1
    ent = new_entity()
    ent.update({
        "engine_family_id": fam["id"],
        "spec_version": spec_version,
        "scr_catalyst_part": scr,
        "dpf_part": dpf,
        "doser_part": doser,
        "nox_sensor_count": nsc,
        "target_def_dosing_g_per_kwh": None,
        "last_deviation_pct": None,
        "calibration_status": "UNCALIBRATED",
        "status": "DRAFT",
    })
    store.specs[ent["id"]] = ent
    touch(fam)  # the create advances the family's version
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/aftertreatment-specs/<sid>")
def get_spec(sid):
    auth(ANY)
    ent = get_or_404(store.specs, sid, "AftertreatmentSpec")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/aftertreatment-specs/<sid>/calibrate")
def calibrate_spec(sid):
    auth(("CertificationEngineer",))
    b = body()
    observed_nox = f_num(b, "observed_nox_ppm_avg")
    observed_def = f_num(b, "observed_def_consumption_g_per_kwh")
    spec = get_or_404(store.specs, sid, "AftertreatmentSpec")
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "calibrate requires a DRAFT spec")
    fam = store.families.get(spec["engine_family_id"])
    target, deviation, status = calculations.dosing_calibration(
        fam["displacement_liters"], observed_def, observed_nox)
    spec["target_def_dosing_g_per_kwh"] = target
    spec["last_deviation_pct"] = deviation
    spec["calibration_status"] = status
    touch(spec)
    return envelope_ok(ser(spec), 200)


@bp.post("/emissions/aftertreatment-specs/<sid>/activate")
def activate_spec(sid):
    auth(("CertificationEngineer",))
    spec = get_or_404(store.specs, sid, "AftertreatmentSpec")
    # state gates (priority 7): spec DRAFT, then family in DESIGN/TESTING
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "activate requires a DRAFT spec")
    fam = store.families.get(spec["engine_family_id"])
    if fam is None or fam["certification_status"] not in ("DESIGN", "TESTING"):
        raise ApiError("ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING", 409,
                       "Spec activate requires the family in DESIGN or TESTING")
    # referential (priority 10)
    if spec["calibration_status"] != "CALIBRATED":
        raise ApiError("ERR_SPEC_NOT_CALIBRATED", 409,
                       "Spec must be CALIBRATED before activation")
    spec["status"] = "ACTIVE"
    touch(spec)
    return envelope_ok(ser(spec), 200)
