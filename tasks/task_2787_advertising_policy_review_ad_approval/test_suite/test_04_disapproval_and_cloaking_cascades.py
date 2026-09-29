"""Two cascades whose last hops land on rows the triggering request never named.

A reviewer's `DISAPPROVE` on one creative can end up expiring a sibling creative's
claimed review task, and a single destination check filed by an integrity analyst can
end up restricting the whole account. Both chains are driven end to end here, hop by
hop, from a state where every earlier hop is already observable.
"""

import pytest

from test_helpers import (
    assert_instant_equals,
    fixtures,
)

SPIRITS = "ALC_SPIRITS"
FIN_CREDIT = "FIN_CREDIT"


# ---------------------------------------------------------------------------
# Shared setup for the manual-disapproval cascade
# ---------------------------------------------------------------------------
def _restricted_account_with_a_held_sibling():
    """A RESTRICTED distiller with cr3's task claimed and cr2's task claimed too.

    cr1 is already disapproved for `MANUAL_REVIEW` and `DESTINATION_MISMATCH`, which
    assessed 6.00 * 1.50 * 1.00 = 9.00 plus 10.00 * 1.50 * 1.25 = 18.75. cr3's task is
    held but untouched, and cr2's claimed task is the trigger each test fires.
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
        legal_name="Cedar Ridge Distillers",
        country_code="US",
        industry_code="ALCOHOL",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["US"],
        display_name="Rev Regulated US",
        max_concurrent_claims=3,
    )
    reviewer_id = reviewer["id"]

    specs = [
        ("Cask strength release", "Our cask strength release ships nationwide today.", "cask"),
        ("Barrel pick event", "Join our barrel pick event and take home a bottle.", "barrel"),
        ("Holiday gift sets", "Holiday gift sets with two reserve bottles included.", "gift"),
    ]
    creatives = [
        fixtures.create_creative(
            advertiser_id,
            [SPIRITS],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.cedarridge.example/{slug}",
            display_url=f"https://www.cedarridge.example/{slug}",
            disclaimer_text="Drink responsibly. 21+",
        )
        for headline, body, slug in specs
    ]
    for creative in creatives:
        submitted = fixtures.submit_creative(creative["id"], advertiser_id)
        fixtures.screen_creative(
            submitted["id"], [(rule["id"], 0.80)], submitted["version"]
        )
    cr1, cr2, cr3 = creatives

    # cr1's landing host diverges from its display host, which is what makes
    # DESTINATION_MISMATCH an admissible reason code on its disapproval.
    fixtures.record_destination_check(
        cr1["id"],
        "https://liquor-deals.example/lp/cask",
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
    )

    task3 = fixtures.only_task_for_creative(cr3["id"])
    fixtures.claim_task(task3["id"], reviewer_id)

    task1 = fixtures.only_task_for_creative(cr1["id"])
    fixtures.claim_task(task1["id"], reviewer_id)
    fixtures.decide_task(
        task1["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW", "DESTINATION_MISMATCH"],
        note="Landing host does not match the display URL.",
    )

    task2 = fixtures.only_task_for_creative(cr2["id"])
    fixtures.claim_task(task2["id"], reviewer_id)
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer_id,
        "cr1": cr1,
        "cr2": cr2,
        "cr3": cr3,
        "task2": task2,
        "task3": task3,
    }


def _fire_second_disapproval(case):
    return fixtures.decide_task(
        case["task2"]["id"],
        case["reviewer_id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Repeat violation on the same account.",
    )


def test_the_disapproval_cascade_walks_notice_ledger_advertiser_and_suspension():
    """PRD §3.7: "Hop two creates a disapproval notice in status `ISSUED` whose
    `decided_by_reviewer_id` is the acting reviewer and whose `reason_codes` are the
    supplied ones."

    PRD §3.7: "Hop three has that notice write a violation ledger entry with `reason`
    `DISAPPROVAL_ASSESSED`, `delta_points` equal to the notice's `assessed_points` and
    `balance_after` set to the advertiser's new raw balance."

    PRD §3.9: "Creating an action moves any existing `ACTIVE` action on the advertiser
    to `SUPERSEDED`, points the new action's `prior_action_id` at it, re-derives
    `account_status` and increments the advertiser's `version` by 1; a `SUSPENSION`
    additionally sweeps the advertiser's creatives to `SUSPENDED_HOLD` and expires their
    review tasks."

    Design: Difficulty/transitive_cascade/manual_disapproval_cascades_six_hops_to_suspension_and_sibling_task_expiry
    """
    case = _restricted_account_with_a_held_sibling()
    advertiser_id = case["advertiser_id"]

    first_notice = fixtures.only_notice_for_creative(case["cr1"]["id"])
    lines = first_notice["assessment_lines"]
    assert len(lines) == 2, f"expected a finding line and an integrity line: {lines}"
    assert lines[0]["policy_rule_code"] == SPIRITS
    assert lines[0]["reason_code"] == "MANUAL_REVIEW"
    assert lines[0]["line_points"] == pytest.approx(9.00, abs=0.01)
    assert lines[1]["policy_rule_code"] is None
    assert lines[1]["reason_code"] == "DESTINATION_MISMATCH"
    assert lines[1]["line_points"] == pytest.approx(18.75, abs=0.01)
    assert first_notice["assessed_points"] == pytest.approx(27.75, abs=0.01)

    before = fixtures.read_advertiser(advertiser_id)
    assert before["violation_points_raw"] == pytest.approx(27.75, abs=0.01)
    assert before["severity_index"] == pytest.approx(31.25, abs=0.01)
    assert before["account_status"] == "RESTRICTED"
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 2

    _fire_second_disapproval(case)

    # Hop one: task and creative.
    task2 = fixtures.read_task(case["task2"]["id"])
    assert task2["status"] == "RESOLVED"
    assert task2["resolution"] == "DISAPPROVE"
    assert (
        fixtures.read_creative(case["cr2"]["id"], advertiser_id=advertiser_id)[
            "review_status"
        ]
        == "DISAPPROVED"
    )

    # Hop two: the notice.
    notice = fixtures.only_notice_for_creative(case["cr2"]["id"])
    assert notice["assessed_points"] == pytest.approx(9.00, abs=0.01)
    assert notice["reason_codes"] == ["MANUAL_REVIEW"]
    assert notice["decided_by_reviewer_id"] == case["reviewer_id"]

    # Hop three: the ledger.
    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 2
    assert [entry["entry_index"] for entry in entries] == [1, 2]
    assert entries[1]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[1]["delta_points"] == pytest.approx(9.00, abs=0.01)
    assert entries[1]["balance_after"] == pytest.approx(36.75, abs=0.01)

    # Hop four: the recomputed advertiser and the new action.
    after = fixtures.read_advertiser(advertiser_id)
    assert after["violation_points_raw"] == pytest.approx(36.75, abs=0.01)
    assert after["violation_points_decayed"] == pytest.approx(36.75, abs=0.01)
    # Zero closed actions, so the base is 36.75 and its tier is 9.00.
    assert after["severity_index"] == pytest.approx(45.75, abs=0.01)

    actions = fixtures.actions_for_advertiser(advertiser_id)
    by_type = {action["action_type"]: action for action in actions}
    assert set(by_type) == {"RESTRICTION", "SUSPENSION"}
    suspension = by_type["SUSPENSION"]
    assert suspension["origin"] == "SYSTEM_CASCADE"
    assert suspension["status"] == "ACTIVE"
    assert suspension["severity_index_at_issue"] == pytest.approx(45.75, abs=0.01)
    assert_instant_equals(
        suspension["effective_until"], "2027-01-28T00:00:00Z", "effective_until"
    )
    assert suspension["prior_action_id"] == by_type["RESTRICTION"]["id"]
    assert by_type["RESTRICTION"]["status"] == "SUPERSEDED"

    # Hop five: the re-derived posture.
    assert after["account_status"] == "SUSPENDED"


def test_the_disapproval_cascade_reaches_an_untouched_sibling_creative():
    """PRD §3.7: "Hop six applies only when that re-derivation lands on `SUSPENDED`:
    the advertiser's sibling creatives are swept to `SUSPENDED_HOLD`, which expires
    their `QUEUED` and `CLAIMED` review tasks and decrements the `claimed_task_count` of
    every reviewer who was holding one."

    PRD §2.11: "`ACCOUNT_ENFORCEMENT` — satisfied when the owning advertiser's
    `account_status` is either `ACTIVE` or `WARNED`."

    Design: Difficulty/transitive_cascade/manual_disapproval_cascades_six_hops_to_suspension_and_sibling_task_expiry
    """
    case = _restricted_account_with_a_held_sibling()
    advertiser_id = case["advertiser_id"]

    held_before = fixtures.read_task(case["task3"]["id"])
    assert held_before["status"] == "CLAIMED"
    assert held_before["assigned_reviewer_id"] == case["reviewer_id"]

    _fire_second_disapproval(case)

    # cr3 was never named by the request that disapproved cr2.
    sibling = fixtures.read_creative(case["cr3"]["id"], advertiser_id=advertiser_id)
    assert sibling["review_status"] == "SUSPENDED_HOLD"
    assert sibling["serving_eligible"] is False
    assert "ACCOUNT_ENFORCEMENT" in sibling["blocking_reason_codes"]

    held_after = fixtures.read_task(case["task3"]["id"])
    assert held_after["status"] == "EXPIRED"
    assert held_after["assigned_reviewer_id"] is None
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 0


# ---------------------------------------------------------------------------
# Shared setup for the cloaking cascade
# ---------------------------------------------------------------------------
def _serving_auto_approved_creative():
    """A creative that auto-approved with no findings and then cleared its destination.

    The single classifier row sits at confidence 0.30, below the rule's manual
    threshold, so the run publishes 0.00 on both scores and mints no review task at
    all. The crawler check then opens the serving gate.
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
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Summit Credit Partners",
        country_code="US",
        industry_code="CONSUMER_CREDIT",
    )
    advertiser_id = advertiser["id"]
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.30)],
        ["US"],
        headline="Balance transfer offer",
        body_text="Move your balance and pay no fee for twelve months.",
        landing_page_url="https://www.summitcredit.example/transfer",
        display_url="https://www.summitcredit.example/transfer",
        disclaimer_text="APR 12.9%-27.9%. Terms apply.",
    )
    crawler_check = fixtures.record_destination_check(
        creative["id"],
        "https://www.summitcredit.example/transfer",
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
    )
    return {
        "rule": rule,
        "advertiser_id": advertiser_id,
        "creative_id": creative["id"],
        "run": run,
        "crawler_check": crawler_check,
    }


