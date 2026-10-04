"""The recruiting pipeline cycle: declining, re-engaging, re-screening and
re-assessing a candidate."""
from test_helpers import (
    api_client,
    candidate_to_offer_declined,
    get_success_data,
    new_candidate,
    new_office,
    ro_headers,
    dd_headers,
    set_clock,
    validate_success,
)


def _walk_one_cycle_to_declined(office_id, name, version="V2"):
    """Screen -> assess -> interview -> offer -> decline -> reengage."""
    candidate, assessment = candidate_to_offer_declined(
        office_id, name=name, assessment_version=version)
    candidate = validate_success(api_client.reengage_candidate(candidate["id"], ro_headers))
    return candidate, assessment


def test_reengagement_increments_the_counter_once_per_cycle():
    """PRD §3.2: "Re-engaging sets the stage to `REENGAGED`, increments
    `reengagement_count` by one, and supersedes — not invalidates — every one of
    the candidate's assessments currently in `SCHEDULED` or `SCORED`."

    Design: Difficulty/non_linear_state_machine/recruiting_pipeline_cycle_and_reengagement
    """
    set_clock()
    office = new_office()
    candidate, _ = _walk_one_cycle_to_declined(office["id"], "Morgan Cyclic")

    assert candidate["stage"] == "REENGAGED"
    assert candidate["reengagement_count"] == 1


def test_the_declined_assessment_is_superseded_not_invalidated():
    """PRD §3.2: "Re-engaging sets the stage to `REENGAGED`, increments
    `reengagement_count` by one, and supersedes — not invalidates — every one of
    the candidate's assessments currently in `SCHEDULED` or `SCORED`."

    Design: Difficulty/non_linear_state_machine/recruiting_pipeline_cycle_and_reengagement
    """
    set_clock()
    office = new_office()
    candidate, first_assessment = _walk_one_cycle_to_declined(office["id"], "Morgan Supersede")

    first = get_success_data(api_client.get_assessment(first_assessment["id"], ro_headers))
    assert first["status"] == "SUPERSEDED"

    rows = get_success_data(api_client.list_candidate_assessments(candidate["id"], ro_headers))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    assert len(rows) == 1
    assert rows[0]["status"] == "SUPERSEDED"


def test_a_second_cycle_reaches_interview_ready_with_one_superseded_assessment():
    """PRD §3.2: "A superseded assessment therefore does not end the candidate's
    assessment phase; a fresh `SCHEDULED` assessment must be produced before the
    candidate can reach `INTERVIEW_READY` again."

    Design: Difficulty/non_linear_state_machine/recruiting_pipeline_cycle_and_reengagement
    """
    set_clock()
    office = new_office()
    candidate, _ = _walk_one_cycle_to_declined(office["id"], "Morgan Second")

    # Second traversal: REENGAGED -> SCREENED -> ASSESSMENT_PENDING -> ...
    validate_success(api_client.screen_candidate(candidate["id"], ro_headers))
    second = validate_success(api_client.schedule_assessment(
        candidate["id"], {"assessment_version": "V2", "scheduled_date": "2026-09-05T00:00:00Z"},
        ro_headers))
    validate_success(api_client.score_assessment(
        second["id"],
        {"raw_score": 86, "competency_scores": {"MARKET_KNOWLEDGE": 8, "RELATIONSHIP": 9,
                                                "RESILIENCE": 7, "ETHICS": 9}}, ro_headers))
    final_candidate = validate_success(api_client.advance_to_interview(candidate["id"], ro_headers))

    assert final_candidate["stage"] == "INTERVIEW_READY"
    assert final_candidate["reengagement_count"] == 1

    rows = get_success_data(api_client.list_candidate_assessments(candidate["id"], ro_headers))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["SCORED", "SUPERSEDED"], \
        "the cycle must leave exactly one superseded and one scored assessment"


def test_reengagement_does_not_rewrite_the_pipeline_lineage():
    """PRD §3.1: "A re-engagement may name the earlier entry it continues in
    `prior_candidate_id`, which defaults to null."

    Design: Difficulty/non_linear_state_machine/recruiting_pipeline_cycle_and_reengagement
    """
    set_clock()
    office = new_office()
    plain = new_candidate(office["id"], name="Prior Lineage")
    assert plain["prior_candidate_id"] is None

    candidate, _ = _walk_one_cycle_to_declined(office["id"], "Morgan Lineage")
    assert candidate["prior_candidate_id"] is None


def test_a_rejected_candidate_may_also_be_re_engaged():
    """PRD §3.2: "A `RecruitingOfficer` may re-engage a candidate whose stage is
    `OFFER_DECLINED` or `REJECTED`."

    Design: Difficulty/non_linear_state_machine/recruiting_pipeline_cycle_and_reengagement
    """
    set_clock()
    office = new_office()
    other = new_candidate(office["id"], name="Riley Rejecta")
    other = validate_success(api_client.screen_candidate(other["id"], ro_headers))
    # schedule-assessment returns the created SelectionAssessment, not the
    # candidate; keep the candidate reference separate so the reject below
    # still addresses the pipeline entry.
    validate_success(api_client.schedule_assessment(
        other["id"], {"assessment_version": "V2", "scheduled_date": "2026-09-02T00:00:00Z"},
        ro_headers))

    # reject is a DistrictDirector action
    rejected = validate_success(api_client.reject_candidate(other["id"], dd_headers))
    assert rejected["stage"] == "REJECTED"

    reengaged = validate_success(api_client.reengage_candidate(other["id"], ro_headers))
    assert reengaged["stage"] == "REENGAGED"
    assert reengaged["reengagement_count"] == 1