"""PRD 3.2 and 3.3 — motor designs, the predicted loss model, review and the
revision cycle."""

from flask import Blueprint

from auth import authorize
from calc import class_ordinal, design_predicted_efficiency
from envelope import created, paginate, single
from errors import fail
from helpers import eq_filter, load, rows
from routes_reference import EFFICIENCY_CLASSES, req_poles
from store import base_row, by_created_at, db, now, touch
from validate import opt_str, parse_body, req_enum, req_int, req_num, req_str

bp = Blueprint("designs", __name__)

RATED_VOLTAGES = (230, 400, 460, 690)
LAMINATION_GRADES = ("M400_50A", "M330_35A", "M270_35A", "M235_35A")
WINDING_TYPES = ("CONCENTRIC", "LAP")
INSULATION_CLASSES = ("B", "F", "H")
ROTOR_CONSTRUCTIONS = ("DIE_CAST_ALUMINUM", "FABRICATED_COPPER")
SHAFT_TOLERANCE_CLASSES = ("k6", "m6", "j6")
LUBRICATION_SPECS = ("GREASE_LIFETIME", "GREASE_REGREASABLE", "OIL_MIST")
DUTY_TYPES = ("S1", "S2", "S3")
ENCLOSURES = ("IP55", "IP65", "IP66")
MOUNTINGS = ("B3", "B5", "B35", "V1")
SUPERSEDABLE_STATUSES = ("RELEASED", "REVISION_OPEN", "OBSOLETE")

DESIGN_READERS = ("DesignEngineer", "DesignReviewer", "ProductionPlanner",
                  "QualityCertifier", "ComplianceOfficer", "PlantAdmin")

MAX_REVIEW_ROUNDS = 3


@bp.post("/motor-designs")
def create_design():
    user_id, _role = authorize("DesignEngineer")
    body = parse_body()

    model_code = req_str(body, "model_code", 1, 40)
    frame_size = req_str(body, "frame_size", 1, 16)
    poles = req_poles(body)
    rated_output_kw = req_num(body, "rated_output_kw", 4.0, 15.0, places=1)
    rated_voltage_v = req_int(body, "rated_voltage_v")
    if rated_voltage_v not in RATED_VOLTAGES:
        fail("ERR_INVALID_REQUEST",
             "Field 'rated_voltage_v' must be one of 230, 400, 460, 690.")
    target_efficiency_class = req_enum(body, "target_efficiency_class", EFFICIENCY_CLASSES)
    lamination_grade = req_enum(body, "lamination_grade", LAMINATION_GRADES)
    lamination_stack_length_mm = req_int(body, "lamination_stack_length_mm", 120, 260)
    winding_copper_kg = req_num(body, "winding_copper_kg", 6.0, 30.0, places=1)
    winding_type = req_enum(body, "winding_type", WINDING_TYPES)
    insulation_class = req_enum(body, "insulation_class", INSULATION_CLASSES)
    stator_bore_id_mm = req_num(body, "stator_bore_id_mm", 80.000, 260.000, places=3)
    design_air_gap_mm = req_num(body, "design_air_gap_mm", 0.200, 1.500, places=3)
    air_gap_tolerance_mm = req_num(body, "air_gap_tolerance_mm", 0.010, 0.200, places=3)
    rotor_construction = req_enum(body, "rotor_construction", ROTOR_CONSTRUCTIONS)
    rotor_bar_count = req_int(body, "rotor_bar_count", 24, 48)
    shaft_diameter_mm = req_num(body, "shaft_diameter_mm", 20.000, 90.000, places=3)
    shaft_tolerance_class = req_enum(body, "shaft_tolerance_class", SHAFT_TOLERANCE_CLASSES)
    bearing_spec_de = req_str(body, "bearing_spec_de", 1, 24)
    bearing_spec_nde = req_str(body, "bearing_spec_nde", 1, 24)
    lubrication_spec = req_enum(body, "lubrication_spec", LUBRICATION_SPECS)
    duty_type = req_enum(body, "duty_type", DUTY_TYPES)
    enclosure = req_enum(body, "enclosure", ENCLOSURES)
    mounting = req_enum(body, "mounting", MOUNTINGS)
    supersedes = opt_str(body, "supersedes_design_id")

    superseded = None
    if supersedes is not None:
        superseded = load("designs", supersedes)

    # PRD 3.2 — case-sensitive, and retired designs still hold their code.
    for existing in db.designs.values():
        if existing["model_code"] == model_code:
            fail("ERR_DUPLICATE_MODEL_CODE",
                 "Model code '%s' is already used by another design." % model_code)

    if superseded is not None and superseded["status"] not in SUPERSEDABLE_STATUSES:
        fail("ERR_INVALID_DESIGN_STATE",
             "A design that is still DRAFT or IN_REVIEW cannot be superseded.")

    row = base_row()
    row.update({
        "model_code": model_code,
        "frame_size": frame_size,
        "poles": poles,
        "rated_output_kw": rated_output_kw,
        "rated_voltage_v": rated_voltage_v,
        "target_efficiency_class": target_efficiency_class,
        "lamination_grade": lamination_grade,
        "lamination_stack_length_mm": lamination_stack_length_mm,
        "winding_copper_kg": winding_copper_kg,
        "winding_type": winding_type,
        "insulation_class": insulation_class,
        "stator_bore_id_mm": stator_bore_id_mm,
        "design_air_gap_mm": design_air_gap_mm,
        "air_gap_tolerance_mm": air_gap_tolerance_mm,
        "rotor_construction": rotor_construction,
        "rotor_bar_count": rotor_bar_count,
        "shaft_diameter_mm": shaft_diameter_mm,
        "shaft_tolerance_class": shaft_tolerance_class,
        "bearing_spec_de": bearing_spec_de,
        "bearing_spec_nde": bearing_spec_nde,
        "lubrication_spec": lubrication_spec,
        "duty_type": duty_type,
        "enclosure": enclosure,
        "mounting": mounting,
        "supersedes_design_id": supersedes,
        "status": "DRAFT",
        "revision_index": 0,
        "review_round": 0,
        "created_by_user_id": user_id,
        "released_at": None,
        "released_by_user_id": None,
        "review_notes": None,
    })
    design_predicted_efficiency(row)
    db.designs[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/motor-designs/<row_id>")
def read_design(row_id):
    authorize(*DESIGN_READERS)
    return single(load("designs", row_id))


@bp.get("/motor-designs")
def list_designs():
    authorize(*DESIGN_READERS)
    collection = rows("designs")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "target_efficiency_class")
    collection = eq_filter(collection, "predicted_class")
    collection = eq_filter(collection, "supersedes_design_id")
    return paginate(collection)