def _fire_user_agent_check(case):
    return fixtures.record_destination_check(
        case["creative_id"],
        "https://payday-offers.example/win",
        check_type="RECHECK",
        user_agent_variant="USER",
    )


def test_a_diverging_user_fetch_disapproves_an_auto_approved_creative():
    """PRD §3.8: "Second, the result is `CLOAKING` with `mismatch_detail`
    `UA_DIVERGENCE` when this check's `user_agent_variant` is `USER`, a reference crawler
    check exists, and the host of that reference check's `fetched_final_url` differs from
    the host of this check's `fetched_final_url` — the classic bait-and-switch, where the
    crawler and the human are shown different destinations."

    PRD §3.8: "Hop two forces `review_status` to `DISAPPROVED` and creates a disapproval
    notice whose `reason_codes` is exactly `[CLOAKING]` and whose `decided_by_reviewer_id`
    is null, since no human decided it."

    PRD §3.9: "Each integrity line has a null `policy_rule_code`, the reason code itself
    as its `reason_code`, and as its `line_points` an integrity base weight of 10.00
    multiplied by the creative's strictest multiplier and then multiplied by that reason
    code's reason factor, rounded half-up to 2 decimals."

    Design: Difficulty/transitive_cascade/cloaking_destination_check_cascades_five_hops_from_an_auto_approved_creative
    """
    case = _serving_auto_approved_creative()
    creative_id = case["creative_id"]
    advertiser_id = case["advertiser_id"]

    assert case["run"]["outcome"] == "AUTO_APPROVED"
    assert case["run"]["provisional_risk_score"] == pytest.approx(0.00, abs=0.01)
    assert fixtures.list_tasks_for_creative(creative_id) == []
    assert case["crawler_check"]["result"] == "CLEARED"
    serving = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert serving["destination_status"] == "DESTINATION_CLEARED"
    assert serving["review_status"] == "AUTO_APPROVED"
    assert serving["serving_eligible"] is True

    user_check = _fire_user_agent_check(case)
    assert user_check["result"] == "CLOAKING"
    assert user_check["mismatch_detail"] == "UA_DIVERGENCE"

    caught = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert caught["destination_status"] == "CLOAKING_CONFIRMED"
    assert caught["review_status"] == "DISAPPROVED"

    notice = fixtures.only_notice_for_creative(creative_id)
    assert notice["reason_codes"] == ["CLOAKING"]
    assert notice["decided_by_reviewer_id"] is None
    lines = notice["assessment_lines"]
    # The 0.30 row was BELOW_THRESHOLD, so no finding line exists at all.
    assert len(lines) == 1, f"expected only the CLOAKING integrity line: {lines}"
    assert lines[0]["policy_rule_code"] is None
    assert lines[0]["reason_code"] == "CLOAKING"
    # 10.00 * 1.20 strictest multiplier * 2.00 cloaking factor.
    assert lines[0]["line_points"] == pytest.approx(24.00, abs=0.01)
    assert notice["assessed_points"] == pytest.approx(24.00, abs=0.01)
    assert_instant_equals(
        notice["appeal_deadline_at"], "2026-08-04T00:00:00Z", "appeal_deadline_at"
    )


