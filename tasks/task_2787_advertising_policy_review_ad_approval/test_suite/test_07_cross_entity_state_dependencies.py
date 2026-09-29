"""A creative's own row is never enough to predict what happens to it.

The first pair sends byte-identical screening runs to two creatives that differ only in
who owns them, and the owner's verification posture alone decides whether one of them
auto-approves. The second pair takes a creative that is already cleared and revokes the
licence it was pinned to, dragging it back into review from a row it does not own.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_success,
)

FIN_CREDIT = "FIN_CREDIT"
SPIRITS = "ALC_SPIRITS"


# ---------------------------------------------------------------------------
# Shared setup for the AdCreative x Advertiser pair
# ---------------------------------------------------------------------------
def _identical_runs_under_two_postures():
    """Two identical creatives screened at 0.30, owned by differently verified holders.

    `advFull` has both axes `VERIFIED`; `advPartial` has `IDENTITY` `VERIFIED` and
    `BUSINESS_STANDING` still `PENDING`. The 0.30 confidence is below the rule's 0.40
    manual threshold, so neither run has a finding and neither can score anything.
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        8.00,
        title="Consumer credit offers",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.85,
        confidence_manual_threshold=0.40,
        review_sla_hours=72,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        rule["id"], "US", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.20
    )
    full = fixtures.create_verified_advertiser(
        legal_name="Fairhaven Credit Union",
        country_code="US",
        industry_code="CONSUMER_CREDIT",
    )
    partial = fixtures.create_advertiser(
        legal_name="Stonegate Credit Union",
        country_code="US",
        industry_code="CONSUMER_CREDIT",
    )
    partial = fixtures.record_verification(
        partial["id"], "IDENTITY", "VERIFIED", "kyc-2026-0082"
    )
    assert partial["identity_status"] == "VERIFIED"
    assert partial["business_standing_status"] == "PENDING"

    runs = {}
    creatives = {}
    for key, advertiser, host in (
        ("full", full, "fairhaven"),
        ("partial", partial, "stonegate"),
    ):
        creative, run = fixtures.screened_creative(
            advertiser["id"],
            [FIN_CREDIT],
            [(rule["id"], 0.30)],
            ["US"],
            headline="Low rate personal loan",
            body_text="Apply for a low rate personal loan in minutes.",
            landing_page_url=f"https://www.{host}.example/loan",
            display_url=f"https://www.{host}.example/loan",
            disclaimer_text="APR 7.9%-19.9%. Terms apply.",
        )
        creatives[key] = creative
        runs[key] = run
    return {
        "rule": rule,
        "full_advertiser_id": full["id"],
        "partial_advertiser_id": partial["id"],
        "creatives": creatives,
        "runs": runs,
    }


def test_the_owners_business_standing_alone_decides_which_run_auto_approves():
    """PRD §3.4: "Fourth, the outcome is `ROUTED_MANUAL` when the owning advertiser's
    `identity_status` is anything other than `VERIFIED`, or its
    `business_standing_status` is anything other than `VERIFIED`."

    PRD §3.4: "An `AUTO_APPROVED` outcome advances `SCREENING → AUTO_APPROVED`, which
    additionally requires that the advertiser's `identity_status` and
    `business_standing_status` are both `VERIFIED` and that `political_flag` is false —
    conditions the fourth and second grading clauses already guarantee, which is
    precisely why this transition is unreachable for a political creative."

    Design: Difficulty/cross_entity_state_dependency/screening_outcome_depends_on_the_owning_advertiser_verification_axes
    """
    case = _identical_runs_under_two_postures()

    assert case["runs"]["full"]["outcome"] == "AUTO_APPROVED"
    assert case["creatives"]["full"]["review_status"] == "AUTO_APPROVED"
    assert fixtures.list_tasks_for_creative(case["creatives"]["full"]["id"]) == []

    assert case["runs"]["partial"]["outcome"] == "ROUTED_MANUAL"
    assert case["creatives"]["partial"]["review_status"] == "PENDING_MANUAL_REVIEW"

    # Neither run has a finding, so the divergence cannot have come from the score.
    for key in ("full", "partial"):
        assert case["runs"][key]["provisional_risk_score"] == pytest.approx(
            0.00, abs=0.01
        )
        decisions = fixtures.decisions_for_run(case["runs"][key]["id"])
        assert len(decisions) == 1
        assert decisions[0]["disposition"] == "BELOW_THRESHOLD"
        # 8.00 * 1.20 * 0.30, identical on both rows.
        assert decisions[0]["assessed_points"] == pytest.approx(2.88, abs=0.01)


