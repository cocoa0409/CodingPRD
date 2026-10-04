"""Peer reviewer registry and deterministic team assembly."""
import time

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_reviewer,
    assemble_review_team,
    create_reviewer,
    get_assignment_for_reviewer,
    get_reviewer,
    get_review_team,
    list_team_assignments,
    make_reviewer_headers,
    register_team_pool,
    respond_to_assignment,
    reviewer_payload,
    set_logical_clock,
    setup_submitted_argument,
    validate_error,
    validate_success,
)


def test_reviewer_create_and_read_roundtrip(api, staff_headers):
    """PRD section 3.5: "`CommissionStaff` register peer reviewers with a `full_name`, the `specialty_criteria` they cover as a subset of the five criterion codes, and a `quality_rating` between 0.00 and 5.00 at two decimal places; optional attributes are the reviewer's home `affiliation_institution_id` (null for the unaffiliated), a `declared_conflict_institution_ids` list, a `prior_chair_count` of completed prior chair assignments (default 0), and an `is_active` flag (default true)."
    PRD section 3.5: "The system continuously tracks each reviewer's `current_assignment_count`: the number of their assignments whose `response` is `PENDING` or `ACCEPTED`, whose own status is `ACTIVE`, and whose team has not been `DISBANDED`."

    Design: Corner/entities/reviewer_create_and_get_roundtrip
    """
    set_logical_clock()
    created = create_reviewer(
        full_name="Roundtrip Reviewer",
        specialty_criteria=["CRIT_MISSION", "CRIT_INTEGRITY"],
        quality_rating=4.25,
        prior_chair_count=1,
    )
    response = api.get_reviewer(created["id"], make_reviewer_headers(created["id"]))
    reviewer = validate_success(response)
    assert_reviewer(reviewer)
    assert reviewer["full_name"] == "Roundtrip Reviewer"
    assert reviewer["specialty_criteria"] == ["CRIT_MISSION", "CRIT_INTEGRITY"]
    assert reviewer["quality_rating"] == 4.25
    assert reviewer["prior_chair_count"] == 1
    assert reviewer["affiliation_institution_id"] is None
    assert reviewer["declared_conflict_institution_ids"] == []
    assert reviewer["is_active"] is True
    assert reviewer["current_assignment_count"] == 0


def test_reviewer_get_unknown_id_returns_not_found(api, staff_headers):
    """PRD section 2.8: "The global order is: (1) authentication of the two headers, failing as `ERR_UNAUTHENTICATED`; (2) role permission and entity-backed ownership, failing as `ERR_UNAUTHORIZED_ROLE`; (3) existence of every identifier in the path, validated left to right, where the first unresolved identifier produces the not-found code belonging to its own path root — one of `ERR_INSTITUTION_NOT_FOUND`, `ERR_ELIGIBILITY_APPLICATION_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`, `ERR_ASSURANCE_ARGUMENT_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_REVIEW_TEAM_NOT_FOUND`, `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_DECISION_PANEL_NOT_FOUND`, `ERR_ACTION_OUTCOME_NOT_FOUND`, `ERR_SUBSTANTIVE_CHANGE_NOT_FOUND`, or `ERR_INDICATOR_REPORT_NOT_FOUND`, each an HTTP 404; (4) state-machine checks — whether the target resource stands in a state that permits the requested transition, failing as `ERR_INVALID_STATE` — together with the creation guards on review cycles (`ERR_CYCLE_ALREADY_OPEN`) and substantive-change requests (`ERR_INSTITUTION_NOT_ACCREDITED`); and finally (5) the business rules of the endpoint — safety, constraint, temporal, referential, and fiscal checks — each named where it applies in §3."

    Design: Corner/errors/reviewer_get_not_found_returns_404
    """
    set_logical_clock()
    response = api.get_reviewer(NON_EXISTENT_UUID, staff_headers)
    validate_error(response, ApiErrorId.ERR_REVIEWER_NOT_FOUND)


def test_team_confirm_with_pending_assignments_rejected(api, staff_headers):
    """PRD section 3.5: "Staff confirm a `PROPOSED` team only when every `ACTIVE` assignment has `response` `ACCEPTED` and none carries a `conflict_status` of `CONFLICTED` — a late-declared conflict must first be resolved by a decline and its replacement — and any shortfall fails confirmation with `ERR_TEAM_INCOMPLETE` (HTTP 409)."

    Design: Corner/state_machines/team_confirm_with_pending_assignment_rejected
    """
    ctx = setup_submitted_argument()
    register_team_pool()
    team = assemble_review_team(ctx["cycle"]["id"])

    response = api.confirm_review_team(team["id"], {}, staff_headers)
    validate_error(response, ApiErrorId.ERR_TEAM_INCOMPLETE)
    assert get_review_team(team["id"])["status"] == "PROPOSED"


