"""Raw mix designs, blended piles and trial burns (PRD 3.1, 3.2, 3.3)."""

from datetime import timedelta

from flask import Blueprint

from core import (
    API_PREFIX, INTERNAL_ROLES,
    D, ZERO, rnd, r2, guard, body, fail, actor, now,
    want_str, want_num, want_int, want_bool, want_enum, want_array,
    is_number, fk_ref, path_row, put_row, new_row, touch, get_row, rows,
    respond_object, filtered_list, field_eq, _bad,
)
import calc
import serial

bp = Blueprint("design", __name__, url_prefix=API_PREFIX)

READ = INTERNAL_ROLES
DESIGN_STATES = ["DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SUPERSEDED"]


# ===========================================================================
# Raw mix designs
# ===========================================================================
def _component_fks(payload):
    """Rung 35 for the raw_material_id inside each components entry."""
    raw = payload.get("components")
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        material_id = entry.get("raw_material_id")
        if isinstance(material_id, str) and get_row("raw_materials", material_id) is None:
            fail("ERR_RAW_MATERIAL_NOT_FOUND")


def _components_shape(payload, required=True):
    raw = want_array(payload, "components", required=required)
    if raw is None:
        return None
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            _bad("components", "must contain objects")
        material_id = entry.get("raw_material_id")
        fraction = entry.get("mass_fraction_pct")
        if not isinstance(material_id, str) or material_id == "":
            _bad("components", "entries must carry a raw_material_id string")
        if not is_number(fraction) or D(fraction) < ZERO:
            _bad("components", "entries must carry a non-negative mass_fraction_pct")
        parsed.append({"raw_material_id": material_id, "mass_fraction_pct": fraction})
    return parsed


def _component_sum_gate(components):
    """Rung 91: at least two components summing to exactly 100.00."""
    if len(components) < 2:
        fail("ERR_COMPONENTS_SUM_INVALID")
    total = ZERO
    for comp in components:
        total += D(comp["mass_fraction_pct"])
    if rnd(total, 2) != D("100.00"):
        fail("ERR_COMPONENTS_SUM_INVALID")


def _recompute_design(design):
    design.update(calc.as_designed_chemistry(design["components"]))


@bp.post("/raw-mix-designs")
@guard(["ProcessEngineer"])
def create_design():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    _component_fks(payload)
    want_str(payload, "plant_id")
    code = want_str(payload, "code")
    target_lsf = want_num(payload, "target_lsf")
    target_sm = want_num(payload, "target_sm")
    target_am = want_num(payload, "target_am")
    components = _components_shape(payload)
    tol_lsf = want_num(payload, "module_tolerance_lsf", required=False)
    tol_pile = want_num(payload, "pile_lsf_tolerance", required=False)
    _component_sum_gate(components)
    row = new_row("designs")
    row.update({
        "plant_id": plant["id"],
        "code": code,
        "target_lsf": target_lsf,
        "target_sm": target_sm,
        "target_am": target_am,
        "module_tolerance_lsf": 1.50 if tol_lsf is None else tol_lsf,
        "pile_lsf_tolerance": 2.00 if tol_pile is None else tol_pile,
        "components": components,
        "status": "DRAFT",
        "revision_count": 0,
        "revision_reason": None,
        "created_by_user_id": actor(),
        "approved_by_user_id": None,
        "approved_at": None,
        "superseded_by_design_id": None,
    })
    _recompute_design(row)
    put_row("designs", row)
    return respond_object(serial.design_out(row), 201)