def test_a_task_routed_with_no_qualifying_decision_falls_back_on_every_axis():
    """PRD §3.4: "Its `queue` is `POLITICAL` when the creative's `political_flag` is
    true; otherwise it is `REGULATED_CERT` when some decision with disposition
    `AUTO_DISAPPROVE` or `ROUTE_MANUAL` matched a rule whose `requires_certification` is
    true, or when such a decision's rule has a country variation with `requires_license`
    true for one of the creative's target countries; otherwise it is `STANDARD`."

    PRD §3.4: "Its `sla_deadline_at` is the task's `created_at` plus the
    `review_sla_hours` of the primary rule, or plus a default of 48 hours when
    `primary_policy_rule_id` is null."

    PRD §3.6: "Compute a severity component: 0.00 when the task has no
    `primary_policy_rule_id`, and otherwise the primary rule's `base_severity_weight`
    multiplied by the creative's strictest multiplier and then multiplied by 2.00, that
    product rounded half-up to 2 decimals and then capped at 30.00."

    Design: Difficulty/cross_entity_state_dependency/screening_outcome_depends_on_the_owning_advertiser_verification_axes
    """
    case = _identical_runs_under_two_postures()

    task = fixtures.only_task_for_creative(case["creatives"]["partial"]["id"])
    assert task["primary_policy_rule_id"] is None
    # The rule's own default was REGULATED_CERT, but no decision qualified.
    assert task["queue"] == "STANDARD"
    assert task["queue"] != case["rule"]["default_queue"]
    assert_instant_equals(
        task["sla_deadline_at"], "2026-08-03T00:00:00Z", "sla_deadline_at"
    )
    # 30.00 STANDARD base + max(0.00, 0.00) + 10.00 verification gap.
    assert task["priority_score"] == pytest.approx(40.00, abs=0.01)

    approved = fixtures.read_creative(
        case["creatives"]["full"]["id"],
        advertiser_id=case["full_advertiser_id"],
    )
    # Its review axis is clear; only the untouched destination axis holds it back.
    assert approved["serving_eligible"] is False
    assert approved["blocking_reason_codes"] == ["DESTINATION_NOT_CLEARED"]