@bp.post("/motor-designs/<row_id>/submit-review")
def submit_review(row_id):
    user_id, _role = authorize("DesignEngineer")
    design = load("designs", row_id)
    if design["created_by_user_id"] != user_id:
        fail("ERR_NOT_OWNER", "Only the authoring engineer may submit this design.")
    parse_body()
    if design["status"] not in ("DRAFT", "REVISION_OPEN"):
        fail("ERR_INVALID_DESIGN_STATE",
             "Only a DRAFT or REVISION_OPEN design may be submitted for review.")
    # PRD 3.3 — submission re-runs every output of the loss model first.
    design_predicted_efficiency(design)
    design["status"] = "IN_REVIEW"
    touch(design)
    return single(design)


@bp.post("/motor-designs/<row_id>/review-decision")
def review_decision(row_id):
    user_id, _role = authorize("DesignReviewer")
    design = load("designs", row_id)
    # PRD 2.9 — the reviewer must not be the authoring engineer, for all three
    # decisions including the one that merely returns the design for changes.
    if design["created_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer must not be the engineer who authored the design.")
    body = parse_body()
    decision = req_enum(body, "decision", ("APPROVE", "REQUEST_CHANGES", "OBSOLETE"))
    review_notes = opt_str(body, "review_notes", min_len=0)

    if design["status"] != "IN_REVIEW":
        fail("ERR_INVALID_DESIGN_STATE", "Only an IN_REVIEW design may be decided.")

    # PRD 2.11 — the class gate is evaluated before the round ceiling.
    if decision == "APPROVE":
        if class_ordinal(design["predicted_class"]) < class_ordinal(
                design["target_efficiency_class"]):
            fail("ERR_DESIGN_CLASS_SHORTFALL",
                 "The guaranteed class %s ranks below the target class %s."
                 % (design["predicted_class"], design["target_efficiency_class"]))

    if design["review_round"] >= MAX_REVIEW_ROUNDS:
        fail("ERR_ROUND_LIMIT_EXCEEDED",
             "The review round counter must remain strictly below %d." % MAX_REVIEW_ROUNDS)

    design["review_round"] = design["review_round"] + 1
    if review_notes is not None:
        design["review_notes"] = review_notes

    if decision == "APPROVE":
        design["status"] = "RELEASED"
        design["released_at"] = now()
        design["released_by_user_id"] = user_id
    elif decision == "REQUEST_CHANGES":
        design["status"] = "DRAFT"
        design["revision_index"] = design["revision_index"] + 1
    else:
        design["status"] = "OBSOLETE"

    touch(design)
    return single(design)


@bp.post("/motor-designs/<row_id>/open-revision")
def open_revision(row_id):
    user_id, _role = authorize("DesignEngineer")
    design = load("designs", row_id)
    if design["created_by_user_id"] != user_id:
        fail("ERR_NOT_OWNER", "Only the authoring engineer may reopen this design.")
    body = parse_body()
    req_str(body, "revision_reason", 1)
    if design["status"] != "RELEASED":
        fail("ERR_INVALID_DESIGN_STATE", "Only a RELEASED design may be reopened.")

    design["status"] = "REVISION_OPEN"
    design["revision_index"] = design["revision_index"] + 1

    # Hop 1 — work orders pinned to this design that still have hardware in the
    # plant, in created_at ascending order.
    stale_statuses = ("RELEASED", "SUBASSEMBLIES_DONE", "ASSEMBLED", "TESTED")
    affected = [w for w in by_created_at(list(db.work_orders.values()))
                if w["design_id"] == design["id"] and w["build_status"] in stale_statuses]
    for work_order in affected:
        work_order["design_pin_stale"] = True
        touch(work_order)

    # Hop 2 — caused by hop 1: every still-SCHEDULED test on those work orders.
    affected_ids = set(w["id"] for w in affected)
    tests = [t for t in by_created_at(list(db.performance_tests.values()))
             if t["work_order_id"] in affected_ids and t["status"] == "SCHEDULED"]
    for test in tests:
        test["requires_requalification"] = True
        touch(test)

    touch(design)
    return single(design)
