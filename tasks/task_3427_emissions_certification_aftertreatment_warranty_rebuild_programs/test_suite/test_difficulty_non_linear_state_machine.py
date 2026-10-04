"""Non-linear state machine tests (PRD §3.7 claim review cycle, §3.8 campaign
completion revert loop).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    assert_claim_financials_balance,
    assert_engine_unit,
    assert_field_campaign,
    assert_warranty_claim,
    complete_work_order,
    compute_completion_rate,
    get_family,
    request_info,
    resubmit_claim,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_claim_under_review,
    setup_engine_unit,
    setup_full_environment,
    stamp_family_non_conforming,
    start_work_order,
    validate_error,
    validate_success,
    verify_work_order,
)

CAMPAIGN_CLOCK = "2026-12-15T00:00:00Z"


# ---------------------------------------------------------------------------
# warranty claim bounded review cycle (UNDER_REVIEW <-> INFO_REQUESTED)
# ---------------------------------------------------------------------------
def _claim_after_two_full_info_rounds():
    """Claim on a clean unit (no maintenance records, no snapshots -> neglect
    score 0), taken through two complete request-info / resubmit rounds."""
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-501")
    set_logical_clock("2026-12-01T00:00:00Z")
    claim = setup_claim_under_review(
        unit, center, failed_component_class="ENGINE_BASE",
        failure_code="FC-cyc", claimed_amount_cents=40000,
    )
    request_info(claim["id"])
    resubmit_claim(claim["id"], unit=unit, note="service invoices attached")
    request_info(claim["id"])
    resubmit_claim(claim["id"], unit=unit, note="def dosing logs attached")
    return env, unit, claim


def test_third_request_info_rejected_when_review_rounds_exhausted(api, adjudicator_headers, admin_headers):
    """PRD §3.7: "From `UNDER_REVIEW` the adjudicator may request more information, moving the claim to `INFO_REQUESTED` and incrementing `review_round` — but only while `review_round` is below 2; a claim that has already consumed 2 information rounds rejects the request with `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 409), and the adjudicator must then decide."
    PRD §3.7: "The filing side answers an information request by resubmitting with a `supplemental_note`, moving the claim from `INFO_REQUESTED` back to `UNDER_REVIEW`; resubmission is accepted from the `FleetManager` of the fleet that owns the claim's unit, or from the `ServiceAdvisor` whose `X-User-ID` equals the claim's `service_center_id`."

    Two full cycles leave review_round at 2; the third request-info is the one
    that fails, and the claim remains UNDER_REVIEW.

    Design: Difficulty/non_linear_state_machine/claim_review_cycle_two_rounds_then_must_decide
    """
    env, unit, claim = _claim_after_two_full_info_rounds()

    resp = api.request_claim_info(claim["id"], adjudicator_headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_ROUNDS_EXHAUSTED)

    claim_now = validate_success(api.get_warranty_claim(claim["id"], admin_headers))
    assert_warranty_claim(claim_now)
    assert claim_now["status"] == "UNDER_REVIEW", (
        f"the exhausted request must not move the claim, got {claim_now['status']}"
    )
    assert claim_now["review_round"] == 2, (
        f"two completed information rounds give review_round 2, got {claim_now['review_round']}"
    )


def test_claim_still_adjudicates_after_review_cycle_exhausted(api, adjudicator_headers, admin_headers):
    """PRD §3.7: "a claim that has already consumed 2 information rounds rejects the request with `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 409), and the adjudicator must then decide."
    PRD §3.7: "On `APPROVE_FULL` the claim moves to `APPROVED_FULL` with `approved_amount_cents` equal to `claimed_amount_cents` and `customer_share_cents` equal to 0."
    PRD §3.7: "a score below 30 is consistent only with an `APPROVE_FULL` decision"

    With no maintenance history and no snapshots the neglect score is 0, so
    after the third request-info is rejected the claim still adjudicates to
    APPROVED_FULL for the full amount.

    Design: Difficulty/non_linear_state_machine/claim_review_cycle_two_rounds_then_must_decide
    """
    env, unit, claim = _claim_after_two_full_info_rounds()

    resp = api.request_claim_info(claim["id"], adjudicator_headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_ROUNDS_EXHAUSTED)

    decided = adjudicate(claim["id"], "APPROVE_FULL")
    assert_warranty_claim(decided)
    assert decided["status"] == "APPROVED_FULL"
    assert decided["review_round"] == 2
    assert decided["neglect_score"] == 0, (
        f"no history on the unit means score 0, got {decided['neglect_score']}"
    )
    assert decided["approved_amount_cents"] == 40000
    assert decided["customer_share_cents"] == 0
    assert_claim_financials_balance(decided)


# ---------------------------------------------------------------------------
# field campaign completion-review revert loop
# ---------------------------------------------------------------------------
def _campaign_with_one_of_two_verified():
    """RECALL campaign CMP-1 IN_PROGRESS over units UN-501/UN-502 (both flagged
    CAMPAIGN_OPEN at announce); the work order for UN-501 is walked to VERIFIED
    (rate 0.5) while UN-502's order stays SCHEDULED."""
    env = setup_full_environment()
    family, fleet, center, tech = (
        env["family"], env["fleet"], env["center"], env["technician"],
    )
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-501")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-502")
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=9, passing_units=8,
    )
    set_logical_clock(CAMPAIGN_CLOCK)
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-1", campaign_type="RECALL",
        defect_summary="SCR catalyst washcoat degradation",
        remedy_description="Replace SCR catalyst and reflash dosing", remedy_bay_days=1,
    )
    wo_a = schedule_work_order(
        campaign["id"], unit_a["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    wo_b = schedule_work_order(
        campaign["id"], unit_b["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    start_work_order(wo_a["id"], center["id"])
    complete_work_order(wo_a["id"], center["id"])
    verify_work_order(wo_a["id"])
    return env, unit_a, unit_b, campaign, wo_a, wo_b


def test_completion_review_below_threshold_parks_campaign(api, officer_headers, admin_headers):
    """PRD §3.8: "A `RegulatoryOfficer` may move an `IN_PROGRESS` campaign to `COMPLETION_REVIEW`; the request recomputes the campaign's `completion_rate` — 0 while `notified_unit_count` is 0, otherwise the verified count divided by the notified count, rounded half-up to 4 decimal places — and, when `notified_unit_count` is greater than 0 and the rate is at least the campaign's `completion_threshold` (the boundary is inclusive), the campaign advances all the way to `CLOSED` within the same request."
    PRD §3.8: "When the rate falls short, the campaign sits in `COMPLETION_REVIEW` until either further verifications push it over the threshold — verification re-evaluates closure while the campaign is in that state — or the officer resumes execution, moving it back from `COMPLETION_REVIEW` to `IN_PROGRESS` in the revert loop."

    One verified unit out of two notified gives rate 0.5, below the default
    threshold 0.95, so completion-review lands in COMPLETION_REVIEW instead of
    CLOSED and the family stays on COMPLIANCE_HOLD.

    Design: Difficulty/non_linear_state_machine/campaign_completion_review_revert_loop
    """
    env, unit_a, unit_b, campaign, wo_a, wo_b = _campaign_with_one_of_two_verified()

    resp = api.campaign_completion_review(campaign["id"], officer_headers)
    reviewed = validate_success(resp)
    assert reviewed["status"] == "COMPLETION_REVIEW", (
        f"rate 0.5 below 0.95 must not close, got {reviewed['status']}"
    )

    campaign_now = validate_success(api.get_field_campaign(campaign["id"], admin_headers))
    assert_field_campaign(campaign_now)
    assert campaign_now["status"] == "COMPLETION_REVIEW"
    assert campaign_now["notified_unit_count"] == 2
    assert campaign_now["verified_unit_count"] == 1
    assert campaign_now["completion_rate"] == compute_completion_rate(1, 2), (
        f"verified 1 / notified 2 = 0.5, got {campaign_now['completion_rate']}"
    )

    family_now = get_family(env["family"]["id"])
    assert family_now["certification_status"] == "COMPLIANCE_HOLD", (
        "the family exits the hold only when its last open campaign closes; "
        f"got {family_now['certification_status']}"
    )


def test_resume_execution_reverts_campaign_to_in_progress(api, officer_headers, admin_headers):
    """PRD §3.8: "or the officer resumes execution, moving it back from `COMPLETION_REVIEW` to `IN_PROGRESS` in the revert loop."
    PRD §3.2: "A family in `CERTIFIED` or `IN_PRODUCTION` is moved to `COMPLIANCE_HOLD` by the system — never directly — as a side effect of a field campaign being announced (§3.8). Symmetrically, when the family's last open campaign closes, the system moves the family out of `COMPLIANCE_HOLD`: to `IN_PRODUCTION` when `production_entered` is true, and back to `CERTIFIED` when it is false."

    Resuming execution loops the campaign back to IN_PROGRESS with the counters
    untouched; the still-open campaign keeps the family on COMPLIANCE_HOLD and
    the unverified work order stays SCHEDULED.

    Design: Difficulty/non_linear_state_machine/campaign_completion_review_revert_loop
    """
    env, unit_a, unit_b, campaign, wo_a, wo_b = _campaign_with_one_of_two_verified()
    validate_success(api.campaign_completion_review(campaign["id"], officer_headers))

    resumed = validate_success(api.resume_campaign_execution(campaign["id"], officer_headers))
    assert resumed["status"] == "IN_PROGRESS", (
        f"resume-execution loops back to IN_PROGRESS, got {resumed['status']}"
    )

    campaign_now = validate_success(api.get_field_campaign(campaign["id"], admin_headers))
    assert campaign_now["status"] == "IN_PROGRESS"
    assert campaign_now["notified_unit_count"] == 2
    assert campaign_now["verified_unit_count"] == 1, (
        "the revert loop does not erase verified progress"
    )

    wo_b_now = validate_success(api.get_campaign_work_order(wo_b["id"], admin_headers))
    assert wo_b_now["status"] == "SCHEDULED", (
        f"the unverified order is untouched by the loop, got {wo_b_now['status']}"
    )

    unit_b_now = validate_success(api.get_engine_unit(unit_b["id"], admin_headers))
    assert_engine_unit(unit_b_now)
    assert unit_b_now["campaign_compliance"] == "CAMPAIGN_OPEN"

    family_now = get_family(env["family"]["id"])
    assert family_now["certification_status"] == "COMPLIANCE_HOLD"
