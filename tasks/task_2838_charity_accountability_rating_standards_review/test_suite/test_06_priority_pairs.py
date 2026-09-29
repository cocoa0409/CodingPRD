"""Two requests that violate two admission rules at once."""
from test_helpers import (
    FILING_FY2025,
    NO_IMPACT_GOVERNANCE,
    assert_instant,
    assert_score,
    publish_payload,
    read_cycle,
    read_dimension_scores,
    read_organization,
    read_publication_records,
    setup_cycle_in_org_review,
    setup_scored_cycle,
    submit_filing,
    validate_error,
    validate_filing,
)


def _cycle_with_only_a_rejected_filing():
    """An evaluated cycle whose single fiscal-year filing failed validation."""
    scenario = setup_scored_cycle(filings=[], score=False)
    filing = submit_filing(
        scenario["organization"]["id"], fiscal_year=2025, **FILING_FY2025
    )
    scenario["rejected_filing"] = validate_filing(
        filing["id"], "REJECT", rejection_code="MISSING_SCHEDULE"
    )
    return scenario


def test_the_wrong_analyst_is_told_who_they_are_not_what_the_data_is_missing(
    api, other_analyst_headers
):
    """Scoring someone else's cycle that also has no usable filing reports the identity
    failure, so the state of another analyst's cycle never leaks.

    PRD §2.8: "Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response."

    PRD §2.8: "**Assigned-analyst identity.** The acting `RatingAnalyst`'s `X-User-ID` equals the cycle's `assigned_analyst_user_id`, else `ERR_NOT_ASSIGNED_ANALYST` (403)."

    Design: Difficulty/priority_pair_validation_conflict/wrong_analyst_outranks_missing_validated_filing_on_score
    """
    scenario = _cycle_with_only_a_rejected_filing()
    cycle_before = read_cycle(scenario["cycle"]["id"])

    response = api.score_rating_cycle(cycle_before["id"], other_analyst_headers)
    validate_error(response, "ERR_NOT_ASSIGNED_ANALYST", 403)

    cycle_after = read_cycle(cycle_before["id"])
    assert cycle_after["status"] == "DATA_COLLECTION"
    assert cycle_after["version"] == cycle_before["version"]
    assert read_dimension_scores(cycle_after["id"], scenario["analyst_headers"]) == []


def test_the_assigned_analyst_is_told_the_filing_is_missing_proving_both_rules_were_broken(
    api, analyst_headers
):
    """The same call from the right analyst surfaces the lower-priority data failure,
    which is what shows the first request really violated two rules at once.

    PRD §2.8: "**Filing sufficiency.** At least one `VALIDATED` filing record exists for the cycle's organization and the cycle's own `fiscal_year`, else `ERR_NO_VALIDATED_FILING` (409), on `POST /rating-cycles/{rating_cycle_id}/score`."

    PRD §3.3: "When the candidate set for the cycle's own fiscal year is empty, scoring is refused with `ERR_NO_VALIDATED_FILING`; when it is empty for one of the two preceding fiscal years, that year is simply treated as unavailable, which shrinks the weight pool of the fundraising-efficiency calculation rather than contributing a zero."

    Design: Difficulty/priority_pair_validation_conflict/wrong_analyst_outranks_missing_validated_filing_on_score
    """
    scenario = _cycle_with_only_a_rejected_filing()
    assert scenario["rejected_filing"]["status"] == "REJECTED"

    response = api.score_rating_cycle(
        scenario["cycle"]["id"], scenario["analyst_headers"]
    )
    validate_error(response, "ERR_NO_VALIDATED_FILING", 409)
    assert read_cycle(scenario["cycle"]["id"])["status"] == "DATA_COLLECTION"


def test_publishing_an_incomplete_cycle_reports_completeness_not_the_open_review_window(
    api, reviewer_headers
):
    """A cycle that is both too thin to publish and still inside its correction window
    is refused on completeness, because that check sits above the window check.

    PRD §2.8: "This ordering is observable and is part of the contract: when a request violates two rules at once, the lower-numbered rule's error is the one returned."

    PRD §2.8: "**Completeness gate.** A cycle is published only when its `data_completeness_pct` is at least 60.00, else `ERR_DATA_COMPLETENESS_TOO_LOW` (409), on `POST /rating-cycles/{rating_cycle_id}/publish`."

    Design: Difficulty/priority_pair_validation_conflict/completeness_gate_outranks_publish_window_state_check
    """
    scenario = setup_cycle_in_org_review(
        filings=[(2025, FILING_FY2025)], governance_overrides=NO_IMPACT_GOVERNANCE
    )
    cycle = scenario["cycle"]
    assert_score(cycle["data_completeness_pct"], 58.33, "data_completeness_pct")
    assert cycle["provisional_grade"] == "UNRATED"
    assert cycle["grade"] == "UNRATED"
    assert_instant(
        cycle["correction_deadline_at"], "2026-09-22T00:00:00Z", "correction_deadline_at"
    )

    response = api.publish_rating_cycle(cycle["id"], publish_payload(), reviewer_headers)
    validate_error(response, "ERR_DATA_COMPLETENESS_TOO_LOW", 409)


def test_the_refused_publication_leaves_no_trace_on_the_cycle_or_the_ledger(
    api, reviewer_headers
):
    """Nothing at all is written by the refused publication: the charity's rating stays
    unpublished and its roll-up fields stay empty.

    PRD §2.8: "**Publishability.** A cycle is published only when the logical clock is at or after `correction_deadline_at`, no correction of the cycle is `SUBMITTED` or `UNDER_ANALYST_REVIEW`, and no appeal of the cycle is `FILED` or `PANEL_ASSIGNED`."

    PRD §3.3: "`published_cycle_count` is the number of publication records whose organization is this one, and starts at 0."

    Design: Difficulty/priority_pair_validation_conflict/completeness_gate_outranks_publish_window_state_check
    """
    scenario = setup_cycle_in_org_review(
        filings=[(2025, FILING_FY2025)], governance_overrides=NO_IMPACT_GOVERNANCE
    )
    api.publish_rating_cycle(
        scenario["cycle"]["id"], publish_payload(), reviewer_headers
    )

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "ORG_REVIEW"
    assert cycle["published_at"] is None
    assert cycle["publishing_reviewer_user_id"] is None
    assert (
        read_publication_records(
            scenario["admin_headers"], rating_cycle_id=cycle["id"]
        )
        == []
    )

    organization = read_organization(scenario["organization"]["id"])
    assert organization["published_cycle_count"] == 0
    assert organization["latest_published_score"] is None
    assert organization["latest_published_grade"] is None
