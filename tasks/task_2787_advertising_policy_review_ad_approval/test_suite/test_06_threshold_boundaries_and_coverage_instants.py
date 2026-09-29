"""One hundredth of a point, and one second, decide entirely different outcomes.

The two confidence thresholds on a policy rule are inclusive lower bounds, and a
certification's validity interval is inclusive at its start and exclusive at its end.
Each test pairs the value exactly on the boundary with the value one step away from it
and shows the branch flipping.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_success,
)

SPIRITS = "ALC_SPIRITS"


def _spirits_rule():
    """ALC_SPIRITS with an auto threshold of 0.90 and a manual threshold of 0.55."""
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
    fixtures.add_country_override(rule["id"], "SE", "BLOCKED", severity_multiplier=2.00)
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    return rule


def _four_creatives_awaiting_screening():
    """Four submitted creatives: two targeting SE and US, two targeting US alone."""
    rule = _spirits_rule()
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Belmont Cellars Inc",
        country_code="US",
        industry_code="ALCOHOL",
    )
    advertiser_id = advertiser["id"]
    specs = [
        ("Reserve cask offer", "Reserve cask offer with worldwide spirits delivery.", "h", ["SE", "US"]),
        ("Reserve cask offer encore", "Encore of the reserve cask offer for spirits lovers.", "l", ["SE", "US"]),
        ("Cellar tour tickets", "Book cellar tour tickets and taste our range.", "t55", ["US"]),
        ("Cellar tour gift cards", "Gift cards for our cellar tour experience.", "t54", ["US"]),
    ]
    creatives = [
        fixtures.create_creative(
            advertiser_id,
            [SPIRITS],
            countries,
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.belmontcellars.example/{slug}",
            display_url=f"https://www.belmontcellars.example/{slug}",
            disclaimer_text="Drink responsibly. 21+",
        )
        for headline, body, slug, countries in specs
    ]
    submitted = [
        fixtures.submit_creative(creative["id"], advertiser_id)
        for creative in creatives
    ]
    return {"rule": rule, "advertiser_id": advertiser_id, "submitted": submitted}


def test_the_auto_disapprove_threshold_is_an_inclusive_lower_bound():
    """PRD §3.4: "Comparing the decision's `confidence` against the thresholds of the
    rule it matched, and treating every threshold as an inclusive lower bound, the
    decision's `disposition` is `AUTO_DISAPPROVE` when `confidence` is at least that
    rule's `confidence_auto_disapprove_threshold`, otherwise `ROUTE_MANUAL` when
    `confidence` is at least that rule's `confidence_manual_threshold`, and otherwise
    `BELOW_THRESHOLD`."

    PRD §3.4: "First, the outcome is `AUTO_DISAPPROVED` when some decision in the run
    has disposition `AUTO_DISAPPROVE` and the strictest disposition of that decision's
    rule for this creative is `BLOCKED`."

    Design: Difficulty/boundary_precision_check/classifier_confidence_exactly_at_each_threshold_takes_the_inclusive_branch
    """
    case = _four_creatives_awaiting_screening()
    rule_id = case["rule"]["id"]
    advertiser_id = case["advertiser_id"]
    high, low = case["submitted"][0], case["submitted"][1]

    run_high = fixtures.screen_creative(high["id"], [(rule_id, 0.90)], high["version"])
    decision_high = fixtures.decisions_for_run(run_high["id"])[0]
    assert decision_high["disposition"] == "AUTO_DISAPPROVE"
    # 6.00 * 2.00 * 0.90 as the per-row audit figure.
    assert decision_high["assessed_points"] == pytest.approx(10.80, abs=0.01)
    assert run_high["outcome"] == "AUTO_DISAPPROVED"
    assert run_high["provisional_risk_score"] == pytest.approx(10.80, abs=0.01)
    assert (
        fixtures.read_creative(high["id"], advertiser_id=advertiser_id)["review_status"]
        == "DISAPPROVED"
    )
    notice = fixtures.only_notice_for_creative(high["id"])
    assert notice["reason_codes"] == ["AUTO_SCREENING"]
    assert notice["assessed_points"] == pytest.approx(9.60, abs=0.01)

    run_low = fixtures.screen_creative(low["id"], [(rule_id, 0.89)], low["version"])
    decision_low = fixtures.decisions_for_run(run_low["id"])[0]
    # One hundredth below the threshold takes the next branch down.
    assert decision_low["disposition"] == "ROUTE_MANUAL"
    assert decision_low["assessed_points"] == pytest.approx(10.68, abs=0.01)
    assert run_low["outcome"] == "ROUTED_MANUAL"
    assert (
        fixtures.read_creative(low["id"], advertiser_id=advertiser_id)["review_status"]
        == "PENDING_MANUAL_REVIEW"
    )
    assert fixtures.list_notices_for_creative(low["id"]) == []


def test_the_manual_threshold_is_an_inclusive_lower_bound():
    """PRD §3.4: "Risk scoring runs off the same evidence but with a narrower input set:
    only the decision rows of the creative's *latest* run count, and among those only the
    rows whose `confidence` is at least the `confidence_manual_threshold` of the rule they
    matched."

    PRD §3.4: "Sixth and last, the outcome is `AUTO_APPROVED` — and that includes a run
    whose `decisions` produced only `BELOW_THRESHOLD` rows."

    PRD §3.4: "This per-row `assessed_points` is an audit figure only; it is never summed
    to produce a risk score, because summing already-rounded rows is the wrong rounding
    order for that purpose."

    Design: Difficulty/boundary_precision_check/classifier_confidence_exactly_at_each_threshold_takes_the_inclusive_branch
    """
    case = _four_creatives_awaiting_screening()
    rule_id = case["rule"]["id"]
    advertiser_id = case["advertiser_id"]
    at_threshold, below = case["submitted"][2], case["submitted"][3]

    run_at = fixtures.screen_creative(
        at_threshold["id"], [(rule_id, 0.55)], at_threshold["version"]
    )
    assert fixtures.decisions_for_run(run_at["id"])[0]["disposition"] == "ROUTE_MANUAL"
    assert run_at["outcome"] == "ROUTED_MANUAL"
    # 6.00 * 1.50 * 0.55, with the row inside the scoring input set.
    assert run_at["provisional_risk_score"] == pytest.approx(4.95, abs=0.01)
    tasks = fixtures.list_tasks_for_creative(at_threshold["id"])
    assert len(tasks) == 1
    assert tasks[0]["queue"] == "REGULATED_CERT"

    run_below = fixtures.screen_creative(
        below["id"], [(rule_id, 0.54)], below["version"]
    )
    decision_below = fixtures.decisions_for_run(run_below["id"])[0]
    assert decision_below["disposition"] == "BELOW_THRESHOLD"
    # The audit figure is still written even though the row scores nothing.
    assert decision_below["assessed_points"] == pytest.approx(4.86, abs=0.01)
    assert run_below["outcome"] == "AUTO_APPROVED"
    assert run_below["provisional_risk_score"] == pytest.approx(0.00, abs=0.01)
    assert (
        fixtures.read_creative(below["id"], advertiser_id=advertiser_id)["review_status"]
        == "AUTO_APPROVED"
    )
    assert fixtures.list_tasks_for_creative(below["id"]) == []

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_raw"] == pytest.approx(0.00, abs=0.01)
    assert advertiser["account_status"] == "ACTIVE"
    assert fixtures.actions_for_advertiser(advertiser_id) == []


# ---------------------------------------------------------------------------
# Shared setup for the half-open coverage window
# ---------------------------------------------------------------------------
def _two_claimed_tasks_one_second_before_the_licence_lapses():
    """Two identical US spirits creatives claimed at 2026-08-09T23:59:59Z.

    The holder's only licence runs to 2026-08-10T00:00:00Z, so the coverage predicate
    still answers yes at the claim instant and answers no exactly one second later.
    """
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
        legal_name="Foxglen Spirits Co",
        country_code="US",
        industry_code="ALCOHOL",
    )
    advertiser_id = advertiser["id"]
    certification = fixtures.create_certification(
        advertiser_id,
        rule["id"],
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-08-10T00:00:00Z",
        issuing_country_code="US",
        license_number="ABC-US-2026-4410",
        headers=make_advertiser_headers(advertiser_id),
    )
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["US"],
        display_name="Rev Regulated US",
        max_concurrent_claims=2,
    )
    specs = [
        ("Summer gin flight", "Our summer gin flight is available for local pickup.", "gin"),
        ("Autumn rum flight", "Our autumn rum flight is available for local pickup.", "rum"),
    ]
    creatives = []
    for headline, body, slug in specs:
        creative, run = fixtures.screened_creative(
            advertiser_id,
            [SPIRITS],
            [(rule["id"], 0.80)],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.foxglen.example/{slug}",
            display_url=f"https://www.foxglen.example/{slug}",
            disclaimer_text="Drink responsibly. 21+",
        )
        assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
        assert creative["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
        creatives.append(creative)
    early, late = creatives
    task_early = fixtures.only_task_for_creative(early["id"])
    task_late = fixtures.only_task_for_creative(late["id"])

    fixtures.set_clock("2026-08-09T23:59:59Z")
    fixtures.claim_task(task_early["id"], reviewer["id"])
    fixtures.claim_task(task_late["id"], reviewer["id"])
    return {
        "advertiser_id": advertiser_id,
        "certification_id": certification["id"],
        "reviewer_id": reviewer["id"],
        "early_id": early["id"],
        "late_id": late["id"],
        "task_early_id": task_early["id"],
        "task_late_id": task_late["id"],
    }


def _limited_approval_response(task_id, reviewer_id):
    """The one request both halves of this pair send, byte for byte."""
    return api_client.decide_review_task(
        task_id,
        factories.decide_review_task_payload(
            "APPROVE_WITH_LIMITS",
            None,
            ["US"],
            "Licensed for US only.",
        ),
        make_reviewer_headers(reviewer_id),
    )


def test_one_second_before_valid_until_the_licence_still_covers_the_approval():
    """PRD §3.5: "The candidate set for that question is every certification whose
    `advertiser_id` is the creative's owner, whose `policy_rule_id` is the rule in
    question, whose `issuing_country_code` equals the country in question, whose `status`
    is `ACTIVE`, and whose interval contains the instant — that is, `valid_from` at or
    before the instant and the instant strictly before `valid_until`."

    PRD §3.7: "On success the creative's `limited_country_codes` is written from the
    request sorted ascending, its `approved_under_certification_id` is written from the
    coverage selection — the candidate ranked first by `valid_until` descending with ties
    broken by `created_at` ascending — the task becomes `RESOLVED` with `resolution`
    `APPROVE_WITH_LIMITS`, a political creative gains exactly one archive entry, and
    `risk_score_final`, `serving_eligible` and `blocking_reason_codes` are recomputed
    before the creative's `version` increments by 1."

    Design: Difficulty/boundary_precision_check/certification_coverage_empty_at_exact_valid_until_instant_blocks_limited_approval
    """
    case = _two_claimed_tasks_one_second_before_the_licence_lapses()

    validate_success(_limited_approval_response(case["task_early_id"], case["reviewer_id"]))

    approved = fixtures.read_creative(
        case["early_id"], advertiser_id=case["advertiser_id"]
    )
    assert approved["review_status"] == "APPROVED_LIMITED"
    assert approved["limited_country_codes"] == ["US"]
    assert approved["approved_under_certification_id"] == case["certification_id"]
    # 7.20 provisional plus no destination penalty less the 8.00 credit, floored.
    assert approved["risk_score_final"] == pytest.approx(0.00, abs=0.01)
    assert approved["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)

    task = fixtures.read_task(case["task_early_id"])
    assert task["status"] == "RESOLVED"
    assert task["resolution"] == "APPROVE_WITH_LIMITS"


def test_at_exactly_valid_until_the_identical_approval_is_refused():
    """PRD §3.7: "Every retained country that demands a licence — because a matched
    rule's `requires_certification` is true, or because that country's variation on a
    matched rule has `requires_license` true — must have a non-empty coverage candidate
    set at the logical clock, and a shortfall is refused with `ERR_CERTIFICATION_MISSING`
    (HTTP 422)."

    PRD §3.5: "The sweep's second phase moves a certification whose `valid_until` has
    been reached or passed to `EXPIRED`, from either `SUBMITTED` or `ACTIVE`."

    Design: Difficulty/boundary_precision_check/certification_coverage_empty_at_exact_valid_until_instant_blocks_limited_approval
    """
    case = _two_claimed_tasks_one_second_before_the_licence_lapses()

    validate_success(_limited_approval_response(case["task_early_id"], case["reviewer_id"]))

    fixtures.set_clock("2026-08-10T00:00:00Z")
    validate_error(
        _limited_approval_response(case["task_late_id"], case["reviewer_id"]),
        ApiErrorId.ERR_CERTIFICATION_MISSING,
        422,
    )

    # No sweep has run, so the row itself is untouched: the refusal came from the
    # half-open interval predicate alone.
    assert fixtures.read_certification(case["certification_id"])["status"] == "ACTIVE"

    refused = fixtures.read_creative(
        case["late_id"], advertiser_id=case["advertiser_id"]
    )
    assert refused["review_status"] == "PENDING_MANUAL_REVIEW"
    assert refused["limited_country_codes"] == []
    assert refused["approved_under_certification_id"] is None
    assert refused["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)

    assert fixtures.read_task(case["task_late_id"])["status"] == "CLAIMED"
    # Only the successful decision released a claim.
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 1