def test_reviewer_load_conserved_through_decline_and_replacement(api, staff_headers):
    """PRD section 3.5: "Declining moves the assignment's `response` to the terminal `DECLINED` and closes the assignment — its status becomes `CLOSED` — while it decrements the reviewer's load and immediately triggers the selector to offer the seat to the next-ranked eligible candidate not already assigned to this team, keeping the same `role_on_team`; if no eligible candidate remains, no replacement is created, the seat stays open, and the team simply cannot be confirmed."

    Design: Difficulty/compensating_invariant/reviewer_load_conserved_through_decline_and_replacement
    """
    ctx = setup_submitted_argument()
    pool = register_team_pool()
    team = assemble_review_team(ctx["cycle"]["id"])
    reserve = create_reviewer(
        full_name="Eve Reserve", specialty_criteria=["CRIT_MISSION"], quality_rating=2.50
    )

    declining = pool["members"][2]
    assert get_reviewer(declining["id"])["current_assignment_count"] == 1

    assignment = get_assignment_for_reviewer(team["id"], declining["id"])
    declined = respond_to_assignment(assignment["id"], declining["id"], "DECLINE")
    assert declined["response"] == "DECLINED"
    assert declined["status"] == "CLOSED"
    assert get_reviewer(declining["id"])["current_assignment_count"] == 0

    replacements = [
        a for a in list_team_assignments(team["id"], reserve["id"])
        if a["status"] == "ACTIVE"
    ]
    assert len(replacements) == 1
    assert replacements[0]["response"] == "PENDING"
    assert replacements[0]["role_on_team"] == "MEMBER"

    confirm = api.confirm_review_team(team["id"], {}, staff_headers)
    validate_error(confirm, ApiErrorId.ERR_TEAM_INCOMPLETE)


def test_chair_tiebreak_prefers_earlier_created_candidate(api, staff_headers):
    """PRD section 3.5: "From the eligible pool, the chair is chosen among candidates whose `prior_chair_count` is at least 2, ranked by `quality_rating` descending, then `prior_chair_count` descending, then `created_at` ascending; if no eligible candidate meets the chair bar, assembly fails with `ERR_NO_ELIGIBLE_CHAIR` (HTTP 422)."
    PRD section 3.5: "The three member seats go to the highest-ranked remaining candidates, ranked by the number of `specialty_criteria` covered descending, then `quality_rating` descending, then `created_at` ascending; if fewer than three members are available, assembly fails with `ERR_INSUFFICIENT_REVIEWER_POOL` (HTTP 422)."

    Design: Corner/cross_cutting_complexity_layers/selector_chair_tiebreak_prefers_earlier_created
    """
    ctx = setup_submitted_argument()
    chair_x = create_reviewer(
        full_name="Chair X", specialty_criteria=["CRIT_MISSION"],
        quality_rating=4.50, prior_chair_count=2,
    )
    # The tie breaks on created_at, which carries millisecond precision; keep
    # the two chair candidates on distinct timestamps.
    time.sleep(0.01)
    chair_y = create_reviewer(
        full_name="Chair Y", specialty_criteria=["CRIT_INTEGRITY"],
        quality_rating=4.50, prior_chair_count=2,
    )
    member1 = create_reviewer(
        full_name="Member One", specialty_criteria=["CRIT_MISSION"], quality_rating=1.00
    )
    member2 = create_reviewer(
        full_name="Member Two", specialty_criteria=["CRIT_INTEGRITY"], quality_rating=0.90
    )
    member3 = create_reviewer(
        full_name="Member Three", specialty_criteria=["CRIT_TEACHING_QUALITY"],
        quality_rating=0.80,
    )

    team = assemble_review_team(ctx["cycle"]["id"], "VIRTUAL")
    assert team["chair_reviewer_id"] == chair_x["id"]

    assignments = list_team_assignments(team["id"])
    assert len(assignments) == 4
    roles_by_reviewer = {a["reviewer_id"]: a["role_on_team"] for a in assignments}
    assert roles_by_reviewer[chair_x["id"]] == "CHAIR"
    # The losing chair candidate re-enters the member pool and tops it on quality.
    member_ids = {rid for rid, role in roles_by_reviewer.items() if role == "MEMBER"}
    assert member_ids == {chair_y["id"], member1["id"], member2["id"]}
    assert member3["id"] not in roles_by_reviewer
