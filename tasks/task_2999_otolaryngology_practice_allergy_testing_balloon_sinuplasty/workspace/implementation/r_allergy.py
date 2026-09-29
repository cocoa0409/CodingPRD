"""Allergy panels (PRD 3.2, 3.3) and reaction events (PRD 3.4)."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("allergy", __name__)

ORDER_FIELDS = [
    "patient_id", "panel_code", "method", "status", "antigen_count",
    "billed_units", "practice_charge_cents", "patient_responsibility_cents",
    "observation_required_minutes", "ordered_by_user_id",
    "administered_by_user_id", "administered_at", "positive_antigen_count",
    "worst_systemic_grade", "abort_reason",
]


# --- orders ------------------------------------------------------------------
@bp.post("/allergy-test-orders")
def create_order():
    ctx = common.begin(["Otolaryngologist", "AllergyNurse"])
    values, _provided = shape.read_body([
        ("patient_id", True, shape.v_ref(), False),
        ("panel_code", True, shape.v_enum(calc.PANEL_CODES), False),
        ("method", True, shape.v_enum(calc.METHODS), False),
    ])
    patient = common.find_ref("patients", values["patient_id"])
    policy = common.policy_of_patient(patient)
    row = common.new_row("allergy_test_orders", {
        "patient_id": patient["id"],
        "panel_code": values["panel_code"],
        "method": values["method"],
        "status": "ORDERED",
        "antigen_count": calc.PANEL_ANTIGEN_COUNT[values["panel_code"]],
        "billed_units": 0,
        "practice_charge_cents": 0,
        "patient_responsibility_cents": 0,
        "observation_required_minutes": calc.observation_minutes(
            patient, policy, values["method"]
        ),
        "ordered_by_user_id": ctx.user_id,
        "administered_by_user_id": None,
        "administered_at": None,
        "positive_antigen_count": 0,
        "worst_systemic_grade": 0,
        "abort_reason": None,
    })
    return envelope.created(common.public("allergy_test_orders", row))


@bp.get("/allergy-test-orders/<order_id>")
def read_order(order_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("allergy_test_orders", order_id)
    return envelope.ok(common.public("allergy_test_orders", row))


@bp.get("/allergy-test-orders")
def list_orders():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "patient_id": shape.q_string(),
        "status": shape.q_enum(calc.ORDER_STATUSES),
        "method": shape.q_enum(calc.METHODS),
        "panel_code": shape.q_enum(calc.PANEL_CODES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("allergy_test_orders",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("allergy_test_orders", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/allergy-test-orders/<order_id>/administer")
def administer_order(order_id):
    ctx = common.begin(["AllergyNurse"])
    shape.no_body()
    order = common.find("allergy_test_orders", order_id)
    # rung 7
    if order["status"] != "ORDERED" or order["method"] not in calc.SKIN_METHODS:
        raise ApiError("ERR_ORDER_STATE_INVALID")
    patient = store.db["patients"][order["patient_id"]]
    # rung 10 — PRD 3.2 enumerates dermatographism before the epinephrine gate
    if patient["dermatographism"]:
        raise ApiError("ERR_DERMATOGRAPHISM_BLOCKS_SKIN_TEST")
    if (patient["risk_score"] >= calc.RISK_OBSERVATION_THRESHOLD
            and not patient["epinephrine_on_file"]):
        raise ApiError("ERR_EPINEPHRINE_NOT_ON_FILE")
    # rung 11
    last_dose = patient["antihistamine_last_dose_at"]
    if last_dose is not None:
        deadline = store.plus_hours(store.parse_instant(last_dose),
                                    calc.WASHOUT_HOURS)
        if store.now() < deadline:
            raise ApiError("ERR_WASHOUT_NOT_COMPLETE")

    policy = common.policy_of_patient(patient)
    order["status"] = "ADMINISTERED"
    order["administered_at"] = store.iso(store.now())
    order["administered_by_user_id"] = ctx.user_id
    order["observation_required_minutes"] = calc.observation_minutes(
        patient, policy, order["method"]
    )
    common.touch(order)
    return envelope.ok(common.public("allergy_test_orders", order))


@bp.post("/allergy-test-orders/<order_id>/convert-to-serum")
def convert_to_serum(order_id):
    common.begin(["AllergyNurse"])
    shape.no_body()
    order = common.find("allergy_test_orders", order_id)
    if order["status"] != "ORDERED" or order["method"] == "SERUM_IGE":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    patient = store.db["patients"][order["patient_id"]]
    policy = common.policy_of_patient(patient)
    if not policy["allergy_serum_covered"]:
        raise ApiError("ERR_SERUM_NOT_COVERED")
    order["status"] = "SERUM_PENDING"
    order["method"] = "SERUM_IGE"
    order["billed_units"] = calc.billed_units_for("SERUM_IGE", order["antigen_count"])
    order["observation_required_minutes"] = 0
    common.touch(order)
    return envelope.ok(common.public("allergy_test_orders", order))


@bp.post("/allergy-test-orders/<order_id>/readings")
def record_readings(order_id):
    common.begin(["AllergyNurse", "Otolaryngologist"])
    values, _provided = shape.read_body([
        ("positive_antigen_count", True, shape.v_int(0, None), False),
        ("max_wheal_mm", False, shape.v_number(0, 80, 1), False),
    ])
    order = common.find("allergy_test_orders", order_id)
    positive = values["positive_antigen_count"]
    # PRD 3.3: a figure larger than the order's antigen_count fails the shape gate
    if positive > order["antigen_count"]:
        shape.bad("positive_antigen_count may not exceed the order's antigen_count")
    if order["status"] not in ("ADMINISTERED", "SERUM_PENDING"):
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if order["status"] == "ADMINISTERED":
        elapsed = store.whole_minutes_between(
            store.parse_instant(order["administered_at"]), store.now()
        )
        if elapsed < order["observation_required_minutes"]:
            raise ApiError("ERR_OBSERVATION_NOT_COMPLETE")

    patient = store.db["patients"][order["patient_id"]]
    policy = common.policy_of_patient(patient)
    order["positive_antigen_count"] = positive

    if order["status"] == "ADMINISTERED" and positive == order["antigen_count"]:
        # the dermatographism abort branch
        order["status"] = "ABORTED"
        order["abort_reason"] = "DERMATOGRAPHISM_DETECTED"
        order["practice_charge_cents"] = 0
        order["patient_responsibility_cents"] = 0
        common.touch(order)
        patient["dermatographism"] = True
        common.touch(patient)
        return envelope.ok(common.public("allergy_test_orders", order))

    billing = calc.panel_billing(order["panel_code"], order["method"],
                                 policy["covered_pct_bps"])
    order["status"] = "READ"
    order["billed_units"] = billing["billed_units"]
    order["practice_charge_cents"] = billing["practice_charge_cents"]
    order["patient_responsibility_cents"] = billing["patient_responsibility_cents"]
    common.touch(order)

    total_positive = 0
    for row in store.rows("allergy_test_orders"):
        if row["patient_id"] == patient["id"] and row["status"] == "READ":
            total_positive += row["positive_antigen_count"]
    patient["sensitized_antigen_count"] = min(20, total_positive)
    calc.rescore_patient(patient)
    common.touch(patient)
    return envelope.ok(common.public("allergy_test_orders", order))


# --- reaction events --------------------------------------------------------
def _rollup_order(order):
    grades = [e["systemic_grade"] for e in store.rows("reaction_events")
              if e["allergy_test_order_id"] == order["id"]]
    order["worst_systemic_grade"] = max(grades) if grades else 0


def _rollup_dose(dose):
    grades = [e["systemic_grade"] for e in store.rows("reaction_events")
              if e["immunotherapy_dose_id"] == dose["id"]]
    dose["reaction_grade"] = max(grades) if grades else 0


def _cascade_rescore(patient):
    patient["risk_score_variant"] = "POST_REACTION"
    patient["risk_score"] = calc.risk_score(patient)
    return patient["risk_score"]


@bp.post("/reaction-events")
def create_reaction_event():
    ctx = common.begin(["AllergyNurse"])
    values, provided = shape.read_body([
        ("allergy_test_order_id", False, shape.v_ref(), True),
        ("immunotherapy_dose_id", False, shape.v_ref(), True),
        ("systemic_grade", True, shape.v_int(0, 4), False),
        ("local_wheal_mm", False, shape.v_number(0, 80, 1), False),
        ("onset_minutes", True, shape.v_int(0, 240), False),
        ("epinephrine_given", False, shape.v_bool(), False),
    ])
    order_id = values.get("allergy_test_order_id")
    dose_id = values.get("immunotherapy_dose_id")
    if (order_id is None) == (dose_id is None):
        shape.bad("exactly one of allergy_test_order_id and "
                  "immunotherapy_dose_id must be supplied")

    order = None
    dose = None
    if order_id is not None:
        order = common.find_ref("allergy_test_orders", order_id)
    else:
        dose = common.find_ref("immunotherapy_doses", dose_id)

    grade = values["systemic_grade"]
    event = common.new_row("reaction_events", {
        "allergy_test_order_id": order_id,
        "immunotherapy_dose_id": dose_id,
        "systemic_grade": grade,
        "local_wheal_mm": values.get("local_wheal_mm", 0),
        "onset_minutes": values["onset_minutes"],
        "epinephrine_given": values.get("epinephrine_given", False),
        "recorded_by_user_id": ctx.user_id,
        "occurred_at": store.iso(store.now()),
    })

    if order is not None:
        _rollup_order(order)
        patient = store.db["patients"][order["patient_id"]]
        if grade >= 2 and order["status"] == "ADMINISTERED":
            order["status"] = "ABORTED"
            order["abort_reason"] = "SYSTEMIC_REACTION"
            order["practice_charge_cents"] = 0
            order["patient_responsibility_cents"] = 0
            common.touch(order)
            score = _cascade_rescore(patient)
            common.touch(patient)
            if score >= calc.RISK_SUPERVISION_THRESHOLD:
                patient["supervision_tier"] = "PHYSICIAN_PRESENT"
        else:
            common.touch(order)
    else:
        _rollup_dose(dose)
        patient = common.patient_of_dose(dose)
        if grade >= 2 and dose["status"] == "ADMINISTERED":
            dose["status"] = "REACTION_HELD"
            common.touch(dose)
            patient["immunotherapy_escalation_step"] = max(
                1, dose["escalation_step_at_dose"] - 2
            )
            patient["immunotherapy_status"] = "HELD"
            score = _cascade_rescore(patient)
            common.touch(patient)
            if score >= calc.RISK_SUPERVISION_THRESHOLD:
                patient["supervision_tier"] = "PHYSICIAN_PRESENT"
                common.resize_ordered_orders(patient)
                common.flag_supervision_targets(patient)
        else:
            common.touch(dose)

    return envelope.created(common.public("reaction_events", event))


@bp.get("/reaction-events/<event_id>")
def read_reaction_event(event_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("reaction_events", event_id)
    return envelope.ok(common.public("reaction_events", row))


@bp.get("/reaction-events")
def list_reaction_events():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "allergy_test_order_id": shape.q_string(),
        "immunotherapy_dose_id": shape.q_string(),
        "systemic_grade": shape.q_int(0, 4),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("reaction_events",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("reaction_events", r) for r in page],
        limit, offset, len(items),
    )