@bp.patch("/raw-mix-designs/<design_id>")
@guard(["ProcessEngineer"])
def amend_design(design_id):
    design = path_row("designs", design_id)
    payload = body()
    _component_fks(payload)
    components = _components_shape(payload, required=False)
    target_lsf = want_num(payload, "target_lsf", required=False)
    target_sm = want_num(payload, "target_sm", required=False)
    target_am = want_num(payload, "target_am", required=False)
    tol_lsf = want_num(payload, "module_tolerance_lsf", required=False)
    tol_pile = want_num(payload, "pile_lsf_tolerance", required=False)
    if design["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_DESIGN_STATE")
    _component_sum_gate(components if components is not None else design["components"])
    if components is not None:
        design["components"] = components
    if target_lsf is not None:
        design["target_lsf"] = target_lsf
    if target_sm is not None:
        design["target_sm"] = target_sm
    if target_am is not None:
        design["target_am"] = target_am
    if tol_lsf is not None:
        design["module_tolerance_lsf"] = tol_lsf
    if tol_pile is not None:
        design["pile_lsf_tolerance"] = tol_pile
    _recompute_design(design)
    if design["status"] == "REVISION_REQUESTED":
        design["status"] = "DRAFT"
    touch(design)
    return respond_object(serial.design_out(design))


@bp.post("/raw-mix-designs/<design_id>/submit")
@guard(["ProcessEngineer"])
def submit_design(design_id):
    design = path_row("designs", design_id)
    if design["status"] != "DRAFT":
        fail("ERR_INVALID_DESIGN_STATE")
    for comp in design["components"]:
        if get_row("raw_materials", comp["raw_material_id"]) is None:
            fail("ERR_RAW_MATERIAL_NOT_FOUND")
    _recompute_design(design)
    _component_sum_gate(design["components"])
    achieved = design["as_designed_lsf"]
    if achieved is None:
        fail("ERR_MODULE_TARGET_DEVIATION")
    deviation = rnd(abs(D(achieved) - D(design["target_lsf"])), 2)
    if deviation > D(design["module_tolerance_lsf"]):
        fail("ERR_MODULE_TARGET_DEVIATION")
    design["status"] = "SUBMITTED"
    touch(design)
    return respond_object(serial.design_out(design))


@bp.post("/raw-mix-designs/<design_id>/request-revision")
@guard(["QualityManager"])
def request_revision(design_id):
    design = path_row("designs", design_id)
    payload = body()
    reason = want_str(payload, "revision_reason")
    if design["status"] != "SUBMITTED":
        fail("ERR_INVALID_DESIGN_STATE")
    if design["revision_count"] >= calc.MAX_DESIGN_REVISIONS:
        fail("ERR_REVISION_LIMIT_EXCEEDED")
    design["status"] = "REVISION_REQUESTED"
    design["revision_reason"] = reason
    design["revision_count"] = design["revision_count"] + 1
    touch(design)
    return respond_object(serial.design_out(design))


