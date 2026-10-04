"""Sanction machinery: indicator cascade, CFI severity floor, cure sub-lifecycle."""
import pytest

from test_helpers import (
    CURE_REVIEW_NEXT_DAY_ISO,
    EXPECTED_CFI_PANEL_BAND,
    EXPECTED_CURE_SNAPSHOT_PROBATION,
    POST_VISIT_CLOCK_ISO,
    ApiErrorId,
    apply_sanction_transition,
    create_change_request,
    create_institution,
    file_team_report,
    get_institution,
    list_change_requests,
    list_institution_outcomes,
    sanction_transition_payload,
    schedule_visit,
    set_logical_clock,
    setup_accredited_institution,
    setup_locked_argument,
    setup_panel_band_sanction,
    submit_change_request,
    submit_cleared_report,
    validate_error,
)


def test_panel_band_evaluation_cascades_to_frozen_change_requests(api):
    """PRD section 3.9: "A report whose CFI falls in the `PANEL` band is marked `FLAGGED_PANEL`, and that verdict fires the indicator cascade: the system creates an `ActionOutcome` with `origin` `INDICATOR_MONITOR`, `action_type` `NOTICE`, status already `EFFECTIVE`, `sanction_level` `NOTICE`, a `cure_deadline_at` twelve months after the evaluation, and `indicator_origin_institution_id` pointing at the reporting institution; the institution's `sanction_status` moves from `NONE` to `NOTICE`, or stays where it is if a sanction is already in force; and the substantive-change freeze of §2.11 applies to the institution's in-flight requests."
    PRD section 2.11: "Imposing a sanction freezes the institution's in-flight substantive-change requests: every such request in `SUBMITTED` status moves to `DEFERRED` with its `decision_notes` set to the literal text "frozen by sanction", while requests still in `DRAFT` are left untouched (§3.8, §3.9)."

    Design: Difficulty/transitive_cascade/indicator_panel_band_cascade_freezes_substantive_changes
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]

    change = create_change_request(institution_id, "NEW_LOCATION")
    submitted = submit_change_request(change["id"], institution_id)
    assert submitted["status"] == "SUBMITTED"

    result = setup_panel_band_sanction(institution_id)
    assert result["report"]["status"] == "FLAGGED_PANEL"
    assert result["report"]["cfi_value"] == pytest.approx(EXPECTED_CFI_PANEL_BAND, abs=0.001)

    outcome = result["outcome"]
    assert outcome["origin"] == "INDICATOR_MONITOR"
    assert outcome["action_type"] == "NOTICE"
    assert outcome["status"] == "EFFECTIVE"

    institution = get_institution(institution_id)
    assert institution["sanction_status"] == "NOTICE"
    assert institution["latest_cfi_band"] == "PANEL"

    changes = list_change_requests(institution_id)
    assert changes[0]["id"] == change["id"]
    assert changes[0]["status"] == "DEFERRED"
    assert changes[0]["decision_notes"] == "frozen by sanction"


def test_cfi_panel_floor_forces_denial_on_initial_cycle(api):
    """PRD section 3.6: "Three floors then apply in a fixed order, each able only to raise the severity, never lower it: first, if the institution's `sanction_status` is `PROBATION` or `SHOW_CAUSE`, the severity is raised to at least 2; second, if the cycle's `federal_compliance_status` is `DEFICIENT`, the severity is raised to at least 2, while `PENDING` or `COMPLIANT` imposes no floor; third, if the institution's `latest_cfi_band` is `PANEL`, the severity is raised to at least 3."
    PRD section 3.6: "The resulting severity is then mapped through the cycle type: on a `REAFFIRMATION` cycle, severities 1 through 4 produce `REAFFIRMATION`, `NOTICE`, `PROBATION`, and `SHOW_CAUSE` respectively, while on an `INITIAL_ACCREDITATION` cycle severity 1 produces `GRANT_INITIAL`, severity 2 produces `NOTICE`, and severity 3 or 4 produces `DENIAL`."

    Design: Difficulty/combinatorial_formula/cfi_panel_floor_binds_over_clean_sanction_record
    """
    ctx = setup_locked_argument()
    institution_id = ctx["institution"]["id"]

    result = setup_panel_band_sanction(institution_id)
    assert result["report"]["status"] == "FLAGGED_PANEL"
    assert result["report"]["cfi_value"] == pytest.approx(EXPECTED_CFI_PANEL_BAND, abs=0.001)

    team_id = ctx["team"]["id"]
    schedule_visit(team_id, ctx["team"]["chair_reviewer_id"])
    set_logical_clock(POST_VISIT_CLOCK_ISO)
    # 4 x MET + 1 x MET_WITH_CONCERNS = 18 points -> base severity 1; the
    # PANEL CFI floor lifts it to 3, which maps to DENIAL on an initial cycle.
    filed = file_team_report(
        team_id,
        ctx["team"]["chair_reviewer_id"],
        ratings={"CRIT_RESOURCES_PLANNING": "MET_WITH_CONCERNS"},
    )
    assert filed["recommended_action_computed"] == "DENIAL"

    institution = get_institution(institution_id)
    assert institution["sanction_status"] == "NOTICE"
    assert institution["latest_cfi_band"] == "PANEL"


def test_cure_threshold_snapshot_frozen_at_review_open(api):
    """PRD section 3.8: "Opening a cure review requires the outcome's `cure_status` to be `NONE` — opening twice is `ERR_INVALID_STATE` — and it sets `cure_status` to `UNDER_CURE_REVIEW`, stamps `cure_review_opened_at`, and freezes `cure_threshold_snapshot` at a base of 60 plus the offset of the sanction level in force at that instant: 0 for `NOTICE`, 15 for `PROBATION`, 30 for `SHOW_CAUSE`."
    PRD section 3.8: "The cure evidence score awards 25 points for each of the institution's indicator reports that reached `CLEARED` with an `evaluated_at` strictly later than `cure_review_opened_at`, capped at 100."
    PRD section 3.8: "The cure succeeds only when that score is at least `cure_threshold_snapshot`; a cure attempted without an open review, or with a score below the snapshot, is rejected with `ERR_CURE_THRESHOLD_NOT_MET` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/cure_threshold_snapshot_frozen_at_probation_level
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    outcome_id = setup_panel_band_sanction(institution_id)["outcome"]["id"]

    escalated = apply_sanction_transition(outcome_id, "ESCALATE")
    assert escalated["sanction_level"] == "PROBATION"

    opened = apply_sanction_transition(outcome_id, "OPEN_CURE_REVIEW")
    assert opened["cure_status"] == "UNDER_CURE_REVIEW"
    # Frozen at 60 + 15 even though PROBATION was reached by escalation.
    assert opened["cure_threshold_snapshot"] == EXPECTED_CURE_SNAPSHOT_PROBATION

    set_logical_clock(CURE_REVIEW_NEXT_DAY_ISO)
    for year in (2027, 2028, 2029):
        cleared = submit_cleared_report(institution_id, year)
        assert cleared["status"] == "CLEARED"
    # Score: 3 reports x 25 points = 75, meeting the frozen snapshot exactly.
    cured = apply_sanction_transition(outcome_id, "CURE")
    assert cured["cure_status"] == "CURED"
    assert get_institution(institution_id)["sanction_status"] == "NONE"


