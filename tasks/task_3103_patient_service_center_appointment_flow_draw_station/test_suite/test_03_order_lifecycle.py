"""Test-order lifecycle: cyclic rejection revert, cancellation, and terminal lockdown."""
import pytest

from test_helpers import (
    validate_success, api_client, INTAKE, TEST_USERS, validate_error,
    ApiErrorId, assert_version_incremented,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_collected_order_with_specimen,
    setup_windowed_compromised_specimen,
    setup_cancelled_order, get_order, get_appointment, get_specimen, new_patient,
    new_order, resolve_insurance, book, check_in, call_patient, set_clock,
    seed_reference, new_center, new_phlebotomist, run_ops, setup_center_and_plan,
    CLOCK_MORNING,
)
from test_helpers import make_patient_headers, make_phlebotomist_headers, make_lab_system_headers
from test_helpers.factories import create_specimen_payload
from test_helpers.test_users import TEST_USERS as _USERS

LIAISON = _USERS["lab_liaison_headers"]


def test_rejection_reverts_a_collected_order_back_onto_the_worklist(api):
    """PRD §3.7: "The order's status returns from `COLLECTED` to `SCHEDULED`,
    which puts it back on the worklist; its `is_fasting_required` is cleared to
    false and its `fasting_hours_required` to 0; its `patient_last_food_utc` is
    cleared to null; and its `fasting_deadline_utc` becomes null as a
    consequence."
    PRD §3.7: "the ripple is what makes the order's lifecycle cyclic rather than
    a straight line"

    Design: Difficulty/non_linear_state_machine/order_rejects_and_reverts_making_status_cyclic
    """
    data = setup_windowed_compromised_specimen(
        compromise_reason="HEMOLYZED",
        order_overrides={"is_fasting_required": True, "fasting_hours_required": 20,
                         "patient_last_food_utc": "2026-09-01T04:00:00Z"})
    order_before = get_order(data["order"]["id"])
    assert order_before["status"] == "COLLECTED"
    assert order_before["fasting_deadline_utc"] is not None, (
        "the order reaches the draw carrying a live fasting deadline, so its "
        "clearance at rejection is observable"
    )
    appointment_before = get_appointment(data["appointment"]["id"])

    specimen = validate_success(
        api.reject_specimen(data["specimen"]["id"], TEST_USERS["lab_liaison_headers"]), 200)
    assert specimen["status"] == "REJECTED"

    order_after = get_order(data["order"]["id"])
    assert order_after["status"] == "SCHEDULED", (
        "the rejection must put the order back on the worklist"
    )
    assert order_after["is_fasting_required"] is False
    assert order_after["fasting_hours_required"] == 0
    assert order_after["patient_last_food_utc"] is None
    assert order_after["fasting_deadline_utc"] is None

    # Only the order reverted; the visit that produced the specimen did not.
    appointment_after = get_appointment(data["appointment"]["id"])
    assert appointment_after["draw_state"] == appointment_before["draw_state"] == "DRAWN"


def test_rejection_increments_the_specimens_local_day_rejection_index(api):
    """PRD §3.7: "Rejecting increments `day_rejection_index`, and the counting
    rule is particular. The index counts the specimens belonging to the same
    order whose status is `REJECTED` and whose collection falls on the same local
    calendar day as the logical clock at the moment of rejection — including the
    specimen currently being rejected"
    PRD §3.7: "The fasting conservation instant is pinned to the logical clock
    at this moment"

    Design: Difficulty/transitive_cascade/rejection_chain_specimen_order_fasting_gate_depth4
    """
    data = setup_windowed_compromised_specimen(compromise_reason="CLOTTED")
    specimen_before = get_specimen(data["specimen"]["id"])
    assert specimen_before["day_rejection_index"] == 0

    specimen = validate_success(
        api.reject_specimen(data["specimen"]["id"],
                            TEST_USERS["lab_liaison_headers"]), 200)
    assert specimen["status"] == "REJECTED"
    assert specimen["day_rejection_index"] == 1

    order_after = get_order(data["order"]["id"])
    assert order_after["status"] == "SCHEDULED"
    assert order_after["is_fasting_required"] is False
    assert order_after["fasting_deadline_utc"] is None

    # The put-back released the run's committed slot.
    run = api_client.get_courier_run(
        data["courier_run"]["id"], TEST_USERS["lab_liaison_headers"]).json()["data"]
    assert run["committed_specimen_count"] == 0


