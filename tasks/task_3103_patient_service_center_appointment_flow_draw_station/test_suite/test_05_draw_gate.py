"""Draw gate: fasting boundary, safety/fiscal precedence, and tube-plan reads."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, make_patient_headers, make_phlebotomist_headers,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_checked_in_visit, new_phlebotomist, book, check_in,
    call_patient, get_order, get_appointment, set_clock, seed_reference, new_center,
    new_patient, new_order, resolve_insurance, resolve_necessity, new_tube_requirement,
    setup_windowed_visit,
)
from test_helpers.factories import create_specimen_payload


def test_fasting_deadline_is_strict_so_equality_is_still_compliant(api):
    """PRD §3.8: "A fasting order passes when the serving instant is no later
    than its deadline, and fails otherwise — with the boundary being strict on
    the far side, so that the deadline instant itself is still a pass and the
    first failing instant is one second past it."
    PRD §3.8: "`fasting_overdue` is true exactly when the serving instant is
    strictly later than the deadline, so equality is still compliant and the flag
    flips only one second past the boundary."

    Design: Difficulty/boundary_precision_check/fasting_deadline_strict_greater_at_the_exact_instant
    """
    set_clock("2026-09-01T12:59:59Z")
    center = new_center(pediatric_capable=True)
    new_phlebotomist(center["id"], credential="RN")
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    patient = new_patient(full_name="Eli Sauer", birth_date="1993-06-30T00:00:00Z")
    order = new_order(center["id"], patient["id"], plan_id,
                      is_fasting_required=True, fasting_hours_required=8,
                      patient_last_food_utc="2026-09-01T05:00:00Z")
    order = resolve_insurance(order["id"])

    appointment = book(center["id"], order["id"], "2026-09-01T13:00:00Z")
    appointment = check_in(patient["id"], appointment["id"])
    call_patient(appointment["id"])

    set_clock("2026-09-01T13:00:00Z")
    headers = make_patient_headers(patient["id"])
    exact = validate_success(api.queue_status(appointment["id"], headers), 200)
    assert get_order(order["id"])["fasting_deadline_utc"] == "2026-09-01T13:00:00.000Z"
    assert exact["fasting_gate"] == "PASS", "the deadline instant itself is compliant"

    set_clock("2026-09-01T13:00:01Z")
    late = validate_success(api.queue_status(appointment["id"], headers), 200)
    assert late["fasting_gate"] == "FAIL"


def test_start_draw_one_second_past_the_deadline_is_refused(api):
    """PRD §2.6: "The fasting window runs sixth: when a fasting deadline is
    non-null and the instant at which the patient would be served is strictly
    after it, the operation is rejected with `ERR_FASTING_WINDOW_VIOLATED`
    (HTTP 422)."
    PRD §3.8: "the first failing instant is one second past it"

    Design: Difficulty/boundary_precision_check/fasting_deadline_strict_greater_at_the_exact_instant
    """
    set_clock("2026-09-01T12:59:59Z")
    center = new_center(pediatric_capable=True)
    phleb = new_phlebotomist(center["id"], credential="RN")
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    patient = new_patient(full_name="Eli Sauer", birth_date="1993-06-30T00:00:00Z")
    order = new_order(center["id"], patient["id"], plan_id,
                      is_fasting_required=True, fasting_hours_required=8,
                      patient_last_food_utc="2026-09-01T05:00:00Z")
    order = resolve_insurance(order["id"])
    appointment = book(center["id"], order["id"], "2026-09-01T13:00:00Z")
    appointment = check_in(patient["id"], appointment["id"])
    call_patient(appointment["id"])

    set_clock("2026-09-01T13:00:01Z")
    response = api_client.start_draw(appointment["id"], make_phlebotomist_headers(phleb["id"]))
    validate_error(response, ApiErrorId.ERR_FASTING_WINDOW_VIOLATED.value)

    assert get_appointment(appointment["id"])["draw_state"] == "CHECKED_IN"


def test_fasting_deadline_is_never_snapped_to_the_scheduling_grid(api):
    """PRD §2.5: "Every deadline, expiry, window boundary, and server-stamped
    `created_at` is computed against that logical clock."
    PRD §3.8: "it is never floor-rounded onto the scheduling grid"
    PRD §3.1: "A fasting order's deadline is the patient's last-food instant
    advanced by the required number of hours."

    Design: Corner/calculations/fasting_deadline_is_never_snapped_to_the_scheduling_grid
    """
    visit = setup_eligible_order(
        clock="2026-09-01T13:00:00Z",
        order_overrides={"is_fasting_required": True, "fasting_hours_required": 8,
                         "patient_last_food_utc": "2026-09-01T07:07:00Z"})

    order = get_order(visit["order"]["id"])
    assert order["fasting_deadline_utc"] == "2026-09-01T15:07:00.000Z"
    assert order["fasting_deadline_utc"] != "2026-09-01T15:00:00Z", (
        "the deadline must not be snapped down to a grid cell"
    )
    assert order["fasting_overdue"] is False


def test_a_fiscal_necessity_failure_outranks_the_order_of_draw_safety_check(api):
    """PRD §2.6: "The safety ladder sits at a lower priority level than the fiscal
    ladder described next, and on at least one endpoint the fiscal check is
    evaluated before the safety check."
    PRD §3.4: "the fiscal eligibility check runs before it, which is the
    deliberate inversion flagged in §3.1 and §2.6, not an accident."
    PRD §2.11: "**Fiscal.** The necessity-and-eligibility ladder plus the
    prepayment gate, evaluated in its fixed sub-order."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_necc_vs_safety_precedence_at_draw_start
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center(pediatric_capable=True)
    phleb = new_phlebotomist(center["id"], credential="RN")
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    api_client.create_necessity_rule({
        "test_panel": "CMP", "icd10_code": "R99", "is_covered": False,
    }, INTAKE)
    patient = new_patient(full_name="Fay Ibarra", birth_date="1994-11-05T00:00:00Z")
    order = new_order(center["id"], patient["id"], plan_id, icd10_codes=["R99"])
    resolve_necessity(order["id"])
    order = get_order(order["id"])
    assert order["necessity_status"] == "FAIL"
    order = resolve_insurance(order["id"])

    appointment = book(center["id"], order["id"], "2026-09-01T13:20:00Z")
    appointment = check_in(patient["id"], appointment["id"])
    call_patient(appointment["id"])

    # Register the tubes out of CLSI order so the safety floor is also violated.
    headers = make_phlebotomist_headers(phleb["id"])
    validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=4), headers), 201)
    validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="SODIUM_HEPARIN_GREEN",
                                volume_ml=4.0, order_of_draw=2), headers), 201)

    response = api_client.start_draw(appointment["id"], headers)
    error_id = response.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_MEDICAL_NECESSITY_FAILED.value, (
        "the priority 6 fiscal error must win at draw start"
    )
    assert error_id != ApiErrorId.ERR_ORDER_OF_DRAW_VIOLATION.value

    after = get_appointment(appointment["id"])
    assert after["draw_state"] == "CHECKED_IN"
    assert after["queue_state"] == "CALLED"