def test_cure_below_threshold_rejected(api, staff_headers):
    """PRD section 3.8: "The cure succeeds only when that score is at least `cure_threshold_snapshot`; a cure attempted without an open review, or with a score below the snapshot, is rejected with `ERR_CURE_THRESHOLD_NOT_MET` (HTTP 422)."

    Design: Corner/errors/cure_threshold_not_met_returns_422
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    outcome_id = setup_panel_band_sanction(institution_id)["outcome"]["id"]

    escalated = apply_sanction_transition(outcome_id, "ESCALATE")
    assert escalated["sanction_level"] == "PROBATION"
    opened = apply_sanction_transition(outcome_id, "OPEN_CURE_REVIEW")
    assert opened["cure_threshold_snapshot"] == EXPECTED_CURE_SNAPSHOT_PROBATION

    set_logical_clock(CURE_REVIEW_NEXT_DAY_ISO)
    for year in (2027, 2028):  # 2 reports x 25 points = 50 < 75
        cleared = submit_cleared_report(institution_id, year)
        assert cleared["status"] == "CLEARED"

    response = api.sanction_transition(
        outcome_id, sanction_transition_payload("CURE"), staff_headers
    )
    validate_error(response, ApiErrorId.ERR_CURE_THRESHOLD_NOT_MET)

    assert get_institution(institution_id)["sanction_status"] == "PROBATION"
    outcomes = list_institution_outcomes(institution_id)
    assert outcomes[0]["cure_status"] == "UNDER_CURE_REVIEW"
