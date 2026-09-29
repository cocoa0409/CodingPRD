"""PRD 3.8 (dynamometer half) and 3.9 — performance tests, nameplate
certification, revocation and the regulatory-standard selector."""

from decimal import Decimal

from flask import Blueprint

from auth import authorize
from calc import rhu, test_measured_efficiency
from envelope import created, paginate, single
from errors import fail
from helpers import bool_filter, eq_filter, load, rows
from ledgers import recompute_cell
from routes_reference import JURISDICTIONS
from store import base_row, by_created_at, db, now, touch
from validate import (as_date, interval, parse_body, req_enum, req_instant,
                      req_int, req_num, req_str)

bp = Blueprint("tests", __name__)

TEST_METHODS = ("IEC_60034_2_1_SUMMATION", "IEEE_112_B_DYNAMOMETER")
TEST_READERS = ("TestEngineer", "QualityCertifier", "ComplianceOfficer",
                "ProductionPlanner", "PlantAdmin")
NAMEPLATE_READERS = ("QualityCertifier", "ComplianceOfficer", "ProductionPlanner",
                     "Distributor", "PlantAdmin")


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------

@bp.post("/performance-tests")
def create_test():
    authorize("TestEngineer")
    body = parse_body()
    work_order_id = req_str(body, "work_order_id")
    test_cell_id = req_str(body, "test_cell_id")
    window_start = req_instant(body, "window_start")
    window_end = req_instant(body, "window_end")
    interval(window_start, window_end, "window_start", "window_end")
    dyno_draw_kw = req_num(body, "dyno_draw_kw", 0.1, 500.0, places=1)
    test_method = req_enum(body, "test_method", TEST_METHODS)
    expected_work_order_version = req_int(body, "expected_work_order_version")

    work_order = load("work_orders", work_order_id)
    cell = load("test_cells", test_cell_id)

    if cell["status"] != "AVAILABLE":
        fail("ERR_RESOURCE_IN_MAINTENANCE", "The dynamometer test cell is in MAINTENANCE.")
    if work_order["build_status"] != "ASSEMBLED":
        fail("ERR_INVALID_WORK_ORDER_STATE",
             "A dynamometer test may only be scheduled on an ASSEMBLED work order.")
    if expected_work_order_version != work_order["version"]:
        fail("ERR_STALE_WORK_ORDER_VERSION",
             "expected_work_order_version %s does not match the work order's current "
             "version %s." % (expected_work_order_version, work_order["version"]))

    # PRD 3.8 — aggregate draw over the overlapping SCHEDULED and COMPLETED
    # tests on this cell; SUPERSEDED tests release their draw entirely.
    aggregate = dyno_draw_kw
    for other in db.performance_tests.values():
        if other.get("test_cell_id") != test_cell_id:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if other["window_start"] < window_end and window_start < other["window_end"]:
            aggregate += other["dyno_draw_kw"]
    if rhu(aggregate, 1) > cell["max_concurrent_kw"]:
        fail("ERR_TEST_CELL_CAPACITY_EXCEEDED",
             "The aggregate reserved draw would exceed the cell's ceiling.")

    affected_cells = set()
    for other in by_created_at(list(db.performance_tests.values())):
        if other["work_order_id"] == work_order_id and other["status"] == "SCHEDULED":
            other["status"] = "SUPERSEDED"
            touch(other)
            if other.get("test_cell_id"):
                affected_cells.add(other["test_cell_id"])

    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "test_cell_id": test_cell_id,
        "window_start": window_start,
        "window_end": window_end,
        "dyno_draw_kw": dyno_draw_kw,
        "test_method": test_method,
        "status": "SCHEDULED",
        "requires_requalification": False,
        "test_engineer_user_id": None,
        "recorded_at": None,
        "input_power_kw": None,
        "output_power_kw": None,
        "stator_loss_w": None,
        "rotor_loss_w": None,
        "core_loss_w": None,
        "friction_windage_w": None,
        "ambient_temp_c": None,
        "stator_loss_corrected_w": None,
        "stray_load_loss_w": None,
        "total_loss_w": None,
        "measured_efficiency_pct": None,
        "achieved_class": None,
    })
    db.performance_tests[row["id"]] = row

    affected_cells.add(test_cell_id)
    for candidate in by_created_at(list(db.test_cells.values())):
        if candidate["id"] in affected_cells:
            recompute_cell(candidate)

    touch(work_order)
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/performance-tests/<row_id>")
def read_test(row_id):
    authorize(*TEST_READERS)
    return single(load("performance_tests", row_id))


