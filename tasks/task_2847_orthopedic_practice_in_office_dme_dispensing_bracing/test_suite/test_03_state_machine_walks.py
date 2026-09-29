"""Three machines whose reachable states are not a straight line: the encounter's
two dimensions advancing side by side, the fabrication rework cycle with its
round cap, and the return fork that rejoins on a refit.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    add_fitter,
    assert_encounter_states,
    assert_error,
    assert_shelf,
    build_practice,
    make_dme_fitter_headers,
    practice_admin_headers,
    read_encounter,
    read_fab_order,
    read_fitter,
    read_shelf,
)
from test_helpers import factories as f


def test_note_and_verification_move_one_dimension_each(api):
    """Signing the note moves the clinical dimension while the financial one
    stands still, and verifying coverage does the opposite.

    PRD: "A `DispenseEncounter` carries two independent state fields on one row,
    and they never share a value, so any state name in this document
    unambiguously identifies its dimension."

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_financial_dimensions_evolve_independently
    """
    practice = build_practice(api)
    opened = practice.open_encounter()
    assert_encounter_states(opened, clinical_status="DRAFT", financial_status="UNVERIFIED")

    documented = practice.sign_note(opened["id"])
    assert_encounter_states(
        read_encounter(api, opened["id"]), clinical_status="DOCUMENTED", financial_status="UNVERIFIED"
    )

    practice.attest(opened["id"])
    assert_encounter_states(
        read_encounter(api, opened["id"]), clinical_status="DOCUMENTED", financial_status="UNVERIFIED"
    )

    practice.verify_coverage(opened["id"])
    assert_encounter_states(
        read_encounter(api, opened["id"]), clinical_status="DOCUMENTED", financial_status="VERIFIED"
    )

    practice.reserve(opened["id"])
    assert_encounter_states(
        read_encounter(api, opened["id"]), clinical_status="RESERVED", financial_status="VERIFIED"
    )
    assert documented["clinical_status"] == "DOCUMENTED"


def test_rejected_fitting_rewinds_only_the_clinical_dimension_and_still_books_time(api):
    """A rejected fitting sends the clinical dimension back to documented and
    releases the shelf hold while the financial dimension keeps its verified
    posture, and the fitter is credited for both sessions.

    PRD: "`REJECTED` sends the encounter back for a new device decision: it reverts
    `RESERVED → DOCUMENTED` and compensates the reservation by reducing the shelf's
    `reserved_qty` by the encounter's `quantity`, advancing the shelf's `version`
    by 1, and restoring `available_qty` to its pre-reservation value — while
    `stock_posture` stays exactly as it was, because `on_hand_qty` never moved."

    Design: Difficulty/non_linear_state_machine/encounter_parallel_clinical_and_financial_dimensions_evolve_independently
    """
    practice = build_practice(api)
    encounter_id = practice.reserved_encounter()

    practice.fit(
        encounter_id,
        start_at="2026-08-01T09:00:00Z",
        end_at="2026-08-01T09:30:00Z",
        outcome="REJECTED",
    )
    assert_encounter_states(
        read_encounter(api, encounter_id), clinical_status="DOCUMENTED", financial_status="VERIFIED"
    )
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=10,
        reserved_qty=0,
        available_qty=10,
        stock_posture="OK",
    )

    practice.reserve(encounter_id)
    practice.fit(
        encounter_id,
        start_at="2026-08-01T10:00:00Z",
        end_at="2026-08-01T10:30:00Z",
        outcome="ACCEPTABLE",
    )

    assert_encounter_states(
        read_encounter(api, encounter_id), clinical_status="FITTED", financial_status="VERIFIED"
    )
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 60


def _fabricated_order(api):
    """A fabrication order delivered on its promised day, ready for inspection."""
    practice = build_practice(
        api, product_factory=f.custom_afo_product_payload, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    order = practice.place_fab_order(encounter_id)
    practice.fabrication_event(order["id"], "ACCEPT_ORDER")
    practice.fabrication_event(order["id"], "DELIVER_TO_CLINIC")
    return practice, encounter_id, order["id"]


def test_two_rework_rounds_cycle_the_order_back_to_ready_for_fitting(api):
    """The rework cycle from adjustment through fabrication back to ready may run
    twice, and each pass raises the recorded round count.

    PRD: "`REQUEST_ADJUSTMENT` moves `READY_FOR_FITTING → ADJUSTMENT_REQUESTED` and
    increases `adjustment_rounds` by 1; rework is capped at two rounds, and a
    request made when `adjustment_rounds` has already reached 2 is refused with
    `ERR_ADJUSTMENT_LIMIT_REACHED` and HTTP 422, so the cycle from
    `ADJUSTMENT_REQUESTED` through `IN_FABRICATION` back to `READY_FOR_FITTING` may
    repeat at most twice."

    Design: Difficulty/non_linear_state_machine/custom_fab_order_adjustment_cycle_third_request_rejected
    """
    practice, _encounter_id, order_id = _fabricated_order(api)

    first = practice.fitting_check(order_id, "REQUEST_ADJUSTMENT", note="medial trimline rubs")
    assert first["status"] == "ADJUSTMENT_REQUESTED"
    assert first["adjustment_rounds"] == 1

    resumed = practice.fabrication_event(order_id, "ACCEPT_ORDER")
    assert resumed["status"] == "IN_FABRICATION"
    practice.fabrication_event(order_id, "DELIVER_TO_CLINIC")

    second = practice.fitting_check(order_id, "REQUEST_ADJUSTMENT", note="strap alignment")
    assert second["status"] == "ADJUSTMENT_REQUESTED"
    assert second["adjustment_rounds"] == 2

    practice.fabrication_event(order_id, "ACCEPT_ORDER")
    ready = practice.fabrication_event(order_id, "DELIVER_TO_CLINIC")
    assert ready["status"] == "READY_FOR_FITTING"
    assert ready["adjustment_rounds"] == 2


def test_third_rework_request_is_refused_and_leaves_the_order_untouched(api):
    """Once two rounds have been recorded a third request is refused and the order
    stays ready for fitting with its round count and its projected score intact.

    PRD: "`REQUEST_ADJUSTMENT` moves `READY_FOR_FITTING → ADJUSTMENT_REQUESTED` and
    increases `adjustment_rounds` by 1; rework is capped at two rounds, and a
    request made when `adjustment_rounds` has already reached 2 is refused with
    `ERR_ADJUSTMENT_LIMIT_REACHED` and HTTP 422, so the cycle from
    `ADJUSTMENT_REQUESTED` through `IN_FABRICATION` back to `READY_FOR_FITTING` may
    repeat at most twice."

    Design: Difficulty/non_linear_state_machine/custom_fab_order_adjustment_cycle_third_request_rejected
    """
    practice, _encounter_id, order_id = _fabricated_order(api)
    for note in ("medial trimline rubs", "strap alignment"):
        practice.fitting_check(order_id, "REQUEST_ADJUSTMENT", note=note)
        practice.fabrication_event(order_id, "ACCEPT_ORDER")
        practice.fabrication_event(order_id, "DELIVER_TO_CLINIC")

    response = api.fitting_check(
        order_id,
        f.fitting_check_payload("REQUEST_ADJUSTMENT", note="third attempt"),
        practice.fitter_headers,
    )

    assert_error(response, ApiErrors.ADJUSTMENT_LIMIT_REACHED, 422)
    order = read_fab_order(api, order_id)
    assert order["status"] == "READY_FOR_FITTING"
    assert order["adjustment_rounds"] == 2
    assert order["first_delivery_days"] == 0
    assert order["projected_turnaround_score"] == 100


def test_sellable_return_restocks_and_then_closes_on_a_refit(api):
    """The sellable branch of a return restocks the shelf and, once a different
    fitter issues the refit, closes at the terminal refit state with a fresh
    documented encounter carrying the note forward.

    PRD: "On success the server creates a **new** `DispenseEncounter` for the same
    `clinic_id`, `patient_id`, `product_id`, `ordering_physician_id` and
    `quantity`, sets that new encounter's `refit_of_encounter_id` to the returned
    encounter, and copies `mn_diagnosis_code`, `mn_functional_deficit`,
    `mn_expected_duration_months` and `mn_signed_at` forward so the physician need
    not re-document — the new encounter therefore opens at `clinical_status`
    `DOCUMENTED` rather than `DRAFT`, while its `financial_status` starts fresh at
    `UNVERIFIED` because coverage must be re-verified."

    Design: Difficulty/non_linear_state_machine/product_return_fork_restocked_or_destroyed_then_join_refit_issued
    """
    practice = build_practice(api)
    second_fitter = add_fitter(practice, full_name="Mira Selk")
    encounter_id = practice.delivered_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    opened = practice.open_return(encounter_id, reason="POOR_FIT")
    inspected = practice.inspect_return(opened["id"], condition="SELLABLE")
    assert inspected["status"] == "RESTOCKED"

    refit = validate_success(
        api.issue_refit(opened["id"], {}, make_dme_fitter_headers(second_fitter["id"])), 201
    )

    assert refit["refit_of_encounter_id"] == encounter_id
    assert_encounter_states(refit, clinical_status="DOCUMENTED", financial_status="UNVERIFIED")
    assert refit["mn_diagnosis_code"] == "M54.50"
    closed = validate_success(api.list_returns(encounter_id, practice_admin_headers()), 200)
    assert closed[0]["status"] == "REFIT_ISSUED"
    assert closed[0]["refit_encounter_id"] == refit["id"]


def test_destroyed_return_reaches_the_same_terminal_refit_state(api):
    """The destroyed branch is not a dead end: a refit may be issued from it too,
    so both forks of the return converge on the same terminal state.

    PRD: "A `DmeFitter` may issue a refit from either `RESTOCKED` or `DESTROYED` —
    both converge on `REFIT_ISSUED`, which is terminal — and the operation takes no
    request body at all."

    Design: Difficulty/non_linear_state_machine/product_return_fork_restocked_or_destroyed_then_join_refit_issued
    """
    practice = build_practice(api)
    second_fitter = add_fitter(practice, full_name="Mira Selk")
    encounter_id = practice.delivered_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    opened = practice.open_return(encounter_id, reason="POOR_FIT")
    inspected = practice.inspect_return(opened["id"], condition="DAMAGED")
    assert inspected["status"] == "DESTROYED"
    assert inspected["restock_eligible"] is False

    refit = validate_success(
        api.issue_refit(opened["id"], {}, make_dme_fitter_headers(second_fitter["id"])), 201
    )

    assert refit["refit_of_encounter_id"] == encounter_id
    assert_encounter_states(refit, clinical_status="DOCUMENTED", financial_status="UNVERIFIED")
    assert_shelf(read_shelf(api, practice.par_level_id), on_hand_qty=9)