def test_a_pediatric_order_at_a_non_capable_center_is_refused_before_operating_hours(api):
    """PRD §2.6: "The pediatric feasibility check runs first: a `PEDIATRIC` order
    presented at a center whose `pediatric_capable` flag is false is rejected with
    `ERR_PEDIATRIC_CENTER_NOT_CAPABLE` (HTTP 422)."
    PRD §2.9: "An occupancy whose local start falls before opening or whose local
    end falls after closing is rejected with `ERR_OUTSIDE_OPERATING_HOURS`
    (HTTP 409)."

    Design: Corner/validations/pediatric_order_at_a_non_capable_center_is_rejected_before_hours_in_local_time
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center(name="Plain Draw Station", pediatric_capable=False)
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    kid = new_patient(full_name="Kid Sato", birth_date="2016-03-03T00:00:00Z")
    order = new_order(center["id"], kid["id"], plan_id, collection_mode="PEDIATRIC")
    order = resolve_insurance(order["id"])

    response = api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": order["id"],
        "scheduled_start_utc": "2026-09-01T23:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": order["version"],
    }, INTAKE)
    error_id = response.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_PEDIATRIC_CENTER_NOT_CAPABLE.value
    assert error_id != ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS.value

    listed = api_client.list_appointments(
        INTAKE, params={"service_center_id": center["id"]}).json()["data"]
    assert listed == []


def test_the_resolved_tube_plan_is_derived_identically_for_the_same_panel(api):
    """PRD §3.1: "The surviving set is the order's `resolved_tubes`, deduplicated
    by tube code, and it is identical for every order placed on the same panel."
    PRD §3.1: "The **draw order specification** is the same set re-sorted:
    `draw_order_spec` lists the resolved tubes by `order_of_draw` ascending,
    breaking ties on the earlier creation instant."

    Design: Corner/entities/test_order_get_exposes_computed_pediatric_and_derived_plan_fields
    """
    visit = setup_eligible_order(
        clock="2026-09-01T13:00:00Z",
        patient_overrides={"full_name": "Kid Sato", "birth_date": "2016-03-03T00:00:00Z"},
        order_overrides={"collection_mode": "PEDIATRIC"})
    order = get_order(visit["order"]["id"])
    assert order["patient_is_pediatric"] is True

    first = api_client.get_tube_plan(order["id"], TEST_USERS["lab_liaison_headers"])
    second = api_client.get_tube_plan(order["id"], TEST_USERS["lab_liaison_headers"])
    assert first.json()["data"]["resolved_tubes"] == second.json()["data"]["resolved_tubes"]
    assert order["concurrence_hash"] == get_order(order["id"])["concurrence_hash"]

    ranks = [row["order_of_draw"] if isinstance(row, dict) else row
             for row in order["draw_order_spec"]]
    assert ranks == sorted(ranks), "the draw order specification must ascend"


def test_a_pediatric_order_across_the_age_boundary_is_classified_by_the_bare_offset(api):
    """PRD §3.1: "The comparison uses a bare 18-year offset applied to the
    patient's `birth_date` in UTC, not a calendar-aware age. The consequence is
    visible at the boundary: a patient born 2008-09-01 is `PEDIATRIC` on
    2026-09-01 and non-pediatric on 2026-09-02."

    Design: Corner/entities/test_order_get_exposes_computed_pediatric_and_derived_plan_fields
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center(pediatric_capable=True)
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    patient = new_patient(full_name="Boundary Child",
                          birth_date="2008-09-01T00:00:00Z")
    order = new_order(center["id"], patient["id"], plan_id)
    assert get_order(order["id"])["patient_is_pediatric"] is True

    set_clock("2026-09-02T13:00:00Z")
    assert get_order(order["id"])["patient_is_pediatric"] is False