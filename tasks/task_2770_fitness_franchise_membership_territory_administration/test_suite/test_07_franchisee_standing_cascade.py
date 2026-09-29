"""The four-link compliance chain, and the standing gate it leaves behind.

One scoring call walks inspection to club to franchisee to promotion. Once the franchisee
is on probation, the gate on promotion approval stays shut until it is explicitly
reinstated — curing the facility defect is not enough on its own.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_approved_promotion,
    create_promotion,
    drive_franchisee_to_probation,
    inspect_club,
    promotion_review_payload,
    read_club,
    read_franchisee,
    read_promotion,
    reinstate_franchisee,
    schedule_inspection,
    score_inspection,
    setup_single_club_franchise,
)

BRAND = TEST_USERS["brand_administrator_headers"]
LEGACY_OPENED_ON = "2019-06-01"


def _legacy_club_with_one_failure_behind_it() -> dict:
    """A pre-2020 club that has already failed once, an approved promotion still standing,
    and a second inspection waiting to be scored."""
    scenario = setup_single_club_franchise(
        legal_name="Vantage Fitness Group LLC",
        contact_email="ops@vantagefit.example",
        club_name="Vantage Downtown",
        opened_on=LEGACY_OPENED_ON,
    )
    scenario["promotion"] = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="SUMMER10",
        discount_pct=0.10,
        starts_on="2026-08-01",
        ends_on="2026-08-31",
    )
    scenario["first_inspection"] = inspect_club(
        scenario["club"]["id"], "2026-07-10", 78, 86, 80, 54
    )
    scenario["second_inspection"] = schedule_inspection(scenario["club"]["id"], "2026-07-20")
    return scenario


def _legacy_club_after_its_second_failure() -> dict:
    scenario = _legacy_club_with_one_failure_behind_it()
    scenario["second_score"] = score_inspection(
        scenario["second_inspection"]["id"], 78, 86, 80, 54
    )
    return scenario


def _probation_franchisee_with_a_pending_filing() -> dict:
    """Two failing inspections have demoted the owner while its 10 percent filing — well
    inside the cap and alone on its channel — still waits for review."""
    scenario = setup_single_club_franchise(
        legal_name="Stonebridge Fitness LLC",
        contact_email="ops@stonebridgefit.example",
        club_name="Stonebridge Club",
        opened_on=LEGACY_OPENED_ON,
    )
    scenario["promotion"] = create_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="FALL10",
        discount_pct=0.10,
        starts_on="2026-09-01",
        ends_on="2026-09-30",
    )
    scenario["inspections"] = drive_franchisee_to_probation(scenario["club"]["id"])
    return scenario


def _probation_franchisee_after_a_passing_re_inspection() -> dict:
    scenario = _probation_franchisee_with_a_pending_filing()
    scenario["recovery_inspection"] = inspect_club(
        scenario["club"]["id"], "2026-07-25", 95, 92, 90, 12
    )
    return scenario


def test_one_failure_dents_the_score_without_demoting_the_franchisee():
    """A single failing walk-through costs 20 points, and 80 is not below the probation
    threshold, so the promotion is untouched and the chain stops at the club.

    PRD 2.10: "The most consequential cascade is the franchisee compliance chain, and it
    always runs in the same direction: a facility, billing, or reporting event changes a
    club-level or report-level fact, that fact changes the owning `Franchisee`'s
    `compliance_score`, and a score that falls below the probation threshold demotes the
    franchisee from `ACTIVE` to `PROBATION`, which in turn withdraws every one of that
    franchisee's approved promotions."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_club_to_franchisee_to_promotion_withdrawal
    """
    scenario = _legacy_club_with_one_failure_behind_it()

    assert scenario["first_inspection"]["score"] == 69
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 1
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"
    assert read_promotion(scenario["promotion"]["id"])["status"] == "APPROVED"


def test_pre_2020_opening_keeps_the_accelerated_cycle_on_the_second_scoring():
    """The opening date alone selects the 42-month cycle, so the same sub-scores fail again
    at 69 and the inspection auto-resolves to remediation.

    PRD 3.9: "The accelerated cycle applies when the club's `opened_on` date falls before
    2020-01-01, or when the club's current `equipment_compliance_state` is `WATCH` — either
    condition alone is enough, and the check reads the club's compliance state as it stands
    *before* this inspection updates it."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_club_to_franchisee_to_promotion_withdrawal
    """
    scenario = _legacy_club_after_its_second_failure()
    inspection = scenario["second_score"]

    assert inspection["variant_applied"] == "ACCELERATED_CYCLE"
    assert inspection["refresh_cycle_months_applied"] == 42
    assert inspection["refresh_pts"] == 0
    assert inspection["score"] == 69
    assert inspection["status"] == "REMEDIATION_REQUIRED"


def test_second_consecutive_failure_drops_the_score_to_sixty_and_demotes_the_owner():
    """Two steps of trailing failure cost 40 points, and 60 is strictly below 70, so the
    franchisee is demoted in the same request that scored the inspection.

    PRD 3.9: "If the franchisee is `ACTIVE` and the freshly recomputed score is strictly
    below 70, the franchisee is demoted `ACTIVE → PROBATION`, which withdraws every
    `APPROVED` promotion it owns; a score of exactly 70 keeps it `ACTIVE`."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_club_to_franchisee_to_promotion_withdrawal
    """
    scenario = _legacy_club_after_its_second_failure()

    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 2
    assert franchisee["compliance_score"] == 60
    assert franchisee["status"] == "PROBATION"


def test_demotion_withdraws_the_approved_promotion_with_a_stamped_reason():
    """The fourth link fires off the demotion rather than off the inspection, taking the
    approved discount away and recording why.

    PRD 3.2: "When the owning franchisee is demoted from `ACTIVE` to `PROBATION` by the
    compliance cascade of §3.9, every promotion of that franchisee whose `status` is
    `APPROVED` moves `APPROVED → WITHDRAWN_BY_BRAND`, has its `withdrawn_reason` set to the
    string `FRANCHISEE_PROBATION`, and has its `version` incremented — one increment per
    withdrawn promotion."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_club_to_franchisee_to_promotion_withdrawal
    """
    scenario = _legacy_club_after_its_second_failure()

    promotion = read_promotion(scenario["promotion"]["id"])
    assert promotion["status"] == "WITHDRAWN_BY_BRAND"
    assert promotion["withdrawn_reason"] == "FRANCHISEE_PROBATION"


def test_repeatedly_failing_club_stays_non_compliant_and_suspended():
    """The middle link of the chain re-derives the facility state from the new score alone,
    which leaves the already-suspended club exactly where it was.

    PRD 3.9: "A club that has just become `NON_COMPLIANT` and was `OPEN` moves to
    `SUSPENDED`; a club that was `SUSPENDED` and has just scored 70 or better moves back to
    `OPEN`."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_club_to_franchisee_to_promotion_withdrawal
    """
    scenario = _legacy_club_after_its_second_failure()

    club = read_club(scenario["club"]["id"])
    assert club["last_inspection_score"] == 69
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["status"] == "SUSPENDED"


def test_approval_is_refused_while_the_owning_franchisee_sits_on_probation():
    """Nothing about the filing itself is wrong — a tenth off, alone on its channel — yet
    the owner's standing alone blocks the approval.

    PRD 3.2: "Approval re-verifies that `discount_pct` does not exceed the 0.30 cap, that
    the owning franchisee's `status` is still `ACTIVE` — approval while the owner sits in
    `PROBATION` is refused with `ERR_FRANCHISEE_ON_PROBATION` — and that no other
    `PENDING_REVIEW` or `APPROVED` promotion for the same franchisee-and-template pair
    violates the seven-day separation rule."

    Design: Difficulty/cross_entity_state_dependency/promotion_approval_gated_on_owning_franchisee_probation_state
    """
    scenario = _probation_franchisee_with_a_pending_filing()
    assert read_franchisee(scenario["franchisee"]["id"])["status"] == "PROBATION"

    response = api_client.review_promotion(
        scenario["promotion"]["id"], promotion_review_payload("APPROVE"), BRAND
    )
    validate_error(response, ApiErrorId.ERR_FRANCHISEE_ON_PROBATION.value)

    promotion = read_promotion(scenario["promotion"]["id"])
    assert promotion["status"] == "PENDING_REVIEW"
    assert promotion["reviewed_by_user_id"] is None


def test_passing_re_inspection_restores_the_score_but_not_the_standing():
    """A 90 wipes the trailing failure run and reopens the club, taking the compliance
    score back to a full 100 while the franchisee remains on probation.

    PRD 3.9: "A franchisee's `compliance_score` is a derived figure, recomputed from scratch
    on every event that could move it: scoring an inspection, waiving remediation, appending
    a billing event, placing an agreement in collections, requesting or finalizing a
    cancellation, completing a transfer, submitting a royalty report and adjudicating one."

    Design: Difficulty/cross_entity_state_dependency/promotion_approval_gated_on_owning_franchisee_probation_state
    """
    scenario = _probation_franchisee_after_a_passing_re_inspection()
    inspection = scenario["recovery_inspection"]

    assert inspection["refresh_cycle_months_applied"] == 42
    assert inspection["refresh_pts"] == 71
    assert inspection["score"] == 90
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 0
    assert franchisee["compliance_score"] == 100
    assert franchisee["status"] == "PROBATION"
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "COMPLIANT"
    assert club["status"] == "OPEN"


def test_approval_between_the_cure_and_the_reinstatement_still_fails():
    """The defect is gone and the score is perfect, but the gate reads the franchisee's
    status, which no recomputation moves on its own.

    PRD 2.10: "The chain never runs backwards on its own: curing the underlying defect does
    not automatically restore `ACTIVE` standing, and restoring `ACTIVE` standing does not
    resurrect a withdrawn promotion."

    Design: Difficulty/cross_entity_state_dependency/promotion_approval_gated_on_owning_franchisee_probation_state
    """
    scenario = _probation_franchisee_after_a_passing_re_inspection()

    response = api_client.review_promotion(
        scenario["promotion"]["id"], promotion_review_payload("APPROVE"), BRAND
    )
    validate_error(response, ApiErrorId.ERR_FRANCHISEE_ON_PROBATION.value)
    assert read_promotion(scenario["promotion"]["id"])["status"] == "PENDING_REVIEW"


def test_explicit_reinstatement_reopens_the_gate_and_the_filing_is_approved():
    """With the score already at 100 the reinstatement is allowed, and only then does the
    same review call succeed and stamp its reviewer.

    PRD 3.9: "A `BrandAdministrator` reinstates a franchisee with an optional `note`: the
    score is recomputed first, and the move `PROBATION → ACTIVE` is allowed only when that
    fresh score is 70 or above, with a still-deficient franchisee refused as
    `ERR_FRANCHISEE_ON_PROBATION`."

    Design: Difficulty/cross_entity_state_dependency/promotion_approval_gated_on_owning_franchisee_probation_state
    """
    scenario = _probation_franchisee_after_a_passing_re_inspection()

    reinstated = reinstate_franchisee(
        scenario["franchisee"]["id"], note="Equipment refresh verified"
    )
    assert reinstated["status"] == "ACTIVE"

    approved = validate_success(
        api_client.review_promotion(
            scenario["promotion"]["id"], promotion_review_payload("APPROVE"), BRAND
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "brand-reviewer-1"