def test_cancel_is_refused_on_an_order_that_has_already_been_cancelled(api):
    """PRD §2.11: "**State.** The target resource must be in a state that
    permits the operation. A second, strictly sequential identical request
    observes the state written by the first and is rejected here."
    PRD §3.2: "Cancelling writes `CANCELLED` — a terminal status"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_precedence_at_order_cancel
    """
    data = setup_cancelled_order()
    assert data["order"]["status"] == "CANCELLED"

    response = api_client.cancel_test_order(data["order"]["id"], INTAKE)
    assert response.status_code == 409, (
        f"a second cancel must be a state rejection, got {response.status_code}"
    )
    error_id = response.json()["data"]["error_id"]
    assert error_id in (
        ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_ALREADY_TERMINAL.value
    )
    assert error_id != ApiErrorId.ERR_INSURANCE_PLAN_NOT_FOUND.value, (
        "the cross-entity integrity catalogue entry must not outrank the state path"
    )

    order_after = get_order(data["order"]["id"])
    assert order_after["status"] == "CANCELLED"


def test_cancel_is_refused_on_a_collected_order(api):
    """PRD §3.2: "An `IntakeCoordinator` may abandon an order from either
    `RECEIVED` or `SCHEDULED`."
    PRD §2.11: "**State.** The target resource must be in a state that permits
    the operation."

    Design: Corner/state_machines/cancel_from_a_collected_order_returns_invalid_state
    """
    data = setup_collected_order_with_specimen()
    assert data["order"]["status"] == "COLLECTED"

    validate_error(api_client.cancel_test_order(data["order"]["id"], INTAKE),
                   ApiErrorId.ERR_INVALID_STATE.value)

    order_after = get_order(data["order"]["id"])
    assert order_after["status"] == "COLLECTED"
    specimen_after = get_specimen(data["specimen"]["id"])
    assert specimen_after["status"] == "UNASSIGNED", (
        "a refused cancel must not move the order's specimens to REJECTED"
    )


def test_cancelling_an_order_cascades_no_show_and_rejection_onto_its_children(api):
    """PRD §3.2: "Every non-terminal appointment belonging to the order is moved
    to `draw_state` `NO_SHOW`. Every non-terminal specimen belonging to the order
    is moved to status `REJECTED`."
    PRD §3.2: "An `IntakeCoordinator` may abandon an order from either `RECEIVED`
    or `SCHEDULED`", and "no specimen belonging to the order may be in status
    `ASSIGNED`, `IN_TRANSIT`, or `RECEIVED`" — so a registered but not yet
    assigned tube is exactly the child this cascade is allowed to sweep.

    Design: Corner/state_machines/cancel_from_a_collected_order_returns_invalid_state
    """
    visit = setup_eligible_order(clock="2026-09-01T13:35:00Z")
    center, patient, order = visit["center"], visit["patient"], visit["order"]
    appointment = book(center["id"], order["id"], "2026-09-01T14:00:00Z")
    check_in(patient["id"], appointment["id"])
    specimen = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        make_lab_system_headers(center["id"])), 201)
    assert get_order(order["id"])["status"] == "SCHEDULED"
    assert get_specimen(specimen["id"])["status"] == "UNASSIGNED"

    validate_success(api_client.cancel_test_order(order["id"], INTAKE), 200)

    assert get_order(order["id"])["status"] == "CANCELLED"
    assert get_appointment(appointment["id"])["draw_state"] == "NO_SHOW"
    assert get_specimen(specimen["id"])["status"] == "REJECTED"


