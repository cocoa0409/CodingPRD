"""Operations refused because of the state of a different entity."""
from test_helpers import (
    assert_instant,
    assert_score,
    dimension_by_name,
    evaluate_governance_profile,
    make_public_headers,
    open_org_review,
    override_dimensions,
    read_cycle,
    read_dimension_scores,
    read_governance_profile,
    score_cycle,
    setup_scored_cycle,
    setup_substantiated_complaint,
    validate_error,
)


def test_scoring_is_refused_while_the_cycles_governance_profile_is_still_pending(
    api, analyst_headers
):
    """The cycle is in the right state with complete financial data; scoring is refused
    only because the disclosure beside it has never been evaluated.

    PRD §3.5: "And the cycle must own a governance profile whose `evaluation_status` is `EVALUATED`, else `ERR_GOVERNANCE_NOT_EVALUATED`."

    PRD §3.4: "Recording the disclosure evaluates nothing: the new profile lands with `evaluation_status` `PENDING`, a null `independence_ratio`, a null `evaluated_at`, and `standards_met_count`, `standards_not_met_count`, `standards_waived_count` and `standards_not_applicable_count` all zero."

    Design: Difficulty/cross_entity_state_dependency/score_requires_evaluated_governance_profile
    """
    scenario = setup_scored_cycle(evaluate=False, governance_overrides={}, score=False)
    profile = read_governance_profile(scenario["governance_profile"]["id"])
    assert profile["evaluation_status"] == "PENDING"
    assert profile["standards_met_count"] == 0
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 0

    cycle_before = read_cycle(scenario["cycle"]["id"])
    response = api.score_rating_cycle(cycle_before["id"], scenario["analyst_headers"])
    validate_error(response, "ERR_GOVERNANCE_NOT_EVALUATED", 409)

    cycle_after = read_cycle(cycle_before["id"])
    assert cycle_after["status"] == "DATA_COLLECTION"
    assert cycle_after["version"] == cycle_before["version"]
    assert read_dimension_scores(cycle_after["id"], scenario["analyst_headers"]) == []


def test_evaluating_the_sibling_disclosure_unblocks_the_identical_score_call(
    api, analyst_headers
):
    """Nothing about the cycle changes; evaluating the disclosure beside it is enough to
    let the same scoring call through.

    PRD §3.4: "Evaluation then sets `standards_met_count` to the number of `MET` rows, `standards_not_met_count` to the number of `NOT_MET` rows, `standards_waived_count` to zero, and `standards_not_applicable_count` to the number of `NOT_APPLICABLE` rows — the four counts always partition eight — copies `standards_not_met_count` onto the owning cycle's `failed_standard_count`, advances that cycle's `version` counter by one, moves the profile `PENDING` → `EVALUATED`, stamps `evaluated_at`, and advances the profile's own `version` counter by one."

    Design: Difficulty/cross_entity_state_dependency/score_requires_evaluated_governance_profile
    """
    scenario = setup_scored_cycle(evaluate=False, governance_overrides={}, score=False)
    api.score_rating_cycle(scenario["cycle"]["id"], scenario["analyst_headers"])

    profile = evaluate_governance_profile(
        scenario["governance_profile"]["id"], scenario["analyst_headers"]
    )
    assert profile["evaluation_status"] == "EVALUATED"
    assert profile["standards_met_count"] == 7
    assert profile["standards_not_met_count"] == 1
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 0

    cycle = score_cycle(scenario["cycle"]["id"], scenario["analyst_headers"])
    assert cycle["status"] == "SCORED"
    assert cycle["failed_standard_count"] == 1
    assert_score(cycle["weighted_sum_provisional"], 84.63, "weighted_sum_provisional")
    assert cycle["provisional_grade"] == "MEETS_STANDARDS"


def test_one_stale_child_row_blocks_opening_organization_review(api, analyst_headers):
    """A complaint penalty leaves the accountability row out of date, and the charity is
    not shown figures the system already knows are stale.

    PRD §3.7: "Three conditions gate that move: the cycle must be in `SCORED`, or the request is `ERR_CYCLE_STATE_INVALID`; the acting `X-User-ID` must be the cycle's `assigned_analyst_user_id`, or the request is `ERR_NOT_ASSIGNED_ANALYST`; and no dimension row of the cycle may be `STALE`, or the request is again `ERR_CYCLE_STATE_INVALID` — an organization must never be shown figures the system already knows are out of date."

    Design: Difficulty/cross_entity_state_dependency/open_org_review_blocked_by_stale_dimension_row
    """
    scenario = setup_scored_cycle()
    setup_substantiated_complaint(
        scenario["organization"]["id"],
        penalty_points=5,
        complainant_headers=make_public_headers("donor-1"),
        narrative="the annual appeal spend was never accounted for",
    )

    rows = read_dimension_scores(scenario["cycle"]["id"], analyst_headers)
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    assert accountability["status"] == "STALE"
    assert accountability["raw_points"] == 16
    for name in ("FINANCIAL_HEALTH", "TRANSPARENCY", "IMPACT"):
        assert dimension_by_name(rows, name)["status"] == "COMPUTED"

    response = api.open_org_review(scenario["cycle"]["id"], analyst_headers)
    validate_error(response, "ERR_CYCLE_STATE_INVALID", 409)

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "SCORED"
    assert cycle["review_opened_at"] is None
    assert cycle["correction_deadline_at"] is None


def test_overriding_the_stale_row_clears_the_block_without_a_rescore(api, analyst_headers):
    """The analyst accepts the penalised figure by overriding it, which moves the row
    out of STALE and lets the identical review call through.

    PRD §3.6: "A row previously `COMPUTED` moves `COMPUTED` → `OVERRIDDEN`; a row previously `STALE` moves `STALE` → `OVERRIDDEN`, which lets an analyst override a row a complaint penalty left stale without re-running the whole pipeline; and a row already `OVERRIDDEN` moves `OVERRIDDEN` → `OVERRIDDEN`, overwriting both the earlier `raw_points` and the earlier `override_reason` and `overridden_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/open_org_review_blocked_by_stale_dimension_row
    """
    scenario = setup_scored_cycle()
    setup_substantiated_complaint(
        scenario["organization"]["id"],
        penalty_points=5,
        complainant_headers=make_public_headers("donor-1"),
    )
    accountability = dimension_by_name(
        read_dimension_scores(scenario["cycle"]["id"], analyst_headers), "ACCOUNTABILITY"
    )
    api.open_org_review(scenario["cycle"]["id"], analyst_headers)

    cycle = read_cycle(scenario["cycle"]["id"])
    override_dimensions(
        cycle["id"],
        [{"dimension_score_id": accountability["id"], "raw_points": 16}],
        cycle["version"],
        override_reason="penalised figure accepted by the review panel",
    )

    overridden = dimension_by_name(
        read_dimension_scores(cycle["id"], analyst_headers), "ACCOUNTABILITY"
    )
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["raw_points"] == 16
    assert overridden["penalty_points"] == 5
    assert_score(overridden["normalized_score"], 66.67, "ACCOUNTABILITY normalized_score")

    scored = read_cycle(cycle["id"])
    assert_score(scored["weighted_sum_provisional"], 79.42, "weighted_sum_provisional")
    assert_score(scored["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(
        scored["provisional_composite_score"], 77.92, "provisional_composite_score"
    )

    reviewed = open_org_review(cycle["id"], analyst_headers)
    assert reviewed["status"] == "ORG_REVIEW"
    assert_instant(
        reviewed["correction_deadline_at"],
        "2026-09-22T00:00:00Z",
        "correction_deadline_at",
    )