@bp.get("/performance-tests")
def list_tests():
    authorize(*TEST_READERS)
    collection = rows("performance_tests")
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "test_cell_id")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "test_method")
    collection = bool_filter(collection, "requires_requalification")
    return paginate(collection)


@bp.post("/performance-tests/<row_id>/record")
def record_test(row_id):
    user_id, _role = authorize("TestEngineer")
    test = load("performance_tests", row_id)
    body = parse_body()
    input_power_kw = req_num(body, "input_power_kw", places=3)
    output_power_kw = req_num(body, "output_power_kw", places=3)
    stator_loss_w = req_num(body, "stator_loss_w", places=1)
    rotor_loss_w = req_num(body, "rotor_loss_w", places=1)
    core_loss_w = req_num(body, "core_loss_w", places=1)
    friction_windage_w = req_num(body, "friction_windage_w", places=1)
    ambient_temp_c = req_num(body, "ambient_temp_c", places=1)
    if input_power_kw <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'input_power_kw' must be greater than zero.")

    if test["status"] != "SCHEDULED":
        fail("ERR_INVALID_PERFORMANCE_TEST_STATE",
             "Only a SCHEDULED performance test may be recorded.")
    if test["requires_requalification"]:
        fail("ERR_REQUALIFICATION_REQUIRED",
             "A test flagged by a design revision must be superseded by a fresh one.")
    if now() < test["window_start"]:
        fail("ERR_TEST_WINDOW_NOT_STARTED",
             "The logical clock has not reached the test window's start.")

    work_order = db.work_orders[test["work_order_id"]]
    design = db.designs[work_order["design_id"]]

    test["input_power_kw"] = input_power_kw
    test["output_power_kw"] = output_power_kw
    test["stator_loss_w"] = stator_loss_w
    test["rotor_loss_w"] = rotor_loss_w
    test["core_loss_w"] = core_loss_w
    test["friction_windage_w"] = friction_windage_w
    test["ambient_temp_c"] = ambient_temp_c
    test_measured_efficiency(test, design["poles"])
    test["test_engineer_user_id"] = user_id
    test["recorded_at"] = now()
    test["status"] = "COMPLETED"
    touch(test)

    cell = db.test_cells.get(test["test_cell_id"])
    if cell is not None:
        recompute_cell(cell)

    if work_order["build_status"] == "ASSEMBLED":
        work_order["build_status"] = "TESTED"
    touch(work_order)
    return single(test)


# ---------------------------------------------------------------------------
# Nameplates
# ---------------------------------------------------------------------------

def select_standard(jurisdiction, design):
    """PRD 3.9 — the governing standard is the most recently effective row that
    matches jurisdiction, pole count and output band; ties are broken by the
    earliest created_at, and the row's id is never consulted."""
    today = now().date()
    candidates = []
    for standard in db.standards.values():
        if standard["jurisdiction"] != jurisdiction:
            continue
        if standard["poles"] != design["poles"]:
            continue
        if not (standard["rated_output_kw_min"] <= design["rated_output_kw"]
                <= standard["rated_output_kw_max"]):
            continue
        if as_date(standard["effective_from"]) > today:
            continue
        candidates.append(standard)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    candidates.sort(key=lambda r: r["effective_from"], reverse=True)
    return candidates[0]