def test_scheduling_an_order_requires_its_appointment_still_in_scheduled_draw_state(api):
    """PRD §3.2: "Third, an open appointment for this order must already exist in
    `draw_state` `SCHEDULED`."
    PRD §3.2: "An order moves from `RECEIVED` to `SCHEDULED` once it is fiscally
    cleared and a drawable visit exists for it."
    PRD §2.11: "**State.** The target resource must be in a state that permits
    the operation."

    Design: Difficulty/cross_entity_state_dependency/order_scheduling_requires_appointment_in_scheduled_draw_state
    """
    visit = setup_eligible_order(clock="2026-09-01T13:35:00Z")
    order = visit["order"]
    appointment = book(visit["center"]["id"], order["id"], "2026-09-01T14:00:00Z")
    check_in(visit["patient"]["id"], appointment["id"])
    # PRD §3.3: check-in drags the linked order from RECEIVED to SCHEDULED — a
    # permitted target state — while the visit goes live. The ops checkpoint
    # then abandons the overrun row, so the order holds SCHEDULED with no open
    # appointment still in draw_state SCHEDULED.
    set_clock("2026-09-01T14:45:00Z")
    run_ops(visit["center"]["id"])
    assert get_appointment(appointment["id"])["draw_state"] == "NO_SHOW"

    response = api_client.schedule_test_order(order["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert get_order(order["id"])["status"] == "SCHEDULED"
    assert get_appointment(appointment["id"])["draw_state"] == "NO_SHOW"


def test_intake_settles_necessity_immediately_and_leaves_eligibility_unverified(api):
    """PRD §3.1: "A newly received order lands in status `RECEIVED`. Its
    `insurance_status` begins at `UNVERIFIED`, both `est_copay_cents` and
    `est_coinsurance_cents` begin at 0, and its necessity outcome is settled
    immediately if there is nothing to screen: when `icd10_codes` is empty,
    `necessity_status` begins at `PASS`"
    PRD §3.1: "When codes were supplied, the status begins at `PENDING` and waits
    to be resolved."

    Design: Corner/state_machines/test_order_starts_received_with_necessity_pending_when_codes_are_supplied
    """
    center, plan_id = setup_center_and_plan(clock=CLOCK_MORNING)
    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan_id, icd10_codes=[])
    assert order["status"] == "RECEIVED"
    assert order["necessity_status"] == "PASS"
    assert order["insurance_status"] == "UNVERIFIED"
    assert order["est_copay_cents"] == 0
    assert order["est_coinsurance_cents"] == 0
    # PRD §3.2 makes eligibility resolution the separate, later screen: resolving
    # it is what moves `UNVERIFIED` off its intake default.
    resolved = resolve_insurance(order["id"])
    assert resolved["insurance_status"] == "ELIGIBLE"


def test_necessity_resolution_distinguishes_pending_from_failed(api):
    """PRD §3.2: "If no supplied code matches any rule for the panel at all —
    the codes are simply unknown to the grid — the outcome is `PENDING` rather
    than a failure."
    PRD §2.7: "an order whose `necessity_status` is still `PENDING` is rejected
    with `ERR_MEDICAL_NECESSITY_PENDING` (HTTP 402)."

    Design: Corner/validations/necessity_pending_blocks_check_in_with_its_own_error
    """
    data = setup_eligible_order(order_overrides={"icd10_codes": ["ZZZ.9"]})
    order = data["order"]
    resolved = validate_success(api_client.necessity_check(order["id"], INTAKE), 200)
    assert resolved["necessity_status"] == "PENDING"

    order = resolve_insurance(order["id"])
    appointment = book(data["center"]["id"], order["id"], "2026-09-01T14:00:00Z")
    response = api_client.check_in(appointment["id"], make_patient_headers(data["patient"]["id"]))
    validate_error(response, ApiErrorId.ERR_MEDICAL_NECESSITY_PENDING.value)

    assert get_appointment(appointment["id"])["draw_state"] == "SCHEDULED"