def test_the_cloaking_cascade_restricts_the_account_and_shuts_the_serving_gate():
    """PRD §3.8: "Hop three has that notice write a violation ledger entry with `reason`
    `DISAPPROVAL_ASSESSED`."

    PRD §3.8: "Hop five lets the refreshed `severity_index` possibly create an
    enforcement action and re-derive `account_status`."

    PRD §2.11: "Four conjuncts are evaluated in this fixed order, and each one that
    fails appends its code to `blocking_reason_codes` in that same order — the array is
    never sorted"

    Design: Difficulty/transitive_cascade/cloaking_destination_check_cascades_five_hops_from_an_auto_approved_creative
    """
    case = _serving_auto_approved_creative()
    creative_id = case["creative_id"]
    advertiser_id = case["advertiser_id"]

    _fire_user_agent_check(case)

    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["delta_points"] == pytest.approx(24.00, abs=0.01)
    assert entries[0]["balance_after"] == pytest.approx(24.00, abs=0.01)
    assert entries[0]["entry_index"] == 1

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_raw"] == pytest.approx(24.00, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(24.00, abs=0.01)
    # 24.00 base with no closed action, plus the 3.50 tier chosen from 24.00.
    assert advertiser["severity_index"] == pytest.approx(27.50, abs=0.01)
    assert advertiser["account_status"] == "RESTRICTED"

    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 1
    action = actions[0]
    assert action["action_type"] == "RESTRICTION"
    assert action["origin"] == "SYSTEM_CASCADE"
    assert action["status"] == "ACTIVE"
    notice = fixtures.only_notice_for_creative(creative_id)
    assert action["source_notice_id"] == notice["id"]
    assert_instant_equals(
        action["effective_until"], "2026-09-30T00:00:00Z", "effective_until"
    )

    caught = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    # 0.00 provisional plus the 40.00 cloaking penalty, with no licence credit.
    assert caught["risk_score_provisional"] == pytest.approx(0.00, abs=0.01)
    assert caught["risk_score_final"] == pytest.approx(40.00, abs=0.01)
    assert caught["serving_eligible"] is False
    assert caught["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
        "ACCOUNT_ENFORCEMENT",
    ]
