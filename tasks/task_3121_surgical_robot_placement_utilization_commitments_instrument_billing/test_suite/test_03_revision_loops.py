"""Cyclic revision loops: a readiness review re-entering PENDING_REVIEW, and a placement
agreement traversing the whole activation path and returning to DRAFT."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_configuration,
    create_review,
    get_success_data,
    reject_review,
    return_review_to_review,
    set_clock,
    setup_commissioned_system,
    submit_agreement,
    submit_verdict,
    validate_success,
)


def test_rejected_review_returns_to_pending_review_and_advances_the_round(api):
    """PRD §2.6: "Returning a rejected review to review requires the review to be `REJECTED`
    (`ERR_READINESS_REVIEW_NOT_REJECTED`, HTTP 409, checked first) and increments `review_round`
    by one, recomputes `conditional_clearance_count` against the evaluated configuration, and
    recomputes the posture."

    Design: Difficulty/non_linear_state_machine/readiness_review_rejected_pending_revision_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(account_name="Birch Run Surgical", idn_group_code="IDN-BIRCH",
                             region_code="EAST", placement_cap=3,
                             maximum_procedure_commitment=20)
    config = create_configuration(model_code="DA_V2", base_placement_fee_cents=6000000,
                                  max_instrument_lives=12, integration_tier=2)
    review = create_review(account["id"], config["id"])
    assert review["readiness_status"] == "PENDING_REVIEW"
    assert review["review_round"] == 1

    rejected = reject_review(review, "Widen the door to 120 cm before re-measure.")
    assert rejected["readiness_status"] == "REJECTED"

    looped = return_review_to_review(rejected, "Door widened.")

    assert looped["readiness_status"] == "PENDING_REVIEW", (
        "the same row re-enters the state it was created in"
    )
    assert looped["review_round"] == 2, "the revision round advances by one"


def test_revised_review_passes_with_the_advanced_round_intact(api):
    """PRD §2.6: "A clean pass requires every dimension and the throw radius to meet or
    exceed the configuration's minimums and requires the conditional clearance count to be
    zero".

    Design: Difficulty/non_linear_state_machine/readiness_review_rejected_pending_revision_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(account_name="Birch Run Surgical", idn_group_code="IDN-BIRCH",
                             region_code="EAST", placement_cap=3,
                             maximum_procedure_commitment=20)
    config = create_configuration(model_code="DA_V2", base_placement_fee_cents=6000000,
                                  max_instrument_lives=12, integration_tier=2)
    review = create_review(account["id"], config["id"])
    review = reject_review(review)
    review = return_review_to_review(review)
    assert review["review_round"] == 2

    passed = submit_verdict(review, "PASSED")

    assert passed["readiness_status"] == "PASSED"
    assert passed["review_round"] == 2, "the revision history stays legible through the pass"


def test_active_agreement_rejected_back_to_draft_clears_its_activation_stamps(api):
    """PRD §3.1.3: "A `HospitalProcurementOfficer` may reject an agreement in `DRAFT`,
    `PENDING_ACCEPTANCE` or `ACTIVE`, returning it to `DRAFT`; a rejection from
    `PENDING_ACCEPTANCE` also clears `acceptance_expires_utc`, and a rejection from
    `ACTIVE` clears both `cycle_start_utc` and `activated_at_utc` back to null."

    Design: Difficulty/non_linear_state_machine/agreement_draft_pending_active_reject_revision_loop
    """
    ctx = setup_commissioned_system()

    backed_out = validate_success(api_client.reject_agreement(
        ctx.agreement["id"],
        {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    assert backed_out["agreement_status"] == "DRAFT", (
        "an agreement that was ACTIVE returns to DRAFT"
    )
    assert backed_out["cycle_start_utc"] is None
    assert backed_out["activated_at_utc"] is None


def test_the_system_minted_at_activation_survives_the_agreement_rejection(api):
    """PRD §3.1.3: "On success the agreement moves to `ACTIVE`; `activated_at_utc` and
    `cycle_start_utc` are stamped from the logical clock; and `cycle_end_utc` becomes
    `cycle_start_utc` plus `interval_months` multiplied by 30 days."
    PRD §3.1.3: "A `RobotSystem` is synthesized in `service_status` `NOT_INSTALLED`,
    serial-numbered from the agreement, and its identifier is recorded on the agreement as
    `synthesized_system_id` with `synthesized_system_version` always 1 immediately after synthesis."

    Design: Difficulty/non_linear_state_machine/agreement_draft_pending_active_reject_revision_loop
    """
    ctx = setup_commissioned_system()
    system_id = ctx.system["id"]
    validate_success(api_client.reject_agreement(
        ctx.agreement["id"],
        {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    system = get_success_data(api_client.get_robot_system(system_id, TEST_USERS["platform_admin_headers"]))

    assert system["id"] == system_id, "the synthesized system still exists after the rejection"
    assert system["placement_agreement_id"] == ctx.agreement["id"]


def test_the_same_agreement_row_re_enters_pending_acceptance_after_being_backed_out(api):
    """PRD §3.1.2: "Submitting the agreement moves it to `PENDING_ACCEPTANCE` and computes
    its placement fee".

    Design: Difficulty/non_linear_state_machine/agreement_draft_pending_active_reject_revision_loop
    """
    ctx = setup_commissioned_system()
    backed_out = validate_success(api_client.reject_agreement(
        ctx.agreement["id"],
        {"expected_agreement_version": ctx.agreement["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    assert backed_out["agreement_status"] == "DRAFT"

    resubmitted = submit_agreement(backed_out)

    assert resubmitted["id"] == ctx.agreement["id"], "the same row re-enters the loop"
    assert resubmitted["agreement_status"] == "PENDING_ACCEPTANCE"