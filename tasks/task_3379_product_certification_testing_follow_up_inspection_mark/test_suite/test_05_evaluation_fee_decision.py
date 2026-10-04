"""Evaluation readiness, the program-fee snapshot, and certification decisions.

Covers the sample-state dependency of the TESTING -> EVALUATION gate, the
per-line fee rounding order (including the DAMAGED multiplier and the SMALL
discount), the approval guard order (segregation of duties, safety-critical,
mandatory), terminal-state lockdown of decided projects, and the RETEST loop
with its surcharge.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    DEFAULT_ENGINEER_ID,
    DEFAULT_REVIEWER_ID,
    SECOND_REVIEWER_ID,
    add_calendar_months,
    assert_certification,
    assert_listing_number,
    canonical_instant,
    decide_project,
    decide_project_payload,
    get_certification_for_project,
    make_certification_reviewer_headers,
    record_result,
    refresh_project,
    reject_sample,
    setup_project_in_evaluation,
    setup_project_with_record,
    submit_and_accept_sample,
    submit_sample,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)


def test_rejected_sample_contributes_nothing_blocks_evaluation(api, reviewer_headers):
    """PRD §3.2: "Only samples in `ACCEPTED` or `TESTED` are eligible —
    `SUBMITTED` and `REJECTED` samples never contribute results."
    PRD §3.4: "Decisions are the exclusive province of a `CertificationReviewer`,
    and only while the project is `EVALUATION` — deciding at any other time is
    rejected with `ERR_PROJECT_NOT_EVALUABLE`."

    Design: Difficulty/cross_entity_state_dependency/project_evaluation_gate_depends_on_sample_states
    """
    ctx = setup_project_with_record(api)
    project = ctx["project"]
    sample = submit_sample(
        api, project["id"], ctx["manufacturer"]["id"], serial_no="S-1"
    )
    reject_sample(api, sample["id"], note="Cracked enclosure")

    project = refresh_project(api, project["id"])
    assert project["status"] == "STANDARD_SELECTED", (
        "a REJECTED sample never moves the project to TESTING"
    )
    response = api.decide_project(
        project["id"], decide_project_payload("APPROVED"), reviewer_headers
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_EVALUABLE)


def test_evaluation_gate_opens_with_accepted_sample_results(api, officer_headers):
    """PRD §3.2: "The readiness gate is satisfied when every `mandatory`
    protocol of the pinned standard has a latest outcome and exactly one
    `FROZEN` construction record exists for the project. When the gate becomes
    satisfied while the project is `TESTING`, the project advances automatically
    from `TESTING` to `EVALUATION`, and its `fee_snapshot_cents` is computed and
    stored at that moment."

    Design: Difficulty/cross_entity_state_dependency/project_evaluation_gate_depends_on_sample_states
    """
    ctx = setup_project_with_record(api)
    project = ctx["project"]
    mfr_id = ctx["manufacturer"]["id"]
    rejected = submit_sample(api, project["id"], mfr_id, serial_no="S-1")
    reject_sample(api, rejected["id"], note="Cracked enclosure")

    accepted = submit_and_accept_sample(api, project["id"], mfr_id, serial_no="S-2")
    record_result(api, accepted["id"], "P-SAFE", 60)
    record_result(api, accepted["id"], "P-TEMP", 110)

    project = refresh_project(api, project["id"])
    assert project["status"] == "EVALUATION"
    # Fee: P-SAFE 5000 + P-TEMP 10001 = 15001; SMALL discount x0.9 -> 13501.
    assert project["fee_snapshot_cents"] == 13501


def test_fee_snapshot_per_line_rounding_with_damaged_samples(api, officer_headers):
    """PRD §3.4: "Each line takes the protocol's `base_fee_cents`, multiplies it
    by 1.25 when the sample carrying that latest result is `DAMAGED` (an
    `INTACT` sample multiplies by one), and rounds the line half-up to whole
    cents before any summation."
    PRD §3.4: "A manufacturer whose `annual_revenue_tier` is `SMALL` then
    receives a ten percent discount — the subtotal multiplied by 0.9 and rounded
    half-up to whole cents; every other tier pays the subtotal unchanged."
    PRD §3.4: "The pinned rounding order matters: per-line rounding happens
    before summation, and summing unrounded lines first produces a different,
    incorrect fee."

    The optional P-MARK result is recorded before the second mandatory result,
    so at the instant the readiness gate fires all three protocols have a latest
    result and all three fee lines enter the snapshot: 5000 + 12501 + 12501 =
    30002, and round_half_up(30002 * 0.9) = 27002 (summing unrounded lines
    first would yield 27003).

    Design: Difficulty/combinatorial_formula/project_fee_per_line_rounding_order
    """
    ctx = setup_project_with_record(api)
    project = ctx["project"]
    mfr_id = ctx["manufacturer"]["id"]
    intact = submit_and_accept_sample(
        api, project["id"], mfr_id, serial_no="SI-1", condition="INTACT"
    )
    damaged = submit_and_accept_sample(
        api, project["id"], mfr_id, serial_no="SD-1", condition="DAMAGED"
    )
    # Optional protocol first: it has a latest result before the gate fires.
    record_result(api, damaged["id"], "P-MARK", 250)
    record_result(api, intact["id"], "P-SAFE", 60)
    record_result(api, damaged["id"], "P-TEMP", 110)

    project = refresh_project(api, project["id"])
    assert project["status"] == "EVALUATION"
    assert project["fee_snapshot_cents"] == 27002, (
        f"per-line rounding before summation must yield 27002, "
        f"got {project['fee_snapshot_cents']}"
    )


def test_fee_snapshot_per_line_rounding_without_small_discount(api, officer_headers):
    """PRD §3.4: "A manufacturer whose `annual_revenue_tier` is `SMALL` then
    receives a ten percent discount — the subtotal multiplied by 0.9 and rounded
    half-up to whole cents; every other tier pays the subtotal unchanged."
    PRD §3.4: "The pinned rounding order matters: per-line rounding happens
    before summation, and summing unrounded lines first produces a different,
    incorrect fee."

    Design: Difficulty/combinatorial_formula/project_fee_per_line_rounding_order
    """
    ctx = setup_project_with_record(
        api, manufacturer_overrides={"annual_revenue_tier": "STANDARD"}
    )
    project = ctx["project"]
    mfr_id = ctx["manufacturer"]["id"]
    intact = submit_and_accept_sample(
        api, project["id"], mfr_id, serial_no="SI-1", condition="INTACT"
    )
    damaged = submit_and_accept_sample(
        api, project["id"], mfr_id, serial_no="SD-1", condition="DAMAGED"
    )
    record_result(api, damaged["id"], "P-MARK", 250)
    record_result(api, intact["id"], "P-SAFE", 60)
    record_result(api, damaged["id"], "P-TEMP", 110)

    project = refresh_project(api, project["id"])
    assert project["status"] == "EVALUATION"
    # No SMALL discount: the snapshot is the rounded-line subtotal itself —
    # 30002, not the 30003 that summing unrounded lines first would produce.
    assert project["fee_snapshot_cents"] == 30002


def test_project_decide_approval_valid_transition_sets_all_fields(api, officer_headers):
    """PRD §3.4: "The server mints a `listing_number`: the letter E followed by
    a zero-padded six-digit sequence assigned in creation order."
    PRD §3.4: "`issued_on` is the logical time of approval. `expires_on` is
    `issued_on` plus the `validity_months` supplied with the decision, or null
    when no `validity_months` was supplied, meaning the certification never
    expires."
    PRD §3.4: "Whatever the outcome, the project records `decided_by` and
    `decided_on`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/state_machines/project_decide_approval_valid_transition_sets_all_fields
    """
    ctx = setup_project_in_evaluation(api)
    project = decide_project(
        api, ctx["project"]["id"], "APPROVED", validity_months=12
    )
    # Immediate consistency: the decide response itself is the updated project.
    assert project["status"] == "APPROVED"
    assert project["fee_snapshot_cents"] == 13501
    assert project["decided_by"] == DEFAULT_REVIEWER_ID
    assert canonical_instant(project["decided_on"]) == canonical_instant(BASE_CLOCK_ISO)

    certification = get_certification_for_project(api, ctx["project"]["id"])
    assert_certification(certification)
    assert certification["status"] == "ACTIVE"
    assert certification["construction_record_id"] == ctx["construction_record"]["id"]
    assert certification["construction_record_revision"] == 1
    assert_listing_number(certification["listing_number"])
    assert canonical_instant(certification["issued_on"]) == canonical_instant(
        BASE_CLOCK_ISO
    )
    assert canonical_instant(certification["expires_on"]) == canonical_instant(
        add_calendar_months(BASE_CLOCK_ISO, 12)
    )


def test_decide_on_rejected_project_returns_already_terminal(api, officer_headers):
    """PRD §2.8: "an entity already in a terminal state — `REJECTED`,
    `WITHDRAWN`, `EXPIRED`, `VOIDED`, `IMPLEMENTED`, or `EVALUATED_FAIL` —
    rejects all further transitions with `ERR_ALREADY_TERMINAL`"
    PRD §3.4: "only while the project is `EVALUATION` — deciding at any other
    time is rejected with `ERR_PROJECT_NOT_EVALUABLE`."

    Both stage-6 rules are verbatim in PRD and collide for a decision on a
    REJECTED project; PRD does not state intra-stage precedence between them,
    so either error is PRD-faithful (error-precedence silence).

    Design: Corner/state_machines/decide_on_rejected_project_returns_already_terminal
    """
    ctx = setup_project_in_evaluation(api)
    project = decide_project(api, ctx["project"]["id"], "REJECTED")
    assert project["status"] == "REJECTED"
    response = api.decide_project(
        ctx["project"]["id"],
        decide_project_payload("APPROVED"),
        make_certification_reviewer_headers(SECOND_REVIEWER_ID),
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_PROJECT_NOT_EVALUABLE],
    )
    project = refresh_project(api, ctx["project"]["id"])
    assert project["status"] == "REJECTED"


def test_segregation_of_duties_reviewer_who_recorded_results_cannot_decide(api):
    """PRD §3.4: "First, segregation of duties: the deciding reviewer's
    `X-User-ID` must differ from every `recorded_by` on every result of the
    project's samples — a reviewer who recorded any result on the project is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_reviewer_who_recorded_results_cannot_decide
    """
    ctx = setup_project_in_evaluation(api)  # results recorded by eng-1
    response = api.decide_project(
        ctx["project"]["id"],
        decide_project_payload("APPROVED", validity_months=12),
        make_certification_reviewer_headers(DEFAULT_ENGINEER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # The identical decide by a clean reviewer succeeds: SoD keys on X-User-ID.
    project = decide_project(
        api, ctx["project"]["id"], "APPROVED", validity_months=12
    )
    assert project["status"] == "APPROVED"


def test_mandatory_protocol_failing_returned_when_safety_passes(api, reviewer_headers):
    """PRD §3.4: "Third, every `mandatory` protocol's latest outcome must be
    `PASS` or `CONDITIONAL` (`ERR_MANDATORY_PROTOCOL_FAILING`)."

    Design: Corner/validations/mandatory_protocol_failing_returned_when_safety_passes
    """
    ctx = setup_project_in_evaluation(api, results=[("P-SAFE", 60), ("P-TEMP", 90)])
    response = api.decide_project(
        ctx["project"]["id"],
        decide_project_payload("APPROVED", validity_months=12),
        reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_MANDATORY_PROTOCOL_FAILING)
    project = refresh_project(api, ctx["project"]["id"])
    assert project["status"] == "EVALUATION", "a failed decide mutates nothing"


def test_safety_failure_wins_over_mandatory_failure(api, reviewer_headers, officer_headers):
    """PRD §3.4: "Approval is guarded by three checks, evaluated in this order.
    First, segregation of duties: the deciding reviewer's `X-User-ID` must
    differ from every `recorded_by` on every result of the project's samples —
    a reviewer who recorded any result on the project is rejected with
    `ERR_SEGREGATION_OF_DUTIES`. Second, every `safety_critical` protocol's
    latest outcome must be `PASS` (`ERR_SAFETY_PROTOCOL_NOT_PASSED`). Third,
    every `mandatory` protocol's latest outcome must be `PASS` or `CONDITIONAL`
    (`ERR_MANDATORY_PROTOCOL_FAILING`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_protocol_failure_wins_over_mandatory_constraint_failure
    """
    # P-SAFE 48 lands in the conditional band and converts to FAIL because the
    # protocol is safety-critical; P-TEMP 90 is an outright FAIL. Both the
    # safety gate and the mandatory gate are violated; the safety error wins.
    ctx = setup_project_in_evaluation(api, results=[("P-SAFE", 48), ("P-TEMP", 90)])
    project = refresh_project(api, ctx["project"]["id"])
    assert project["status"] == "EVALUATION"
    response = api.decide_project(
        ctx["project"]["id"],
        decide_project_payload("APPROVED", validity_months=12),
        reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_SAFETY_PROTOCOL_NOT_PASSED)
    certifications, _meta = validate_paginated(
        api.list_certifications(officer_headers, params={"project_id": ctx["project"]["id"]})
    )
    assert certifications == [], "no certification may be minted by a failed approval"


def test_failed_approval_leaves_project_evaluable(api, reviewer_headers):
    """PRD §3.4: "Second, every `safety_critical` protocol's latest outcome must
    be `PASS` (`ERR_SAFETY_PROTOCOL_NOT_PASSED`)."
    PRD §3.4: "A `RETEST` decision loops the project back from `EVALUATION` to
    `TESTING`, increments `retest_count` by 1, and clears `fee_snapshot_cents`
    to null"

    Design: Difficulty/priority_pair_validation_conflict/safety_protocol_failure_wins_over_mandatory_constraint_failure
    """
    ctx = setup_project_in_evaluation(api, results=[("P-SAFE", 48), ("P-TEMP", 90)])
    response = api.decide_project(
        ctx["project"]["id"],
        decide_project_payload("APPROVED", validity_months=12),
        reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_SAFETY_PROTOCOL_NOT_PASSED)
    project = refresh_project(api, ctx["project"]["id"])
    assert project["status"] == "EVALUATION", "a failed decide mutates nothing"
    # The project is still decidable: RETEST succeeds right after the failure.
    project = decide_project(api, ctx["project"]["id"], "RETEST")
    assert project["status"] == "TESTING"
    assert project["retest_count"] == 1


def test_retest_loop_increments_count_and_adds_surcharge(api):
    """PRD §3.4: "A `RETEST` decision loops the project back from `EVALUATION`
    to `TESTING`, increments `retest_count` by 1, and clears
    `fee_snapshot_cents` to null, so the fee is recomputed — now with the
    surcharge reflecting the additional retest — the next time the project
    reaches `EVALUATION`."
    PRD §3.4: "The retest surcharge is the after-discount amount multiplied by
    0.5 and by the project's `retest_count`, rounded half-up to whole cents."

    Design: Difficulty/non_linear_state_machine/project_retest_loop_increments_and_reapproves
    """
    ctx = setup_project_with_record(api)
    project = ctx["project"]
    mfr_id = ctx["manufacturer"]["id"]
    first = submit_and_accept_sample(api, project["id"], mfr_id, serial_no="S-1")
    record_result(api, first["id"], "P-SAFE", 60)
    record_result(api, first["id"], "P-TEMP", 90)  # FAIL -> gate still fires
    project = refresh_project(api, project["id"])
    assert project["status"] == "EVALUATION"
    # First snapshot: (5000 + 10001) * 0.9 rounded = 13501, no surcharge.
    assert project["fee_snapshot_cents"] == 13501

    project = decide_project(api, project["id"], "RETEST")
    assert project["status"] == "TESTING"
    assert project["retest_count"] == 1
    assert project["fee_snapshot_cents"] is None

    second = submit_and_accept_sample(api, project["id"], mfr_id, serial_no="S-2")
    record_result(api, second["id"], "P-TEMP", 115)
    project = refresh_project(api, project["id"])
    assert project["status"] == "EVALUATION"
    # Recomputed: 13501 + round_half_up(13501 * 0.5 * 1) = 13501 + 6751.
    assert project["fee_snapshot_cents"] == 20252


def test_retest_loop_reapproves_and_mints_certification(api, officer_headers):
    """PRD §3.4: "A `RETEST` decision loops the project back from `EVALUATION`
    to `TESTING`, increments `retest_count` by 1, and clears
    `fee_snapshot_cents` to null, so the fee is recomputed — now with the
    surcharge reflecting the additional retest — the next time the project
    reaches `EVALUATION`."
    PRD §3.4: "The server mints a `listing_number`: the letter E followed by a
    zero-padded six-digit sequence assigned in creation order."

    Design: Difficulty/non_linear_state_machine/project_retest_loop_increments_and_reapproves
    """
    ctx = setup_project_with_record(api)
    project = ctx["project"]
    mfr_id = ctx["manufacturer"]["id"]
    first = submit_and_accept_sample(api, project["id"], mfr_id, serial_no="S-1")
    record_result(api, first["id"], "P-SAFE", 60)
    record_result(api, first["id"], "P-TEMP", 90)
    decide_project(api, project["id"], "RETEST")
    second = submit_and_accept_sample(api, project["id"], mfr_id, serial_no="S-2")
    record_result(api, second["id"], "P-TEMP", 115)

    project = decide_project(api, project["id"], "APPROVED", validity_months=12)
    assert project["status"] == "APPROVED"
    assert project["retest_count"] == 1
    assert project["fee_snapshot_cents"] == 20252

    certification = get_certification_for_project(api, project["id"])
    assert_certification(certification)
    assert certification["status"] == "ACTIVE"
    assert_listing_number(certification["listing_number"])
