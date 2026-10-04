"""Decision panel: full happy path, close cascade, quorum, gate order, tally ties."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CDR_RATES_BOUNDARY_DEFICIENT,
    POST_VISIT_CLOCK_ISO,
    cast_panel_vote,
    cast_panel_votes,
    close_decision_panel,
    get_institution,
    get_review_team,
    get_reviewer,
    list_cycle_outcomes,
    list_team_assignments,
    make_reviewer_headers,
    record_federal_compliance,
    setup_accredited_institution,
    setup_decided_cycle,
    setup_panel_review,
    validate_error,
    validate_paginated,
)


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_initial_accreditation_pipeline_reaches_accredited(api):
    """PRD section 3.3: "The cycle walks a one-directional ladder: `SCHEDULED` → `MATERIALS_OPEN` → `EVALUATION_ACTIVE` → `VISIT_COMPLETE` → `PANEL_REVIEW` → `DECIDED` → `CLOSED`."
    PRD section 3.8: "A `GRANT_INITIAL` is gated on the candidacy clock — if the logical clock has passed `candidacy_expires_at`, the advance is rejected with `ERR_CANDIDACY_EXPIRED` (HTTP 409) — and otherwise promotes the institution from `CANDIDATE` to `ACCREDITED`, stamping `accredited_since`."

    Design: Corner/state_machines/initial_accreditation_happy_path_reaches_accredited
    """
    ctx = setup_accredited_institution()
    institution = ctx["institution"]
    assert institution["accreditation_status"] == "ACCREDITED"
    assert _parse_instant(institution["accredited_since"]) == _parse_instant(
        POST_VISIT_CLOCK_ISO
    )
    assert institution["sanction_status"] == "NONE"
    assert institution["last_reaffirmed_at"] is None

    assert ctx["panel"]["status"] == "CLOSED"
    assert ctx["panel"]["prevailing_action"] == "GRANT"
    assert ctx["outcome"]["action_type"] == "GRANT_INITIAL"
    assert ctx["outcome"]["origin"] == "PANEL"
    assert ctx["outcome"]["status"] == "EFFECTIVE"
    assert ctx["cycle"]["status"] == "CLOSED"


def test_panel_close_cascade_disbands_team_and_drafts_outcome(api):
    """PRD section 3.7: "A successful close stamps `closed_at`, moves the panel to the terminal `CLOSED`, and fires the panel-close cascade."
    PRD section 3.7: "An `ActionOutcome` is created with `origin` `PANEL`, the mapped `action_type`, and status `DRAFTED` (§3.8)."
    PRD section 3.7: "The cycle moves from `PANEL_REVIEW` to `DECIDED`, stamping `decided_at`."
    PRD section 3.7: "The cycle's `REPORT_FILED` review team moves to `DISBANDED`, each of its `ACTIVE` assignments moves to `CLOSED`, and each affected reviewer's `current_assignment_count` drops accordingly."
    PRD section 3.7: "Finally, the cycle's `REVIEW_LOCKED` assurance argument cascades to `ACCEPTED` — unless the prevailing action is a denial, in which case the argument is not accepted and remains locked."

    Design: Difficulty/transitive_cascade/panel_close_cascade_disbands_team_and_drafts_outcome
    """
    ctx = setup_decided_cycle()

    assert ctx["panel"]["status"] == "CLOSED"
    assert ctx["panel"]["prevailing_action"] == "GRANT"
    assert ctx["panel"]["closed_at"] is not None

    assert ctx["outcome"]["action_type"] == "GRANT_INITIAL"
    assert ctx["outcome"]["origin"] == "PANEL"
    assert ctx["outcome"]["status"] == "DRAFTED"

    assert ctx["cycle"]["status"] == "DECIDED"
    assert ctx["cycle"]["decided_at"] is not None

    assert ctx["team"]["status"] == "DISBANDED"
    assignments = list_team_assignments(ctx["team"]["id"])
    assert len(assignments) == 4
    assert all(a["status"] == "CLOSED" for a in assignments)
    chair = get_reviewer(ctx["reviewers"]["chair"]["id"])
    assert chair["current_assignment_count"] == 0

    assert ctx["argument"]["status"] == "ACCEPTED"


def test_panel_closes_with_exactly_quorum_votes(api):
    """PRD section 3.7: "Second, at least 5 of the 7 seats must have cast votes — the quorum — failing which the close is rejected with `ERR_PANEL_QUORUM_NOT_MET` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/panel_quorum_exactly_five_votes_suffices
    """
    ctx = setup_decided_cycle()  # exactly five GRANT votes are cast by default
    assert ctx["panel"]["status"] == "CLOSED"
    assert ctx["panel"]["prevailing_action"] == "GRANT"
    outcomes = list_cycle_outcomes(ctx["cycle"]["id"])
    assert len(outcomes) == 1
    assert outcomes[0]["action_type"] == "GRANT_INITIAL"


def test_federal_deficiency_checked_before_quorum(api, staff_headers):
    """PRD section 2.8: "Closing a decision panel evaluates the federal-compliance gate first, so a `DEFICIENT` cycle surfaces `ERR_FEDERAL_COMPLIANCE_DEFICIENT` rather than being masked by vote arithmetic, then the quorum gate, then the action-type consistency gate (§3.7)."
    PRD section 3.3: "The assessment reads the rates chronologically: the cycle is `DEFICIENT` if any single rate is 40.0 or greater, or if three rates were provided and all three are 30.0 or greater — both boundaries are inclusive, so exactly 40.0 triggers the single-year rule and exactly 30.0 counts toward the three-year rule."

    Design: Difficulty/priority_pair_validation_conflict/priority_federal_safety_over_quorum_constraint_rejected
    """
    ctx = setup_panel_review(record_compliance=False)
    cycle_id = ctx["cycle"]["id"]
    deficient = record_federal_compliance(
        cycle_id, cohort_default_rates=CDR_RATES_BOUNDARY_DEFICIENT
    )
    assert deficient["federal_compliance_status"] == "DEFICIENT"

    member_ids = [p["id"] for p in ctx["panelists"]]
    for reviewer_id in member_ids[:4]:  # one short of quorum
        cast_panel_vote(ctx["panel"]["id"], reviewer_id, "GRANT")

    response = api.close_decision_panel(ctx["panel"]["id"], {}, staff_headers)
    validate_error(response, ApiErrorId.ERR_FEDERAL_COMPLIANCE_DEFICIENT)

    panels, _meta = validate_paginated(api.list_decision_panels(cycle_id, staff_headers))
    assert panels[0]["status"] == "CONVENED"
    assert list_cycle_outcomes(cycle_id) == []


def test_panel_tie_breaks_toward_more_severe_action(api):
    """PRD section 3.7: "The tally itself takes the choice with the highest vote count among the cast votes; ties break toward the more severe action under the order `WITHDRAW` most severe, then `SHOW_CAUSE`, then `PROBATION`, then `NOTICE`, then `DENY`, then `REAFFIRM`, with `GRANT` least severe."
    PRD section 3.7: "The winning choice becomes `prevailing_action` and is mapped to the outcome vocabulary: `GRANT` maps to `GRANT_INITIAL`, `DENY` to `DENIAL`, `WITHDRAW` to `WITHDRAWAL`, `REAFFIRM` to `REAFFIRMATION`, and each sanction choice maps to the sanction of the same name."

    Design: Corner/calculations/tally_tie_breaks_toward_more_severe_action
    """
    ctx = setup_panel_review()
    member_ids = [p["id"] for p in ctx["panelists"]]
    cast_panel_votes(
        ctx["panel"]["id"], member_ids,
        ["GRANT", "GRANT", "NOTICE", "NOTICE", "PROBATION"],
    )
    closed = close_decision_panel(ctx["panel"]["id"])
    assert closed["prevailing_action"] == "NOTICE"

    outcomes = list_cycle_outcomes(ctx["cycle"]["id"])
    assert len(outcomes) == 1
    assert outcomes[0]["action_type"] == "NOTICE"
    assert outcomes[0]["origin"] == "PANEL"
    assert outcomes[0]["status"] == "DRAFTED"


def test_peer_reviewer_cannot_close_panel(api, staff_headers):
    """PRD section 2.1: "A request whose role is not among the roles authorized for the target endpoint, or that fails the entity-backed ownership binding described below, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST   | `/accreditation/decision-panels/{id}/close` | Close the panel and fire the decision cascade | CommissionStaff |"

    Design: Corner/rbac/peer_reviewer_cannot_close_panel
    """
    ctx = setup_panel_review()
    member_ids = [p["id"] for p in ctx["panelists"]]
    cast_panel_votes(ctx["panel"]["id"], member_ids, ["GRANT"] * 5)

    response = api.close_decision_panel(
        ctx["panel"]["id"], {}, make_reviewer_headers(member_ids[0])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    panels, _meta = validate_paginated(
        api.list_decision_panels(ctx["cycle"]["id"], staff_headers)
    )
    assert panels[0]["status"] == "CONVENED"
    assert list_cycle_outcomes(ctx["cycle"]["id"]) == []
