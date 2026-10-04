"""Second-angle tests for the difficulty instances whose first test lives elsewhere."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, create_estimate_payload, make_patient_headers,
    make_phlebotomist_headers, assert_version_incremented, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_staff_pending_visit, setup_center_and_plan,
    setup_windowed_visit, setup_windowed_compromised_specimen, new_center,
    new_patient, new_order, resolve_insurance, book, check_in, call_patient,
    get_order, get_appointment, get_specimen, set_clock, new_courier_run,
    draw_visit_to_collected, new_phlebotomist, setup_checked_in_visit,
    add_minutes,
)
from test_helpers.factories import create_specimen_payload


def test_the_recollection_release_and_replacement_leave_the_census_matched(api):
    """PRD §3.7: "A successful recollection moves the specimen to `RECOLLECTED`
    and stamps `recollection_approved_at_utc` with the logical clock."
    PRD §3.7: "Because it is derived only from those three inputs, a recollection
    can prove that it reproduces the original collection conditions simply by
    producing the same digest."

    Design: Difficulty/compensating_invariant/specimen_reassignment_chain_preserves_total_specimen_count
    """
    data = setup_windowed_compromised_specimen(
        compromise_reason="INSUFFICIENT_VOLUME", recollection_ready=True)
    headers = TEST_USERS["lab_liaison_headers"]
    order = get_order(data["order"]["id"])

    census_before = api_client.list_specimens(
        headers, params={"service_center_id": data["center"]["id"]}).json()["data"]
    assert len(census_before) == 1

    recollected = validate_success(
        api_client.recollect_specimen(data["specimen"]["id"], headers), 200)
    assert recollected["status"] == "RECOLLECTED"
    assert recollected["recollection_approved_at_utc"] is not None

    replacement = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        make_phlebotomist_headers(data["phlebotomist"]["id"])), 201)

    census_after = api_client.list_specimens(
        headers, params={"service_center_id": data["center"]["id"]}).json()["data"]
    assert len(census_after) == len(census_before) + 1, (
        "the release and the replacement are a matched pair"
    )
    assert get_specimen(data["specimen"]["id"])["status"] == "RECOLLECTED"
    assert replacement["status"] == "UNASSIGNED"


def test_the_attended_variant_is_strictly_cheaper_than_the_self_pay_variant(api):
    """PRD §3.5: "A `SELF_PAY_LIST` gross is exactly the effective rate, so it is
    strictly greater than an `ATTENDED_COLLECTED` gross whenever the three
    components sum to less than the allowed amount."
    PRD §3.5: "Against the reference fixture — copay 2500, coinsurance 0.25,
    allowed 10000 — the ratio of the self-pay figure to the attended figure is
    exactly 1.25, being 5000 against 4000, a discount of 1000."

    Design: Difficulty/dual_variant_calc/estimate_dual_variant_on_test_order
    """
    data = setup_eligible_order()
    center, plan_id = data["center"], data["plan_id"]

    self_pay_patient = new_patient(full_name="Bo Alvarez",
                                   birth_date="1988-01-11T00:00:00Z")
    self_pay_order = new_order(center["id"], self_pay_patient["id"], plan_id,
                              ordering_provider_npi="1700111240")
    # An INELIGIBLE order lands on the SELF_PAY_LIST branch of the ladder.
    self_pay_order = validate_success(
        api_client.insurance_resolve(self_pay_order["id"], INTAKE), 200)
    assert self_pay_order["insurance_status"] == "ELIGIBLE"

    attended_order = data["order"]
    attended = validate_success(api.create_estimate(
        attended_order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", attended_order["version"]),
        INTAKE), 201)
    assert attended["gross_cents"] == 5000
    assert attended["net_patient_cents"] == 4000
    assert attended["discount_cents"] == 1000

    # The same order under the self-pay branch would publish the whole rate.
    ratio = attended["gross_cents"] / attended["net_patient_cents"]
    assert ratio == 1.25
    assert self_pay_order["list_price_cents"] == attended["gross_cents"]


def test_the_nested_rounding_components_sum_to_the_pinned_gross(api):
    """PRD §2.12: "Rounding is applied to each component of a sum before the
    components are added, not once after. That ordering is not cosmetic. Where
    two terms each carry a residual of exactly one half-cent, per-component
    rounding and sum-then-round differ by exactly one cent, and this API's
    contract is the per-component order."
    PRD §3.5: "The three rounded components sum to `gross_cents`."

    Design: Difficulty/combinatorial_formula/estimate_nested_rounding_order_pins_one_cent
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    plan = validate_success(api_client.create_insurance_plan({
        "payer_name": "HALF CENT HMO", "plan_type": "HMO", "copay_cents": 2500,
        "coinsurance_pct": 0.25, "deductible_remaining_cents": 20000,
        "allowed_amount_cents": 10000, "prior_paid_pct": 0.125,
    }, INTAKE), 201)
    patient = new_patient()
    order = resolve_insurance(new_order(center["id"], patient["id"], plan["id"])["id"])

    estimate = validate_success(api.create_estimate(
        order["id"], create_estimate_payload("ATTENDED_COLLECTED", order["version"]),
        INTAKE), 201)

    components = (estimate["copay_component_cents"]
                  + estimate["coinsurance_component_cents"]
                  + estimate["deductible_component_cents"])
    assert components == estimate["gross_cents"] == 11251, (
        "the published components must sum exactly to the pinned gross"
    )
    # Each half-cent term was rounded up independently before the sum.
    assert estimate["coinsurance_component_cents"] == 2188
    assert estimate["deductible_component_cents"] == 6563
    assert estimate["discount_cents"] == 2250
    assert estimate["net_patient_cents"] == estimate["gross_cents"] - estimate["discount_cents"]


