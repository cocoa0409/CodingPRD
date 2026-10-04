"""Recollection gating, the courier capacity guard, and second-angle coverage of the
precedence, overlap and cascade pairs."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, make_patient_headers, create_estimate_payload,
    make_phlebotomist_headers,
)
from test_helpers.fixtures import (
    setup_windowed_compromised_specimen, setup_windowed_assigned_specimen,
    setup_eligible_order, setup_center_and_plan, new_center, new_patient,
    new_order, resolve_insurance, book, check_in, get_order, get_appointment,
    get_specimen, new_courier_run, set_clock, setup_windowed_visit,
    new_phlebotomist,
)
from test_helpers.factories import create_specimen_payload


def test_recollection_schedules_a_fresh_visit_and_keeps_prepay_at_zero(api):
    """PRD §3.7: "A successful recollection moves the specimen to `RECOLLECTED`
    and stamps `recollection_approved_at_utc` with the logical clock. It returns
    the order to `SCHEDULED` and creates a fresh appointment for it in
    `draw_state` `SCHEDULED`."
    PRD §3.5: "A recollection visit is exempt: after a specimen is recollected,
    the order's required prepayment stays at zero for that visit, because
    prepayment is charged on the first visit only."

    Design: Difficulty/cross_entity_state_dependency/specimen_recollection_requires_run_outbound_and_planned
    """
    data = setup_windowed_compromised_specimen(compromise_reason="HEMOLYZED",
                                             recollection_ready=True)
    headers = TEST_USERS["lab_liaison_headers"]
    order = get_order(data["order"]["id"])

    appointments_before = api_client.list_appointments(
        INTAKE, params={"test_order_id": order["id"]}).json()["data"]

    recollected = validate_success(
        api_client.recollect_specimen(data["specimen"]["id"], headers), 200)
    assert recollected["status"] == "RECOLLECTED"
    assert recollected["recollection_approved_at_utc"] is not None

    reopened = get_order(order["id"])
    assert reopened["status"] == "SCHEDULED"
    assert reopened["prepay_required_cents"] == 0

    appointments_after = api_client.list_appointments(
        INTAKE, params={"test_order_id": order["id"]}).json()["data"]
    assert len(appointments_after) == len(appointments_before) + 1
    fresh = [row for row in appointments_after
             if all(row["id"] != old["id"] for old in appointments_before)]
    assert len(fresh) == 1
    assert fresh[0]["draw_state"] == "SCHEDULED"


def test_recollection_only_releases_the_first_visit_and_the_run_stays_planned(api):
    """PRD §3.7: "It also requires that the visit's recollection count be zero,
    meaning the first recollection of a visit is the only one this path will
    schedule; `REPEAT_WINDOW_HOURS` is 24, and the count is taken over specimens
    belonging to the order that are `RECOLLECTED` and whose approval instant is
    within 24 hours of the logical clock."
    PRD §3.7: "The recollection-scheduling run must itself be `OUTBOUND`,
    `PLANNED`, and inside the same 30-minute lead and 15-minute cutoff rules that
    govern ordinary assignment."

    Design: Difficulty/cross_entity_state_dependency/specimen_recollection_requires_run_outbound_and_planned
    """
    data = setup_windowed_compromised_specimen(compromise_reason="CLOTTED",
                                              recollection_ready=True)
    headers = TEST_USERS["lab_liaison_headers"]
    order = get_order(data["order"]["id"])

    validate_success(api_client.recollect_specimen(data["specimen"]["id"], headers), 200)

    # A second compromised specimen on the same order, inside the 24-hour repeat
    # window, cannot open a second recollection of the same visit.
    set_clock("2026-09-01T13:00:00Z")
    second = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        TEST_USERS["phlebotomist_headers"]), 201)
    run = data["courier_run"]
    assert get_courier_run_status(run["id"], headers) == "PLANNED"
    validate_success(api_client.assign_courier(second["id"], run["id"], headers), 200)
    set_clock("2026-09-01T17:50:00Z")
    validate_success(api_client.compromise_specimen(second["id"], "HEMOLYZED", headers), 200)

    response = api_client.recollect_specimen(second["id"], headers)
    assert response.status_code >= 400, (
        "the repeat window admits only the first recollection of a visit"
    )
    assert get_specimen(second["id"])["status"] == "COMPROMISED"
    assert get_specimen(second["id"])["recollection_approved_at_utc"] is None


def get_courier_run_status(courier_run_id, headers):
    return api_client.get_courier_run(courier_run_id, headers).json()["data"]["status"]


def test_a_put_back_frees_exactly_one_slot_for_the_next_assignment(api):
    """PRD §2.10: "The capacity guard applied on writes is derived from the count
    after a decrement, so a put-back that lands the run at exactly capacity frees
    one slot rather than two."
    PRD §2.10: "A run tracks `committed_specimen_count`, which rises by one for
    each specimen assigned and falls by one when an assignment is undone"

    Design: Difficulty/combinatorial_formula/capacity_gate_evaluates_before_discount_keyed_on_result
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]
    run_id = data["courier_run"]["id"]
    assert get_courier_run_status(run_id, headers) == "PLANNED"

    set_clock("2026-09-01T17:50:00Z")
    validate_success(api_client.compromise_specimen(data["specimen"]["id"],
                                                    "HEMOLYZED", headers), 200)
    run_after_put_back = api_client.get_courier_run(run_id, headers).json()["data"]
    assert run_after_put_back["committed_specimen_count"] == 0

    # The write-time guard reads the post-decrement value, so a re-assignment
    # finds a free slot and the run returns to exactly one committed specimen.
    set_clock("2026-09-01T12:30:00Z")
    replacement = validate_success(api_client.create_specimen(
        create_specimen_payload(data["order"]["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        TEST_USERS["phlebotomist_headers"]), 201)
    validate_success(api_client.assign_courier(replacement["id"], run_id, headers), 200)

    run_final = api_client.get_courier_run(run_id, headers).json()["data"]
    assert run_final["committed_specimen_count"] == 1, (
        "the put-back must free one slot, not two"
    )


def test_the_committed_count_never_drifts_across_an_assign_put_back_round_trip(api):
    """PRD §2.10: "the count is never allowed to drift from the set of specimens
    actually committed to the run."
    PRD §2.10: "The band published on reads is derived from the count before any
    pending decrement"

    Design: Difficulty/combinatorial_formula/capacity_gate_evaluates_before_discount_keyed_on_result
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]
    run_id = data["courier_run"]["id"]

    before = api_client.get_courier_run(run_id, headers).json()["data"]
    assert before["committed_specimen_count"] == 1
    rows = api_client.list_specimens(headers, params={"courier_run_id": run_id}).json()["data"]
    assert len(rows) == before["committed_specimen_count"]

    set_clock("2026-09-01T17:50:00Z")
    validate_success(api_client.compromise_specimen(data["specimen"]["id"],
                                                    "INSUFFICIENT_VOLUME", headers), 200)

    after = api_client.get_courier_run(run_id, headers).json()["data"]
    assert after["committed_specimen_count"] == 0
    rows_after = api_client.list_specimens(
        headers, params={"courier_run_id": run_id}).json()["data"]
    assert len(rows_after) == after["committed_specimen_count"]


def test_a_necessity_failure_alone_still_blocks_the_draw_at_the_fiscal_step(api):
    """PRD §2.7: "Necessity is evaluated first: an order whose `necessity_status`
    is `FAIL` is rejected with `ERR_MEDICAL_NECESSITY_FAILED` (HTTP 402)"
    PRD §3.4: "the fiscal eligibility check runs before it, which is the
    deliberate inversion flagged in §3.1 and §2.6, not an accident."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_necc_vs_safety_precedence_at_draw_start
    """
    set_clock("2026-09-01T13:30:00Z")
    center = new_center(pediatric_capable=True)
    plan_id = api_client.seed_reference(
        TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    api_client.create_necessity_rule(
        {"test_panel": "CBC", "icd10_code": "Z00.0", "is_covered": False}, INTAKE)
    # PRD §2.6 makes an on-duty credential covering the mode a precondition of
    # the call, so the visit can only reach the station once one is rostered.
    phleb = new_phlebotomist(center["id"], credential="PBT", full_name="Omar Vela")
    patient = new_patient(full_name="Fay Ibarra", birth_date="1994-11-05T00:00:00Z")
    order = new_order(center["id"], patient["id"], plan_id, test_panel="CBC",
                      icd10_codes=["Z00.0"])
    api_client.necessity_check(order["id"], INTAKE)
    order = resolve_insurance(order["id"])
    assert order["necessity_status"] == "FAIL"

    appointment = book(center["id"], order["id"], "2026-09-01T13:45:00Z")
    appointment = check_in(patient["id"], appointment["id"])
    api_client.call_appointment(appointment["id"], INTAKE)

    response = api_client.start_draw(appointment["id"],
                                     make_phlebotomist_headers(phleb["id"]))
    validate_error(response, ApiErrorId.ERR_MEDICAL_NECESSITY_FAILED.value)
    assert get_appointment(appointment["id"])["draw_state"] == "CHECKED_IN"


def test_a_second_cancel_cannot_fall_through_to_a_lower_priority_catalogue_entry(api):
    """PRD §2.11: "**State.** The target resource must be in a state that permits
    the operation. A second, strictly sequential identical request observes the
    state written by the first and is rejected here."
    PRD §2.11: "**Cross-entity integrity and uniqueness.** Referential-integrity
    failures are reported in a fixed pairing order"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_precedence_at_order_cancel
    """
    data = setup_eligible_order()
    validate_success(api_client.cancel_test_order(data["order"]["id"], INTAKE), 200)

    response = api_client.cancel_test_order(data["order"]["id"], INTAKE)
    assert response.status_code >= 400
    assert response.json()["data"]["error_id"] not in (
        ApiErrorId.ERR_INSURANCE_PLAN_NOT_FOUND.value,
        ApiErrorId.ERR_TUBE_REQUIREMENT_MISSING.value,
    ), "the state path must be reported ahead of the integrity catalogue"
    assert get_order(data["order"]["id"])["status"] == "CANCELLED"


def test_two_courier_runs_an_instant_apart_coexist_on_the_same_center(api):
    """PRD §2.9: "Two courier runs of the same center must not share an identical
    dispatch instant while either is still live"
    PRD §2.9: "Adjacent intervals are accepted. Two occupancies that merely touch
    at a boundary do not collide"

    Design: Difficulty/resource_temporal_overlap/courier_run_duplicate_dispatch_instant_rejected_on_distinct_resource
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    headers = TEST_USERS["lab_liaison_headers"]

    first = new_courier_run(center["id"], "2026-09-01T16:00:00Z")
    second = new_courier_run(center["id"], "2026-09-01T16:01:00Z")
    assert first["id"] != second["id"]
    assert second["cutoff_utc"] == "2026-09-01T15:46:00.000Z"

    listed = api_client.list_courier_runs(
        headers, params={"service_center_id": center["id"], "status": "PLANNED"}).json()["data"]
    assert {row["id"] for row in listed} == {first["id"], second["id"]}


def test_the_interval_duplicate_is_detected_regardless_of_which_side_is_created(api):
    """PRD §2.9: "Pair comparisons are order-insensitive: a collision is detected
    regardless of which of the two the request is attempting to create."
    PRD §2.9: "an equal `[start, start + slot_span * slot_minutes)` interval is
    rejected with `ERR_SLOT_ALREADY_TAKEN`"

    Design: Difficulty/resource_temporal_overlap/appointment_interval_adjacency_accepted_duplicate_rejected
    """
    set_clock("2026-09-01T12:30:00Z")
    center = new_center(station_count=4)
    plan_id = api_client.seed_reference(
        TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    orders = []
    for npi in ("1700111233", "1700111234"):
        patient = new_patient()
        orders.append(resolve_insurance(
            new_order(center["id"], patient["id"], plan_id, ordering_provider_npi=npi)["id"]))

    incumbent = validate_success(api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[0]["id"],
        "scheduled_start_utc": "2026-09-01T15:00:00Z", "slot_span": 2,
        "source": "BOOKED", "expected_test_order_version": orders[0]["version"],
    }, INTAKE), 201)
    assert incumbent["slot_span"] == 2

    # The same two-cell interval, attempted from the other side of the pair.
    duplicate = api_client.create_appointment({
        "service_center_id": center["id"], "test_order_id": orders[1]["id"],
        "scheduled_start_utc": "2026-09-01T15:00:00Z", "slot_span": 2,
        "source": "BOOKED", "expected_test_order_version": orders[1]["version"],
    }, INTAKE)
    validate_error(duplicate, ApiErrorId.ERR_SLOT_ALREADY_TAKEN.value)


def test_a_rejected_specimen_leaves_the_order_gate_reading_pass_from_that_instant(api):
    """PRD §3.8: "That revert writes a fasting conservation instant equal to the
    logical clock at that moment, and that instant is the first point as the
    clock advances at which the gate flips from failing to passing."
    PRD §3.8: "once the rejection has pinned that instant, the gate reads nothing
    but the pinned deadline thereafter."

    Design: Difficulty/transitive_cascade/rejection_chain_specimen_order_fasting_gate_depth4
    """
    data = setup_windowed_compromised_specimen(
        compromise_reason="CLOTTED",
        order_overrides={"is_fasting_required": True, "fasting_hours_required": 20,
                         "patient_last_food_utc": "2026-09-01T04:00:00Z"})
    headers = TEST_USERS["lab_liaison_headers"]
    validate_success(api_client.reject_specimen(data["specimen"]["id"], headers), 200)

    order = get_order(data["order"]["id"])
    assert order["status"] == "SCHEDULED"
    assert order["fasting_deadline_utc"] is None
    assert order["is_fasting_required"] is False

    # A null deadline cannot be breached, so the gate is vacuously compliant.
    assert order["fasting_overdue"] is False
    assert get_specimen(data["specimen"]["id"])["day_rejection_index"] == 1
    run = api_client.get_courier_run(data["courier_run"]["id"], headers).json()["data"]
    assert run["committed_specimen_count"] == 0


def test_the_order_reverting_on_rejection_keeps_its_identifier_and_creation_stamp(api):
    """PRD §2.4: "`id` is a server-minted UUID string. It carries no type prefix
    and no human-readable segment; consumers must treat it as opaque."
    PRD §3.7: "The order's status returns from `COLLECTED` to `SCHEDULED`, which
    puts it back on the worklist"

    Design: Difficulty/transitive_cascade/rejection_chain_specimen_order_fasting_gate_depth4
    """
    data = setup_windowed_compromised_specimen(compromise_reason="HEMOLYZED")
    headers = TEST_USERS["lab_liaison_headers"]
    before = get_order(data["order"]["id"])

    validate_success(api_client.reject_specimen(data["specimen"]["id"], headers), 200)

    after = get_order(data["order"]["id"])
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    assert after["status"] == "SCHEDULED"
    assert after["version"] > before["version"], "the revert is a mutation like any other"