# ---------------------------------------------------------------------------
# Shared setup for the AdCreative x Certification pair
# ---------------------------------------------------------------------------
def _creative_cleared_against_a_licence():
    """An APPROVED_LIMITED creative pinned to the one licence its holder owns."""
    rule = fixtures.create_policy_rule(
        SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Marrow Creek Distillery",
        country_code="US",
        industry_code="ALCOHOL",
    )
    advertiser_id = advertiser["id"]
    certification = fixtures.create_certification(
        advertiser_id,
        rule["id"],
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
        issuing_country_code="US",
        license_number="ABC-US-2026-7781",
        headers=make_advertiser_headers(advertiser_id),
    )
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["US"],
        display_name="Rev Regulated US",
        max_concurrent_claims=2,
    )
    creative, first_task = fixtures.creative_in_manual_review(
        advertiser_id,
        [SPIRITS],
        [(rule["id"], 0.80)],
        ["US"],
        headline="Bourbon flight tasting",
        body_text="Book a bourbon flight tasting at our distillery.",
        landing_page_url="https://www.marrowcreek.example/flight",
        display_url="https://www.marrowcreek.example/flight",
        disclaimer_text="Drink responsibly. 21+",
    )
    assert creative["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
    fixtures.claim_task(first_task["id"], reviewer["id"])
    fixtures.decide_task(
        first_task["id"],
        reviewer["id"],
        "APPROVE_WITH_LIMITS",
        limited_country_codes=["US"],
        note="Licensed in US.",
    )
    cleared = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert cleared["review_status"] == "APPROVED_LIMITED"
    assert cleared["approved_under_certification_id"] == certification["id"]
    assert cleared["limited_country_codes"] == ["US"]
    assert cleared["risk_score_final"] == pytest.approx(0.00, abs=0.01)
    return {
        "advertiser_id": advertiser_id,
        "certification_id": certification["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "first_task_id": first_task["id"],
    }


def test_revoking_the_pinned_licence_drags_the_creative_back_into_review():
    """PRD §3.5: "Revocation is narrower in scope but heavier in effect: every creative
    whose `approved_under_certification_id` names the revoked licence and whose
    `review_status` is `APPROVED_LIMITED` moves to `PENDING_MANUAL_REVIEW` with a new
    `REGULATED_CERT` task, and has both `approved_under_certification_id` and
    `limited_country_codes` cleared, along with the same recomputation and `version`
    bump."

    PRD §3.5: "A `PolicyAdmin` may instead revoke a certification whose `status` is
    `SUBMITTED` or `ACTIVE`, supplying `revocation_reason`, which moves it to `REVOKED`;
    revoking one already `EXPIRED` or `REVOKED` is refused with
    `ERR_INVALID_CERTIFICATION_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/limited_approval_depends_on_certification_row_state_and_collapses_on_revocation
    """
    case = _creative_cleared_against_a_licence()

    revoked = fixtures.revoke_certification(
        case["certification_id"],
        "State board suspended the license pending audit.",
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_reason"] == (
        "State board suspended the license pending audit."
    )

    dragged = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert dragged["review_status"] == "PENDING_MANUAL_REVIEW"
    assert dragged["approved_under_certification_id"] is None
    assert dragged["limited_country_codes"] == []
    assert dragged["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)

    tasks = fixtures.list_tasks_for_creative(case["creative_id"])
    assert len(tasks) == 2, f"the revocation mints exactly one fresh task: {tasks}"
    by_id = {task["id"]: task for task in tasks}
    assert by_id[case["first_task_id"]]["status"] == "RESOLVED"
    replacement = [
        task for task in tasks if task["id"] != case["first_task_id"]
    ][0]
    assert replacement["status"] == "QUEUED"
    assert replacement["queue"] == "REGULATED_CERT"
    assert replacement["cycle_count"] == 0


def test_the_same_limited_approval_now_fails_while_a_plain_approval_still_lands():
    """PRD §3.5: "Rows in `SUBMITTED`, `EXPIRED` or `REVOKED` never qualify as
    coverage."

    PRD §3.7: "`APPROVE` advances `PENDING_MANUAL_REVIEW → AUTO_APPROVED`."

    PRD §3.7: "Beyond the gates above it demands nothing further: when `political_flag`
    is true the creative must carry non-empty `disclaimer_text` and the advertiser must be
    `ELIGIBLE`, and when any matched rule or any applicable country variation has
    `requires_disclaimer` true the creative must carry non-empty `disclaimer_text`."

    Design: Difficulty/cross_entity_state_dependency/limited_approval_depends_on_certification_row_state_and_collapses_on_revocation
    """
    case = _creative_cleared_against_a_licence()
    fixtures.revoke_certification(
        case["certification_id"],
        "State board suspended the license pending audit.",
    )
    replacement = [
        task
        for task in fixtures.list_tasks_for_creative(case["creative_id"])
        if task["id"] != case["first_task_id"]
    ][0]
    fixtures.claim_task(replacement["id"], case["reviewer_id"])

    validate_error(
        api_client.decide_review_task(
            replacement["id"],
            factories.decide_review_task_payload(
                "APPROVE_WITH_LIMITS", None, ["US"], "Retrying the limited approval."
            ),
            make_reviewer_headers(case["reviewer_id"]),
        ),
        ApiErrorId.ERR_CERTIFICATION_MISSING,
        422,
    )

    validate_success(
        api_client.decide_review_task(
            replacement["id"],
            factories.decide_review_task_payload(
                "APPROVE", None, None, "Approving without country limits."
            ),
            make_reviewer_headers(case["reviewer_id"]),
        )
    )

    approved = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert approved["review_status"] == "AUTO_APPROVED"
    assert approved["limited_country_codes"] == []
    assert approved["approved_under_certification_id"] is None
    # The 8.00 coverage credit is gone with the licence, so the final score is the
    # provisional score again.
    assert approved["risk_score_final"] == pytest.approx(7.20, abs=0.01)

    resolved = fixtures.read_task(replacement["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "APPROVE"
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 0
