"""The readiness assessment's deterministic gap synthesis, the remediation lifecycle,
and the three-step remediation debt that drives the engagement posture."""

from test_helpers import (
    CLOCK_DEFAULT,
    TEST_USERS,
    ApiErrorId,
    assert_debt_decomposition,
    assert_gap,
    assert_gap_debt_points_match_status,
    create_control,
    create_criterion,
    create_engagement,
    create_manual_gap,
    lead_engagement_action,
    make_auditor_headers,
    plan_gap,
    read_engagement,
    read_readiness_summary,
    remediate_gap,
    reopen_gap,
    run_readiness_assessment,
    setup_approved_locked_description,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_gap,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]


def test_debt_tier_one_ends_at_a_base_of_exactly_ten(api):
    """PRD 3.5: "Second, the tier is selected **from the pre-surcharge base and never from
    the total it will later be added to**. A base of 10 or less draws a rate of 0 percent;
    a base from 11 through 25 inclusive draws 15 percent; a base of 26 or more draws 30
    percent."
    PRD 3.5: "Third, the surcharge is the base multiplied by that rate, rounded half up to
    two decimal places, and `gap_debt_points` is the base plus the surcharge, rounded half
    up to two decimal places."
    PRD 2.8: "The comparisons are inclusive at the boundary: a debt of exactly 11.00 is
    restricted and a debt of exactly 26.00 is frozen."

    Design: Corner/calculations/corner_gap_debt_tier_one_boundary_at_base_ten_adds_no_surcharge
    """
    engagement = create_engagement(client_name="Tier Edge")
    create_manual_gap(engagement["id"], severity="HIGH", description="Access review gap")
    create_manual_gap(engagement["id"], severity="LOW", description="Asset tagging")
    create_manual_gap(engagement["id"], severity="LOW", description="Runbook stale")

    at_ten = read_readiness_summary(engagement["id"])
    assert at_ten["base_debt_points"] == 10
    assert at_ten["surcharge_points"] == 0.00, "A base of exactly 10 draws the zero rate"
    assert at_ten["gap_debt_points"] == 10.00
    assert at_ten["gap_posture"] == "OPEN"
    assert_debt_decomposition(at_ten)

    create_manual_gap(engagement["id"], severity="LOW", description="Training log incomplete")

    at_eleven = read_readiness_summary(engagement["id"])
    assert at_eleven["base_debt_points"] == 11
    assert at_eleven["surcharge_points"] == 1.65, "11 at 15 percent is a 1.65 surcharge"
    assert at_eleven["gap_debt_points"] == 12.65
    assert at_eleven["gap_posture"] == "RESTRICTED"
    assert_debt_decomposition(at_eleven)


