"""Non-linear state machines: resources that revisit states or carry two axes.

Covers the patient order's parallel clinical and billing dimensions, and the
build item's reject / rework revision cycle.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_patient_order_payload,
    create_test_scenario_payload,
    get_success_data,
    get_build_item,
    setup_program_and_facility,
    setup_program_facility_department,
    create_item_in_testing,
    BUILD_ANALYST,
    TEST_LEAD,
    CONVERSION,
    RECONCILER,
    REVENUE,
    ANALYST,
)


# ===========================================================================
# r3_patient_order_parallel_dimensions_advance_independently
# ===========================================================================

def test_posting_the_charge_advances_billing_without_touching_clinical(api, conversion_headers, revenue_headers, reconciler_headers):
    """PRD §3.7: "A patient order carries two independent state dimensions that
    advance on the same row: its clinical state, whose vocabulary is
    `CONVERTED`, `RECONCILED` and `PAPER_BACKFILL_REQUIRED`, and its billing
    state, whose vocabulary is `UNPOSTED`, `CHARGE_POSTED`, `CLAIM_SUBMITTED`,
    `CLAIM_ACCEPTED`, `CLAIM_DENIED` and `CLAIM_PAID`."
    PRD §3.7: "posting is admissible while the order's clinical state is
    `CONVERTED` or `RECONCILED`".

    Posting then reconciling moves one axis at a time: after post-charge the
    billing state is CHARGE_POSTED while the clinical state is still CONVERTED.

    Design: Difficulty/non_linear_state_machine/r3_patient_order_parallel_dimensions_advance_independently
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-5001", order_type="MEDICATION",
            encounter_utc="2026-08-25T00:00:00Z", legacy_charge_cents=25000,
        ),
        conversion_headers,
    ))

    charged = validate_success(api.post_charge(order["id"], revenue_headers), 200)
    assert charged["billing_state"] == "CHARGE_POSTED"
    assert charged["clinical_state"] == "CONVERTED", (
        "posting the charge must not move the clinical dimension"
    )

    reconciled = validate_success(api.reconcile_order(order["id"], reconciler_headers), 200)
    assert reconciled["clinical_state"] == "RECONCILED"
    assert reconciled["billing_state"] == "CHARGE_POSTED", (
        "reconciling must not move the billing dimension"
    )


def test_a_claim_denial_leaves_the_clinical_dimension_reconciled(api, conversion_headers, revenue_headers, reconciler_headers):
    """PRD §3.8: "A charge may be submitted as a claim once the order is in
    billing state `CHARGE_POSTED` and its clinical state is `RECONCILED`".
    PRD §3.8: "An acceptance moves a submitted claim to `CLAIM_ACCEPTED`, a
    denial moves it to `CLAIM_DENIED`, and a payment moves an accepted claim to
    `CLAIM_PAID`, which is terminal."

    The billing axis walks UNPOSTED -> CHARGE_POSTED -> CLAIM_SUBMITTED ->
    CLAIM_DENIED while the clinical axis stays parked at RECONCILED, producing a
    pair a single-axis machine could not represent.

    Design: Difficulty/non_linear_state_machine/r3_patient_order_parallel_dimensions_advance_independently
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-5001", order_type="MEDICATION",
            encounter_utc="2026-08-25T00:00:00Z", legacy_charge_cents=25000,
        ),
        conversion_headers,
    ))
    get_success_data(api_client.post_charge(order["id"], revenue_headers))
    get_success_data(api_client.reconcile_order(order["id"], reconciler_headers))

    submitted = validate_success(api.submit_claim(order["id"], revenue_headers), 200)
    assert submitted["billing_state"] == "CLAIM_SUBMITTED"
    assert submitted["clinical_state"] == "RECONCILED"

    denied = validate_success(
        api.record_claim_response(order["id"], {"claim_response": "DENIED"}, revenue_headers), 200
    )
    assert denied["billing_state"] == "CLAIM_DENIED"
    assert denied["clinical_state"] == "RECONCILED", (
        "a denial moves only the billing dimension; the clinical state is untouched"
    )


# ===========================================================================
# r3_build_item_reject_then_rework_cycle_closes
# ===========================================================================

def test_failing_scenario_rejects_the_item_and_counts_the_rejection(api, build_analyst_headers, test_lead_headers):
    """PRD §3.3: "Any test scenario of the item that transitions into `FAILED`
    pushes the item from `IN_TESTING` into `BUILD_REJECTED`, and each such
    rejection increments `rejection_count` by one".
    PRD §3.5: "a failing outcome moves the scenario to `FAILED`, records the
    epoch, and pushes the owning build item from `IN_TESTING` into
    `BUILD_REJECTED` on the spot."

    Design: Difficulty/non_linear_state_machine/r3_build_item_reject_then_rework_cycle_closes
    """
    prog, fac, dept = setup_program_facility_department()
    item = create_item_in_testing(dept["id"])
    assert item["status"] == "IN_TESTING", "the item entered testing as IN_TESTING"
    scenario = get_success_data(api_client.create_test_scenario(
        item["id"], create_test_scenario_payload(), test_lead_headers
    ))

    validate_success(
        api.execute_scenario(scenario["id"], {"outcome": "FAIL", "executed_epoch": 0}, test_lead_headers),
        200,
    )

    after = get_build_item(item["id"], test_lead_headers)
    assert after["status"] == "BUILD_REJECTED"
    assert after["rejection_count"] == 1


def test_a_rejected_item_can_be_reworked_and_re_enter_testing_without_a_second_rejection(api, build_analyst_headers, test_lead_headers):
    """PRD §3.3: "From `BUILD_REJECTED` the item may be reworked back to
    `IN_BUILD` — permitted while `rejection_count` is at most 3".
    PRD §3.3: "Moving into testing requires only `BUILD_COMPLETE`".

    After the rework the item is IN_BUILD; re-completing the build and re-entering
    testing returns it to IN_TESTING with rejection_count still 1, closing the
    cycle a strictly linear pipeline could never revisit.

    Design: Difficulty/non_linear_state_machine/r3_build_item_reject_then_rework_cycle_closes
    """
    prog, fac, dept = setup_program_facility_department()
    item = create_item_in_testing(dept["id"])
    scenario = get_success_data(api_client.create_test_scenario(
        item["id"], create_test_scenario_payload(), test_lead_headers
    ))
    get_success_data(api_client.execute_scenario(
        scenario["id"], {"outcome": "FAIL", "executed_epoch": 0}, test_lead_headers
    ))

    reworked = validate_success(api.rework_build_item(item["id"], build_analyst_headers), 200)
    assert reworked["status"] == "IN_BUILD"

    get_success_data(api.complete_build_item(item["id"], build_analyst_headers))
    back = validate_success(api.start_testing(item["id"], test_lead_headers), 200)
    assert back["status"] == "IN_TESTING", "the cycle closed back at IN_TESTING"
    assert back["rejection_count"] == 1, "no second rejection was recorded"