@bp.post("/raw-mix-designs/<design_id>/approve")
@guard(["QualityManager"])
def approve_design(design_id):
    design = path_row("designs", design_id)
    if actor() == design["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if design["status"] != "SUBMITTED":
        fail("ERR_INVALID_DESIGN_STATE")
    design["status"] = "APPROVED"
    design["approved_by_user_id"] = actor()
    design["approved_at"] = now()
    touch(design)
    for other in rows("designs"):
        if (other["id"] != design["id"]
                and other["plant_id"] == design["plant_id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            other["superseded_by_design_id"] = design["id"]
            touch(other)
    return respond_object(serial.design_out(design))


@bp.get("/raw-mix-designs/<design_id>")
@guard(READ)
def get_design(design_id):
    return respond_object(serial.design_out(path_row("designs", design_id)))


@bp.get("/raw-mix-designs")
@guard(READ)
def list_designs():
    return filtered_list("designs", serial.design_out, {
        "plant_id": field_eq("plant_id"),
        "status": field_eq("status"),
        "superseded_by_design_id": field_eq("superseded_by_design_id"),
    })


# ===========================================================================
# Blended piles
# ===========================================================================
@bp.post("/blended-piles")
@guard(["ProcessEngineer"])
def create_pile():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    design = fk_ref(payload, "raw_mix_design_id", "designs")
    want_str(payload, "plant_id")
    want_str(payload, "raw_mix_design_id")
    pile_code = want_str(payload, "pile_code")
    expected = want_int(payload, "expected_raw_mix_design_version")
    if expected != design["version"]:
        fail("ERR_STALE_DESIGN_VERSION")
    if design["status"] != "APPROVED":
        fail("ERR_DESIGN_NOT_APPROVED")
    row = new_row("piles")
    row.update({
        "plant_id": plant["id"],
        "raw_mix_design_id": design["id"],
        "pile_code": pile_code,
        "additions": [],
        "as_received_tonnes": 0.0,
        "dry_tonnes": 0.0,
        "alt_raw_share_pct": 0.0,
        "as_blended_cao_pct": None,
        "as_blended_sio2_pct": None,
        "as_blended_al2o3_pct": None,
        "as_blended_fe2o3_pct": None,
        "as_blended_lsf": None,
        "as_blended_sm": None,
        "as_blended_am": None,
        "lsf_deviation": None,
        "status": "OPEN",
        "sealed_at": None,
        "consumed_dry_tonnes": 0.0,
    })
    put_row("piles", row)
    touch(design)
    return respond_object(serial.pile_out(row), 201)


@bp.post("/blended-piles/<pile_id>/additions")
@guard(["ProcessEngineer"])
def append_addition(pile_id):
    pile = path_row("piles", pile_id)
    payload = body()
    material = fk_ref(payload, "raw_material_id", "raw_materials")
    want_str(payload, "raw_material_id")
    tonnes = want_num(payload, "tonnes_as_received")
    moisture = want_num(payload, "moisture_pct")
    if pile["status"] != "OPEN":
        fail("ERR_INVALID_PILE_STATE")
    design = get_row("designs", pile["raw_mix_design_id"])
    if design is None or design["status"] != "APPROVED":
        fail("ERR_DESIGN_NOT_APPROVED")
    addition = {
        "raw_material_id": material["id"],
        "tonnes_as_received": tonnes,
        "moisture_pct": moisture,
        "added_at": now(),
    }
    trial = pile["additions"] + [addition]
    figures = calc.pile_chemistry(trial)
    # Rung 94: the as-received alternative share must respect the tightest cap
    # among the alternative materials actually present in the pile.
    caps = []
    for entry in trial:
        candidate = get_row("raw_materials", entry["raw_material_id"])
        if candidate is not None and candidate.get("is_alternative"):
            caps.append(D(candidate["max_substitution_pct"]))
    if caps and D(figures["alt_raw_share_pct"]) > min(caps):
        fail("ERR_ALT_RAW_SUBSTITUTION_EXCEEDED")
    pile["additions"] = trial
    calc.recompute_pile(pile)
    touch(pile)
    return respond_object(serial.pile_out(pile))


@bp.post("/blended-piles/<pile_id>/seal")
@guard(["ProcessEngineer"])
def seal_pile(pile_id):
    pile = path_row("piles", pile_id)
    if pile["status"] != "OPEN":
        fail("ERR_INVALID_PILE_STATE")
    design = get_row("designs", pile["raw_mix_design_id"])
    if design is None or design["status"] != "APPROVED":
        fail("ERR_DESIGN_NOT_APPROVED")
    if not pile["additions"]:
        fail("ERR_PILE_EMPTY")
    deviation = pile["lsf_deviation"]
    if deviation is None or D(deviation) > D(design["pile_lsf_tolerance"]):
        fail("ERR_PILE_LSF_OFF_TARGET")
    pile["status"] = "SEALED"
    pile["sealed_at"] = now()
    touch(pile)
    return respond_object(serial.pile_out(pile))


@bp.get("/blended-piles/<pile_id>")
@guard(READ)
def get_pile(pile_id):
    return respond_object(serial.pile_out(path_row("piles", pile_id)))


@bp.get("/blended-piles")
@guard(READ)
def list_piles():
    return filtered_list("piles", serial.pile_out, {
        "plant_id": field_eq("plant_id"),
        "raw_mix_design_id": field_eq("raw_mix_design_id"),
        "status": field_eq("status"),
    })


# ===========================================================================
# Trial burns
# ===========================================================================
@bp.post("/burn-tests")
@guard(["EnvironmentalOfficer", "LabTechnician"])
def create_burn_test():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    fuel = fk_ref(payload, "fuel_id", "fuels")
    want_str(payload, "plant_id")
    want_str(payload, "fuel_id")
    requested = want_num(payload, "requested_max_tsr_pct")
    valid_days = want_int(payload, "valid_days")
    row = new_row("burn_tests")
    row.update({
        "plant_id": plant["id"],
        "fuel_id": fuel["id"],
        "requested_max_tsr_pct": requested,
        "valid_days": valid_days,
        "status": "REQUESTED",
        "measured_chlorine_pct": None,
        "measured_nox_kg_per_gj": None,
        "stack_compliant": None,
        "result_recorded_by_user_id": None,
        "adjudicated_by_user_id": None,
        "authorized_max_tsr_pct": 0,
        "valid_from": None,
        "valid_until": None,
        "decision_reason": None,
    })
    put_row("burn_tests", row)
    return respond_object(serial.burn_test_out(row), 201)


@bp.post("/burn-tests/<burn_test_id>/start")
@guard(["LabTechnician"])
def start_burn_test(burn_test_id):
    test = path_row("burn_tests", burn_test_id)
    if test["status"] != "REQUESTED":
        fail("ERR_INVALID_BURN_TEST_STATE")
    test["status"] = "IN_PROGRESS"
    touch(test)
    return respond_object(serial.burn_test_out(test))


@bp.post("/burn-tests/<burn_test_id>/record-result")
@guard(["LabTechnician"])
def record_burn_result(burn_test_id):
    test = path_row("burn_tests", burn_test_id)
    payload = body()
    chlorine = want_num(payload, "measured_chlorine_pct")
    nox = want_num(payload, "measured_nox_kg_per_gj")
    compliant = want_bool(payload, "stack_compliant")
    if test["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_BURN_TEST_STATE")
    test["measured_chlorine_pct"] = chlorine
    test["measured_nox_kg_per_gj"] = nox
    test["stack_compliant"] = compliant
    test["result_recorded_by_user_id"] = actor()
    test["status"] = "RESULT_RECORDED"
    touch(test)
    return respond_object(serial.burn_test_out(test))


@bp.post("/burn-tests/<burn_test_id>/adjudicate")
@guard(["EnvironmentalOfficer"])
def adjudicate_burn_test(burn_test_id):
    test = path_row("burn_tests", burn_test_id)
    payload = body()
    decision = want_enum(payload, "decision", calc.BURN_DECISIONS)
    granted = want_num(payload, "authorized_max_tsr_pct", required=False)
    reason = want_str(payload, "decision_reason", required=False)
    if actor() == test["result_recorded_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if test["status"] != "RESULT_RECORDED":
        fail("ERR_INVALID_BURN_TEST_STATE")
    test["adjudicated_by_user_id"] = actor()
    test["decision_reason"] = reason
    if decision == "REJECTED":
        test["status"] = "REJECTED"
        touch(test)
        return respond_object(serial.burn_test_out(test))
    plant = get_row("plants", test["plant_id"])
    ceiling = 0 if granted is None else granted
    if not test["stack_compliant"]:
        _bad("decision", "cannot authorize a trial burn whose stack test was not compliant")
    if D(ceiling) > D(test["requested_max_tsr_pct"]):
        _bad("authorized_max_tsr_pct", "may not exceed requested_max_tsr_pct")
    if plant is not None and D(ceiling) > D(plant["permit_max_tsr_pct"]):
        _bad("authorized_max_tsr_pct", "may not exceed the plant's permit_max_tsr_pct")
    test["status"] = "AUTHORIZED"
    test["authorized_max_tsr_pct"] = ceiling
    test["valid_from"] = now()
    test["valid_until"] = now() + timedelta(days=test["valid_days"])
    touch(test)
    return respond_object(serial.burn_test_out(test))


@bp.get("/burn-tests/<burn_test_id>")
@guard(READ)
def get_burn_test(burn_test_id):
    return respond_object(serial.burn_test_out(path_row("burn_tests", burn_test_id)))


@bp.get("/burn-tests")
@guard(READ)
def list_burn_tests():
    return filtered_list("burn_tests", serial.burn_test_out, {
        "plant_id": field_eq("plant_id"),
        "fuel_id": field_eq("fuel_id"),
        "status": field_eq("status"),
    })