def test_rejection_cascades_onto_the_specimen_and_leaves_the_visit_drawn(api):
    """PRD §3.7: "Rejecting increments `day_rejection_index`"
    PRD §3.7: "The order's status returns from `COLLECTED` to `SCHEDULED`, which
    puts it back on the worklist"
    PRD §2.11: "**State.** The target resource must be in a state that permits
    the operation."

    Design: Difficulty/non_linear_state_machine/order_rejects_and_reverts_making_status_cyclic
    """
    data = setup_windowed_compromised_specimen(compromise_reason="HEMOLYZED")
    headers = TEST_USERS["lab_liaison_headers"]
    appointment_id = data["appointment"]["id"]
    before_appointment = get_appointment(appointment_id)

    rejected = validate_success(
        api_client.reject_specimen(data["specimen"]["id"], headers), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["day_rejection_index"] == 1

    order_after = get_order(data["order"]["id"])
    assert order_after["status"] == "SCHEDULED"
    # Only the order left its completed state; the visit that drew the tube did
    # not, and neither did the courier run's planned posture.
    after_appointment = get_appointment(appointment_id)
    assert after_appointment["draw_state"] == before_appointment["draw_state"] == "DRAWN"
    assert api_client.get_courier_run(
        data["courier_run"]["id"], headers).json()["data"]["status"] == "PLANNED"


def test_the_two_appointment_dimensions_advance_independently_on_a_staff_hold(api):
    """PRD §3.3: "A visit is represented by an **appointment**, which carries two
    independent state dimensions. The first is `queue_state`, tracking the
    patient's position in the room ... The second is `draw_state`, tracking the
    clinical act"
    PRD §3.3: "That transition stamps `staff_pending_at_utc` with the logical
    clock, sets `draw_hold_expires_utc` to that instant plus the center's
    `draw_hold_minutes` (which defaults to 30), and clears the assignment by
    setting `station_index` to the sentinel −1 and `phlebotomist_id` to null."

    Design: Difficulty/non_linear_state_machine/appointment_runs_two_parallel_dimensions_with_hold_expiry
    """
    visit = setup_staff_pending_visit()
    phleb_before = api_client.get_phlebotomist(
        visit["phlebotomist"]["id"], TEST_USERS["supervisor_headers"]).json()["data"]

    api_client.call_appointment(visit["appointment"]["id"], INTAKE)

    appointment = get_appointment(visit["appointment"]["id"])
    assert appointment["draw_state"] == "STAFF_PENDING"
    assert appointment["queue_state"] == "WAITING"
    assert appointment["station_index"] == -1
    assert appointment["phlebotomist_id"] is None
    # staff_pending_at_utc is the check-in instant, plus the center's hold.
    assert appointment["draw_hold_expires_utc"] == "2026-09-01T14:00:00.000Z"
    assert appointment["draw_hold_expired"] is False

    phleb_after = api_client.get_phlebotomist(
        visit["phlebotomist"]["id"], TEST_USERS["supervisor_headers"]).json()["data"]
    assert phleb_after["status"] == phleb_before["status"] == "ON_DUTY", (
        "entering the hold changes no phlebotomist status and reserves no station"
    )


def test_the_estimate_recompute_rewrites_the_balance_from_the_collected_total(api):
    """PRD §3.5: "the order's `balance_remaining_cents` is reset to the leftover
    of the responsibility over `prepay_collected_cents`, floored at zero"
    PRD §3.5: "Each collection adds to the order's `prepay_collected_cents` and
    resets `balance_remaining_cents` to the leftover of
    `patient_responsibility_cents` over the collected total, floored at zero."

    Design: Difficulty/transitive_cascade/estimate_chain_order_balance_to_occ_rejection_depth4
    """
    data = setup_eligible_order(clock="2026-09-01T13:30:00Z")
    center, patient = data["center"], data["patient"]
    order = data["order"]
    # The center has no phlebotomist yet, and PRD §2.6 makes an on-duty
    # credential covering the mode a precondition of the call and the draw, so
    # the visit can only reach the station once one is rostered.
    start_draw_phleb = new_phlebotomist(center["id"], credential="RN")
    appointment = book(center["id"], order["id"], "2026-09-01T14:00:00Z")
    check_in(patient["id"], appointment["id"])
    call_patient(appointment["id"])

    # PRD §3.4: start-draw fixes the ATTENDED_COLLECTED recosting before the
    # estimate is collected; without it the draw gate's prepayment condition
    # (prepay_collected < prepay_required) rejects the start.
    validate_success(api_client.start_draw(
        appointment["id"], make_phlebotomist_headers(start_draw_phleb["id"])), 200)

    after_draw_version = get_order(order["id"])["version"]
    estimate = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", after_draw_version), INTAKE), 201)
    assert estimate["net_patient_cents"] == 4000

    collected = get_order(order["id"])
    assert collected["patient_responsibility_cents"] == 4000
    assert collected["balance_remaining_cents"] == 4000
    assert_version_incremented(collected["version"], after_draw_version)

    validate_success(api_client.prepay(appointment["id"], 1500, INTAKE), 200)
    settled = get_order(order["id"])
    assert settled["prepay_collected_cents"] == 1500
    assert settled["balance_remaining_cents"] == 2500, (
        "the balance is the floored leftover of responsibility over collected"
    )


def test_the_eligible_read_returns_the_named_run_when_one_is_inside_the_interval(api):
    """PRD §3.6: "The chosen run is the `OUTBOUND` run of the center whose
    `dispatch_utc` falls in the commit interval and whose status is still
    `PLANNED`."
    PRD §3.6: "the published eligible-runs read, by contrast, returns an empty set
    as a declared sentinel rather than an error."

    Design: Difficulty/boundary_precision_check/empty_candidate_set_on_courier_selector_returns_declared_sentinel
    """
    data = setup_windowed_visit()
    headers = TEST_USERS["lab_liaison_headers"]
    # 18 hours after the check-in instant lands exactly on the commit interval's
    # inclusive opening edge.
    inside = new_courier_run(data["center"]["id"], "2026-09-02T06:45:00Z")

    response = api_client.list_eligible_courier_runs(headers, specimen_id=data["specimen"]["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "array"
    assert [row["id"] for row in body["data"]] == [inside["id"]]
    assert body["data"] != [], "an eligible run inside the interval must be published"


def test_an_order_schedules_once_its_appointment_is_still_in_scheduled_draw_state(api):
    """PRD §3.2: "An order moves from `RECEIVED` to `SCHEDULED` once it is
    fiscally cleared and a drawable visit exists for it."
    PRD §3.2: "Third, an open appointment for this order must already exist in
    `draw_state` `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/order_scheduling_requires_appointment_in_scheduled_draw_state
    """
    data = setup_eligible_order(clock="2026-09-01T13:00:00Z")
    order = data["order"]
    appointment = book(data["center"]["id"], order["id"], "2026-09-01T14:00:00Z")
    assert get_appointment(appointment["id"])["draw_state"] == "SCHEDULED"
    assert order["insurance_status"] == "ELIGIBLE"
    assert order["necessity_status"] == "PASS"

    scheduled = validate_success(api_client.schedule_test_order(order["id"], INTAKE), 200)
    assert scheduled["status"] == "SCHEDULED"