def test_readiness_assessment_run_twice_does_not_duplicate_its_gaps(api):
    """PRD 3.5: "The pass skips a control entirely when a gap already exists with `source`
    `READINESS_ASSESSMENT`, that same `control_id`, and a status other than `VERIFIED` or
    `WITHDRAWN`."
    PRD 3.5: "**The first pass walks the engagement's controls whose `in_scope` is true, in
    ascending `control_ref` order.** A control with a `primary_mapping_count` of 0 yields a
    gap of severity `HIGH`."
    PRD 3.5: "An uncovered criterion yields a gap of severity `HIGH` when its `category` is
    `SECURITY` and severity `MODERATE` for every other category."
    PRD 3.5: "The assessment takes no payload, is permitted while the engagement is in the
    `READINESS` phase, synthesises a deterministic set of gaps, stamps
    `readiness_assessed_at` with the logical clock, recomputes `base_debt_points`,
    `gap_debt_points` and `gap_posture`, and increments the engagement's `version`."

    Design: Corner/calculations/corner_readiness_assessment_is_idempotent_across_two_runs
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Twice")
    setup_approved_locked_description(engagement["id"])
    control = create_control(
        engagement["id"],
        control_ref="U-01",
        title="Unmapped control",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=10,
    )
    lead_engagement_action(engagement["id"], "START_READINESS")

    first_run = run_readiness_assessment(engagement["id"])
    assert first_run["gap_debt_points"] == 18.40, (
        f"Two HIGH gaps give base 16 and total 18.40, got {first_run['gap_debt_points']}"
    )

    second_run = run_readiness_assessment(engagement["id"])
    assert second_run["gap_debt_points"] == 18.40, (
        "The idempotence guard must stop the second run from doubling the ledger"
    )

    gaps, meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={"engagement_id": engagement["id"], "source": "READINESS_ASSESSMENT"},
        )
    )
    assert meta["total_count"] == 2, f"Expected exactly 2 synthesised gaps, got {meta['total_count']}"

    control_anchored = [g for g in gaps if g["control_id"] == control["id"]]
    criterion_anchored = [g for g in gaps if g["trust_criterion_id"] == criterion["id"]]
    assert len(control_anchored) == 1
    assert control_anchored[0]["trust_criterion_id"] is None
    assert control_anchored[0]["severity"] == "HIGH"
    assert len(criterion_anchored) == 1
    assert criterion_anchored[0]["control_id"] is None
    assert criterion_anchored[0]["severity"] == "HIGH"

    after = read_engagement(engagement["id"])
    assert after["base_debt_points"] == 16
    assert after["gap_posture"] == "RESTRICTED"
    assert after["readiness_assessed_at"] == CLOCK_DEFAULT


def test_verify_is_not_an_edge_out_of_open(api):
    """PRD 3.5: "An `Auditor` then moves `REMEDIATED → VERIFIED`, and here segregation of
    duties bites: the acting `X-User-ID` must differ from the gap's
    `remediation_owner_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD 2.7: "The supplied `action`, `disposition` or `method` value is an outgoing edge
    from the row's current state, else `ERR_TRANSITION_NOT_ALLOWED` (409)."

    Design: Corner/state_machines/corner_gap_verify_from_open_rejected
    """
    engagement = create_engagement(client_name="Gap Flow")
    gap = create_manual_gap(
        engagement["id"], severity="MODERATE", description="Policy not ratified"
    )

    response = api.transition_gap(gap["id"], {"action": "VERIFY"}, AUD_HEADERS)
    assert response.status_code == 409, (
        f"VERIFY out of OPEN must be refused with 409, got {response.status_code}"
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )

    stored = validate_success(api.get_gap(gap["id"], CL_HEADERS))
    assert_gap(stored)
    assert stored["status"] == "OPEN"
    assert stored["debt_points"] == 3
    assert_gap_debt_points_match_status(stored)
    assert read_engagement(engagement["id"])["gap_debt_points"] == 3.00


def test_remediation_owner_may_not_verify_their_own_remediation(api):
    """PRD 3.5: "An `Auditor` then moves `REMEDIATED → VERIFIED`, and here segregation of
    duties bites: the acting `X-User-ID` must differ from the gap's
    `remediation_owner_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.5: "Verification leaves `debt_points` at 0."

    Design: Corner/validations/corner_gap_verify_by_its_own_remediation_owner_rejected
    """
    engagement = create_engagement(client_name="Self Verify")
    gap = create_manual_gap(
        engagement["id"], severity="HIGH", description="Privileged access not reviewed"
    )
    plan_gap(gap["id"], "own-7", "2026-10-01T00:00:00.000Z")
    remediate_gap(gap["id"])

    self_verify = api.transition_gap(
        gap["id"], {"action": "VERIFY"}, make_auditor_headers("own-7")
    )
    validate_error(self_verify, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    verified = validate_success(
        api.transition_gap(gap["id"], {"action": "VERIFY"}, make_auditor_headers("aud-1"))
    )
    assert verified["status"] == "VERIFIED"
    assert verified["remediation_owner_user_id"] == "own-7"
    assert verified["debt_points"] == 0

    after = read_engagement(engagement["id"])
    assert after["gap_debt_points"] == 0.00
    assert after["gap_posture"] == "OPEN"


def build_base_twenty_five_ledger():
    """Five OPEN manual gaps - HIGH, HIGH, MODERATE, MODERATE, MODERATE - summing to a
    pre-surcharge base of exactly 25."""
    engagement = create_engagement(client_name="Fabrikam")
    gaps = [
        create_manual_gap(engagement["id"], "HIGH", "Access review evidence not retained"),
        create_manual_gap(engagement["id"], "HIGH", "No formal change approval"),
        create_manual_gap(engagement["id"], "MODERATE", "Backup restore untested"),
        create_manual_gap(engagement["id"], "MODERATE", "Vendor review overdue"),
        create_manual_gap(engagement["id"], "MODERATE", "Asset inventory stale"),
    ]
    return engagement, gaps


def test_surcharge_reads_the_tier_off_the_pre_surcharge_base(api):
    """PRD 3.5: "First, the base: sum the severity point value of every gap of the
    engagement whose `status` is `OPEN`, `PLANNED` or `REOPENED`. A `LOW` gap is worth 1
    point, a `MODERATE` gap 3, a `HIGH` gap 8 and a `CRITICAL` gap 20."
    PRD 3.5: "Second, the tier is selected **from the pre-surcharge base and never from the
    total it will later be added to**. A base of 10 or less draws a rate of 0 percent; a
    base from 11 through 25 inclusive draws 15 percent; a base of 26 or more draws 30
    percent."
    PRD 3.5: "The tier is never re-selected from the post-surcharge total."

    Design: Difficulty/combinatorial_formula/gap_debt_tier_selected_from_pre_surcharge_base
    """
    engagement, _ = build_base_twenty_five_ledger()

    summary = validate_success(api.get_readiness_summary(engagement["id"], CL_HEADERS))
    assert summary["base_debt_points"] == 25
    assert summary["surcharge_points"] == 3.75, (
        "25 sits in the 15 percent tier, giving a 3.75 surcharge"
    )
    assert summary["gap_debt_points"] == 28.75, (
        "Re-selecting the tier from the 28.75 total would wrongly give 32.50, "
        f"got {summary['gap_debt_points']}"
    )
    assert_debt_decomposition(summary)


def test_a_base_of_twenty_five_still_freezes_the_engagement(api):
    """PRD 2.8: "The engagement is `FROZEN` when any of the following holds: at least one
    gap of the engagement has severity `CRITICAL` and a status of either `OPEN` or
    `REOPENED`; or `gap_debt_points` is 26.00 or more; or `open_exception_count` is 3 or
    more."
    PRD 3.5: "The readiness summary read exposes this decomposition directly, returning the
    surcharge as `surcharge_points` alongside `base_debt_points` and `gap_debt_points`."

    Design: Difficulty/combinatorial_formula/gap_debt_tier_selected_from_pre_surcharge_base
    """
    engagement, gaps = build_base_twenty_five_ledger()

    summary = validate_success(api.get_readiness_summary(engagement["id"], CL_HEADERS))
    assert summary["gap_posture"] == "FROZEN", (
        "28.75 clears the 26.00 frozen threshold even though the base is only 25"
    )

    row = read_engagement(engagement["id"])
    assert row["gap_debt_points"] == 28.75
    assert row["gap_posture"] == "FROZEN"

    high = validate_success(api.get_gap(gaps[0]["id"], CL_HEADERS))
    moderate = validate_success(api.get_gap(gaps[2]["id"], CL_HEADERS))
    assert high["debt_points"] == 8
    assert moderate["debt_points"] == 3


def build_verified_high_gap_ledger():
    """One HIGH gap taken through PLAN, REMEDIATE and VERIFY, plus two live LOW gaps,
    leaving a base of 2 and a debt of 2.00."""
    engagement = create_engagement(client_name="Dogwood")
    high = create_manual_gap(engagement["id"], "HIGH", "Privileged access not reviewed")
    low_one = create_manual_gap(engagement["id"], "LOW", "Asset tagging incomplete")
    low_two = create_manual_gap(engagement["id"], "LOW", "Runbook out of date")
    plan_gap(high["id"], "own-7", "2026-10-01T00:00:00.000Z")
    remediate_gap(high["id"])
    verify_gap(high["id"])
    return engagement, high, low_one, low_two


def test_reopening_a_verified_gap_restores_its_severity_points(api):
    """PRD 3.5: "An `Auditor` may push a verified gap back with `VERIFIED → REOPENED` so
    long as the engagement has not reached `ISSUED`; reopening increments `reopen_count` by
    one, restores `debt_points` to the severity's point value, and recomputes the
    engagement's debt and posture along with the control's `open_gap_count`."

    Design: Difficulty/compensating_invariant/gap_reopen_then_reremediate_conserves_engagement_debt_points
    """
    engagement, high, _, _ = build_verified_high_gap_ledger()

    before = read_readiness_summary(engagement["id"])
    assert before["base_debt_points"] == 2
    assert before["gap_debt_points"] == 2.00

    reopened = reopen_gap(high["id"], reason="Regression found in Q4 sample")
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["debt_points"] == 8, (
        f"Reopening restores the HIGH gap's 8 points, got {reopened['debt_points']}"
    )

    middle = read_readiness_summary(engagement["id"])
    assert middle["base_debt_points"] == 10
    assert middle["gap_debt_points"] == 10.00


def test_a_second_remediation_cycle_returns_the_debt_to_its_prior_total(api):
    """PRD 3.5: "The same lead moves `PLANNED → REMEDIATED`, which sets `debt_points` to 0,
    recomputes the engagement's `base_debt_points`, `gap_debt_points` and `gap_posture`,
    and recomputes the control's `open_gap_count` when the gap names a control."
    PRD 3.5: "`VERIFIED → REOPENED → PLANNED → REMEDIATED → VERIFIED` is the full
    remediation cycle and may be traversed as often as the examination demands."

    Design: Difficulty/compensating_invariant/gap_reopen_then_reremediate_conserves_engagement_debt_points
    """
    engagement, high, low_one, low_two = build_verified_high_gap_ledger()

    reopen_gap(high["id"], reason="Regression found in Q4 sample")
    plan_gap(high["id"], "own-7", "2026-11-01T00:00:00.000Z")
    remediate_gap(high["id"])
    verify_gap(high["id"])

    after = read_readiness_summary(engagement["id"])
    assert after["base_debt_points"] == 2, (
        f"The second cycle must return the base to exactly 2, got {after['base_debt_points']}"
    )
    assert after["gap_debt_points"] == 2.00
    assert after["gap_posture"] == "OPEN"

    high_after = validate_success(api.get_gap(high["id"], CL_HEADERS))
    assert high_after["status"] == "VERIFIED"
    assert high_after["reopen_count"] == 1, "reopen_count settles at 1, not 0 and not 2"
    assert high_after["debt_points"] == 0

    for low in (low_one, low_two):
        stored = validate_success(api.get_gap(low["id"], CL_HEADERS))
        assert stored["debt_points"] == 1, "Each untouched LOW gap still carries 1 point"