@bp.post("/nameplates")
def create_nameplate():
    user_id, _role = authorize("QualityCertifier")
    body = parse_body()
    # PRD 2.11 — segregation of duties precedes payload shape, so the cited
    # test's engineer is resolved opportunistically before the shape check.
    raw_test_id = body.get("performance_test_id")
    if isinstance(raw_test_id, str):
        early = db.performance_tests.get(raw_test_id)
        if early is not None and early.get("test_engineer_user_id") == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The certifier must not be the engineer who recorded the test.")

    work_order_id = req_str(body, "work_order_id")
    performance_test_id = req_str(body, "performance_test_id")
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)

    work_order = load("work_orders", work_order_id)
    test = load("performance_tests", performance_test_id)

    if test.get("test_engineer_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The certifier must not be the engineer who recorded the test.")

    if work_order["build_status"] != "TESTED":
        fail("ERR_INVALID_WORK_ORDER_STATE",
             "Only a TESTED work order may be certified.")
    if test["status"] != "COMPLETED":
        fail("ERR_INVALID_PERFORMANCE_TEST_STATE",
             "Only a COMPLETED performance test may be stamped.")

    order = db.orders[work_order["order_id"]]
    if jurisdiction != order["jurisdiction"]:
        fail("ERR_JURISDICTION_MISMATCH",
             "The certificate jurisdiction must match the customer order's jurisdiction.")

    design = db.designs[work_order["design_id"]]
    standard = select_standard(jurisdiction, design)
    if standard is None:
        fail("ERR_NO_APPLICABLE_STANDARD",
             "No effective regulatory standard governs this motor in %s." % jurisdiction)

    minimum = standard["minimum_efficiency_pct"]
    if test["measured_efficiency_pct"] < minimum:
        fail("ERR_EFFICIENCY_BELOW_REGULATORY_MINIMUM",
             "The measured efficiency falls below the governing minimum of %s." % minimum)

    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "performance_test_id": performance_test_id,
        "standard_id": standard["id"],
        "jurisdiction": jurisdiction,
        "minimum_efficiency_pct_applied": minimum,
        "stamped_efficiency_pct": test["measured_efficiency_pct"],
        "stamped_class": test["achieved_class"],
        "certifier_user_id": user_id,
        "issued_at": now(),
        "status": "ISSUED",
        "revoked_at": None,
        "revocation_reason": None,
    })
    db.nameplates[row["id"]] = row

    work_order["certification_status"] = "CERTIFIED"
    touch(work_order)
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/nameplates/<row_id>")
def read_nameplate(row_id):
    authorize(*NAMEPLATE_READERS)
    return single(load("nameplates", row_id))


@bp.get("/nameplates")
def list_nameplates():
    authorize(*NAMEPLATE_READERS)
    collection = rows("nameplates")
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "performance_test_id")
    collection = eq_filter(collection, "standard_id")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "jurisdiction")
    return paginate(collection)


@bp.post("/nameplates/<row_id>/revoke")
def revoke_nameplate(row_id):
    authorize("QualityCertifier")
    nameplate = load("nameplates", row_id)
    body = parse_body()
    reason = req_str(body, "revocation_reason", 1)
    if nameplate["status"] != "ISSUED":
        fail("ERR_INVALID_NAMEPLATE_STATE", "Only an ISSUED nameplate may be revoked.")

    nameplate["status"] = "REVOKED"
    nameplate["revoked_at"] = now()
    nameplate["revocation_reason"] = reason
    touch(nameplate)

    # Hop 1 — the owning work order's certification is suspended.
    work_order = db.work_orders.get(nameplate["work_order_id"])
    if work_order is not None:
        work_order["certification_status"] = "SUSPENDED"
        touch(work_order)

    # Hop 2 — open claims on that motor carry a defect presumption.
    claims = [c for c in by_created_at(list(db.warranty_claims.values()))
              if c["work_order_id"] == nameplate["work_order_id"]
              and c["status"] in ("SUBMITTED", "UNDER_ANALYSIS")]
    for claim in claims:
        claim["defect_presumption_applied"] = True
        touch(claim)

    # Hop 3 — recompute open_presumed_defect_count for the owning distributors.
    from ledgers import recompute_presumed_defects
    owners = set(c["distributor_id"] for c in claims)
    for distributor in by_created_at(list(db.distributors.values())):
        if distributor["id"] in owners:
            recompute_presumed_defects(distributor)

    return single(nameplate)
