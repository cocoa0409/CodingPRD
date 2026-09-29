"""Three multi-term formulas whose composition is the whole point.

Priority takes the *larger* of two components rather than their sum, a notice's
assessment rounds every line before adding them up, and the severity index picks
its escalation surcharge from the pre-surcharge base index and never revisits that
choice. Each test drives the inputs so that the wrong composition would produce a
different, recognisable number.
"""

import pytest

from test_helpers import (
    assert_instant_equals,
    fixtures,
)

WEAPONS = "WEAPONS_FIREARMS"
SPIRITS = "ALC_SPIRITS"
POLITICAL = "POLITICAL_ISSUE"
TOBACCO = "TOBACCO_VAPE"
SUPPLEMENTS = "SUPPLEMENTS_CLAIMS"
GAMBLING = "GAMBLING_ONLINE"


# ---------------------------------------------------------------------------
# Shared setup for the priority-composition pair
# ---------------------------------------------------------------------------
def _political_framework():
    """Three rules plus their country variations, ready for a political advertiser."""
    weapons = fixtures.create_policy_rule(
        WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(weapons["id"], "SE", "BLOCKED", severity_multiplier=2.00)
    fixtures.add_country_override(
        weapons["id"], "US", "RESTRICTED_CERT_REQUIRED", severity_multiplier=1.00
    )
    spirits = fixtures.create_policy_rule(
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
    fixtures.add_country_override(spirits["id"], "SE", "BLOCKED", severity_multiplier=2.00)
    fixtures.add_country_override(
        spirits["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    political = fixtures.create_policy_rule(
        POLITICAL,
        "REGULATED",
        5.00,
        title="Political and social issue advertising",
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.95,
        confidence_manual_threshold=0.60,
        review_sla_hours=12,
        default_queue="POLITICAL",
    )
    fixtures.add_country_override(
        political["id"], "US", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.00
    )
    return weapons, spirits, political


def _advertiser_with_2880_decayed_points(weapons, spirits, political):
    """An unverified advertiser carrying 28.80 decayed points and one live creative.

    Two Swedish-targeted creatives are auto-disapproved at confidence 0.95, which
    assesses 12.00 * 2.00 * 0.80 = 19.20 and then 6.00 * 2.00 * 0.80 = 9.60. The
    third creative is authored up front, while the account is still `ACTIVE`, and is
    only submitted once the history is in place.
    """
    advertiser = fixtures.create_advertiser(
        legal_name="Harbor Civic Media Inc",
        country_code="US",
        industry_code="POLITICAL_CONSULTING",
    )
    advertiser_id = advertiser["id"]
    creative_a = fixtures.create_creative(
        advertiser_id,
        [WEAPONS],
        ["SE", "US"],
        headline="Rifle range membership drive",
        body_text="Join our rifle range and shoot every weekend.",
        landing_page_url="https://www.harborcivic.example/range",
        display_url="https://www.harborcivic.example",
    )
    creative_b = fixtures.create_creative(
        advertiser_id,
        [SPIRITS],
        ["SE", "US"],
        headline="Nordic single malt tasting",
        body_text="Book a single malt tasting flight this weekend.",
        landing_page_url="https://www.harborcivic.example/malt",
        display_url="https://www.harborcivic.example",
        disclaimer_text="Drink responsibly. 20+",
    )
    creative_c = fixtures.create_creative(
        advertiser_id,
        [POLITICAL, SPIRITS],
        ["US"],
        headline="Vote yes on the harbor levy",
        body_text="Support the harbor levy and toast the win with local spirits.",
        landing_page_url="https://www.harborcivic.example/levy",
        display_url="https://www.harborcivic.example",
        political_flag=True,
    )
    for creative, rule in ((creative_a, weapons), (creative_b, spirits)):
        submitted = fixtures.submit_creative(creative["id"], advertiser_id)
        fixtures.screen_creative(
            submitted["id"], [(rule["id"], 0.95)], submitted["version"]
        )
    return advertiser_id, creative_c


def test_priority_takes_the_larger_component_and_never_their_sum():
    """PRD §3.6: "Take the *larger* of the severity component and the history
    component; the two are alternatives, never a sum."

    PRD §3.6: "Add the queue base, the larger of the two components, the
    verification gap and the disclosure gap; round the total half-up to 2 decimals
    and cap it at 100.00."

    Design: Difficulty/combinatorial_formula/priority_score_nested_max_over_severity_and_history_with_two_conditional_gaps
    """
    weapons, spirits, political = _political_framework()
    advertiser_id, creative_c = _advertiser_with_2880_decayed_points(
        weapons, spirits, political
    )
    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_decayed"] == pytest.approx(28.80, abs=0.01)

    submitted = fixtures.submit_creative(creative_c["id"], advertiser_id)
    run = fixtures.screen_creative(
        submitted["id"],
        [(political["id"], 0.70), (spirits["id"], 0.60)],
        submitted["version"],
    )
    assert run["outcome"] == "ROUTED_MANUAL"

    task = fixtures.only_task_for_creative(creative_c["id"])
    # Severity component 5.00 * 1.50 * 2.00 = 15.00 beats the history component
    # floor(28.80 / 10.00) * 5.00 = 10.00, so 60.00 + 15.00 + 10.00 + 12.00.
    assert task["priority_score"] == pytest.approx(97.00, abs=0.01)
    # Summing the two components instead would reach 107.00 and clamp to the cap.
    assert task["priority_score"] != pytest.approx(100.00, abs=0.01)
    assert task["queue"] == "POLITICAL"
    assert task["primary_policy_rule_id"] == political["id"]


def test_priority_pins_both_conditional_gaps_and_the_primary_rule_deadline():
    """PRD §3.6: "Then add a verification gap of 10.00 when the advertiser's
    `identity_status` is anything other than `VERIFIED` or its
    `business_standing_status` is anything other than `VERIFIED`, and 0.00
    otherwise."

    PRD §3.6: "Then add a disclosure gap of 12.00 when the creative's
    `political_flag` is true while its `disclaimer_text` is null or the empty
    string, and 0.00 otherwise."

    PRD §3.6: "The deadline `sla_deadline_at` is the task's `created_at` plus the
    primary rule's `review_sla_hours`, or plus 48 hours when the task has no primary
    rule."

    Design: Difficulty/combinatorial_formula/priority_score_nested_max_over_severity_and_history_with_two_conditional_gaps
    """
    weapons, spirits, political = _political_framework()
    advertiser_id, creative_c = _advertiser_with_2880_decayed_points(
        weapons, spirits, political
    )
    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["identity_status"] != "VERIFIED"
    assert creative_c["political_flag"] is True
    assert creative_c["disclaimer_text"] is None

    submitted = fixtures.submit_creative(creative_c["id"], advertiser_id)
    run = fixtures.screen_creative(
        submitted["id"],
        [(political["id"], 0.70), (spirits["id"], 0.60)],
        submitted["version"],
    )
    # 5.00 * 1.00 * 0.70 + 6.00 * 1.50 * 0.60, summed unrounded and rounded once.
    assert run["provisional_risk_score"] == pytest.approx(8.90, abs=0.01)

    task = fixtures.only_task_for_creative(creative_c["id"])
    # Both gaps land: 60.00 queue base + 15.00 larger component + 10.00 + 12.00.
    assert task["priority_score"] == pytest.approx(97.00, abs=0.01)
    # Dropping either gap would leave 87.00 or 85.00 on the row.
    assert task["priority_score"] != pytest.approx(87.00, abs=0.01)
    assert task["priority_score"] != pytest.approx(85.00, abs=0.01)
    # POLITICAL_ISSUE carries review_sla_hours 12 and the clock starts at midnight.
    assert_instant_equals(
        task["sla_deadline_at"], "2026-08-01T12:00:00Z", "sla_deadline_at"
    )
    assert task["cycle_count"] == 0
    assert task["status"] == "QUEUED"


def test_priority_falls_back_to_the_history_component_when_it_is_the_larger():
    """PRD §3.6: "Compute a history component from the owning advertiser's decayed
    points balance: divide `violation_points_decayed` by 10.00, discard the
    fractional part, multiply the whole number by 5.00, and cap the result at 15.00
    — so every complete ten decayed points buys five priority points, up to three
    steps."

    PRD §3.6: "Compute a severity component: 0.00 when the task has no
    `primary_policy_rule_id`, and otherwise the primary rule's
    `base_severity_weight` multiplied by the creative's strictest multiplier and
    then multiplied by 2.00, that product rounded half-up to 2 decimals and then
    capped at 30.00."

    Design: Difficulty/combinatorial_formula/priority_score_nested_max_over_severity_and_history_with_two_conditional_gaps
    """
    weapons = fixtures.create_policy_rule(
        WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(weapons["id"], "SE", "BLOCKED", severity_multiplier=2.00)
    light = fixtures.create_policy_rule(
        SUPPLEMENTS,
        "REGULATED",
        2.00,
        title="Supplement efficacy claims",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Baltic Outfitters AB",
        country_code="SE",
        industry_code="SPORTING_GOODS",
    )
    advertiser_id = advertiser["id"]
    heavy = fixtures.create_creative(
        advertiser_id,
        [WEAPONS],
        ["SE"],
        headline="Hunting rifles in stock",
        body_text="Our hunting rifles are back in stock this season.",
        landing_page_url="https://www.balticoutfitters.example/rifles",
        display_url="https://www.balticoutfitters.example",
    )
    mild = fixtures.create_creative(
        advertiser_id,
        [SUPPLEMENTS],
        ["US"],
        headline="Trail recovery powder",
        body_text="Our recovery powder helps you hike further every day.",
        landing_page_url="https://www.balticoutfitters.example/powder",
        display_url="https://www.balticoutfitters.example",
    )
    submitted_heavy = fixtures.submit_creative(heavy["id"], advertiser_id)
    fixtures.screen_creative(
        submitted_heavy["id"], [(weapons["id"], 0.95)], submitted_heavy["version"]
    )
    assert fixtures.read_advertiser(advertiser_id)[
        "violation_points_decayed"
    ] == pytest.approx(19.20, abs=0.01)

    submitted_mild = fixtures.submit_creative(mild["id"], advertiser_id)
    fixtures.screen_creative(
        submitted_mild["id"], [(light["id"], 0.60)], submitted_mild["version"]
    )
    task = fixtures.only_task_for_creative(mild["id"])
    # History floor(19.20 / 10.00) * 5.00 = 5.00 beats severity 2.00 * 1.00 * 2.00
    # = 4.00, so 30.00 + 5.00 + 10.00 verification gap and no disclosure gap.
    assert task["queue"] == "STANDARD"
    assert task["primary_policy_rule_id"] == light["id"]
    assert task["priority_score"] == pytest.approx(45.00, abs=0.01)
    # Summing the components would give 49.00; taking severity alone gives 44.00.
    assert task["priority_score"] != pytest.approx(49.00, abs=0.01)
    assert task["priority_score"] != pytest.approx(44.00, abs=0.01)


# ---------------------------------------------------------------------------
# Shared setup for the assessment-rounding pair
# ---------------------------------------------------------------------------
def _german_wellness_case():
    """A DE creative matching two rules whose lines round in the third decimal.

    Both rules carry a DE variation with `severity_multiplier` 1.15, so the
    `MANUAL_REVIEW` lines are 4.02 * 1.15 = 4.623 and 6.02 * 1.15 = 6.923 — figures
    whose rounding order is observable to the cent.
    """
    tobacco = fixtures.create_policy_rule(
        TOBACCO,
        "RESTRICTED",
        6.02,
        title="Tobacco and vaping products",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        tobacco["id"], "DE", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.15
    )
    supplements = fixtures.create_policy_rule(
        SUPPLEMENTS,
        "REGULATED",
        4.02,
        title="Supplement efficacy claims",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        supplements["id"], "DE", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.15
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Rheinvale Wellness GmbH",
        country_code="DE",
        industry_code="SUPPLEMENTS",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["DE"], display_name="Rev Standard DE", max_concurrent_claims=3
    )
    creative, run = fixtures.screened_creative(
        advertiser["id"],
        [TOBACCO, SUPPLEMENTS],
        [(tobacco["id"], 0.60), (supplements["id"], 0.60)],
        ["DE"],
        headline="Vape kits and immunity boosters",
        body_text="Our vape kits and immunity boosters cure fatigue fast.",
        landing_page_url="https://www.rheinvale.example/kits",
        display_url="https://www.rheinvale.example",
    )
    task = fixtures.only_task_for_creative(creative["id"])
    fixtures.claim_task(task["id"], reviewer["id"])
    fixtures.decide_task(
        task["id"],
        reviewer["id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Unsupported health claims alongside a vaping offer.",
    )
    return {
        "tobacco": tobacco,
        "supplements": supplements,
        "advertiser": advertiser,
        "reviewer": reviewer,
        "creative": creative,
        "run": run,
        "task": task,
    }


def test_each_assessment_line_is_rounded_before_the_lines_are_summed():
    """PRD §3.9: "The rounding order here is pinned and is the opposite of the
    risk-score order: each line is rounded to 2 decimals **before** the sum, and the
    already-rounded lines are then added — summing unrounded products and rounding
    once at the end is not what this rule does, and the two orders can differ by a
    cent."

    PRD §3.9: "Each finding line records the matched rule's code as its
    `policy_rule_code`, the source reason as its `reason_code`, and as its
    `line_points` the matched rule's `base_severity_weight` multiplied by the country
    multiplier of that rule for this creative and then multiplied by the reason factor
    of the source reason, rounded half-up to 2 decimals."

    Design: Difficulty/combinatorial_formula/disapproval_assessment_rounds_each_line_before_summing
    """
    case = _german_wellness_case()
    notice = fixtures.only_notice_for_creative(case["creative"]["id"])

    assert notice["decided_by_reviewer_id"] == case["reviewer"]["id"]
    lines = notice["assessment_lines"]
    assert len(lines) == 2, f"expected exactly two finding lines, got {lines}"
    # Phase one takes the qualifying decisions in ascending order of the rule code.
    assert lines[0]["policy_rule_code"] == SUPPLEMENTS
    assert lines[0]["reason_code"] == "MANUAL_REVIEW"
    assert lines[0]["line_points"] == pytest.approx(4.62, abs=0.01)
    assert lines[1]["policy_rule_code"] == TOBACCO
    assert lines[1]["reason_code"] == "MANUAL_REVIEW"
    assert lines[1]["line_points"] == pytest.approx(6.92, abs=0.01)
    # 4.62 + 6.92, not round(4.623 + 6.923).
    assert notice["assessed_points"] == pytest.approx(11.54, abs=0.01)
    assert notice["assessed_points"] != pytest.approx(11.55, abs=0.01)


def test_the_risk_score_rounds_once_on_the_sum_unlike_the_assessment():
    """PRD §3.4: "For each finding, take the matched rule's `base_severity_weight`,
    multiply it by the country multiplier of that rule for this creative, and multiply
    the result by the finding's own `confidence`; keep each of those products
    unrounded, add them all together, round the single total half-up to 2 decimals,
    and cap the outcome at 100.00."

    PRD §3.5: "Its `primary_policy_rule_id` is null when no decision in the run
    reached `AUTO_DISAPPROVE` or `ROUTE_MANUAL`; otherwise it is the rule of the
    qualifying decision ranked by `confidence` descending, ties broken by that rule's
    `code` ascending — and since codes are unique the ranking is total."

    Design: Difficulty/combinatorial_formula/disapproval_assessment_rounds_each_line_before_summing
    """
    case = _german_wellness_case()
    # 6.02 * 1.15 * 0.60 + 4.02 * 1.15 * 0.60 = 6.9276, rounded once to 6.93 —
    # rounding each product first would leave 4.15 + 2.77 = 6.92.
    # The two candidate values are exactly one cent apart, so the tolerance must be
    # narrower than a cent for the pair of assertions to discriminate at all. PRD §2.6
    # pins these to "exactly 2 decimal places", so half a cent is the faithful window.
    assert case["run"]["provisional_risk_score"] == pytest.approx(6.93, abs=0.005)
    assert case["run"]["provisional_risk_score"] != pytest.approx(6.92, abs=0.005)
    assert case["task"]["queue"] == "STANDARD"
    # Confidence ties on 0.60, so the ascending rule code decides.
    assert case["task"]["primary_policy_rule_id"] == case["supplements"]["id"]

    advertiser_id = case["advertiser"]["id"]
    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["delta_points"] == pytest.approx(11.54, abs=0.01)
    assert entries[0]["balance_after"] == pytest.approx(11.54, abs=0.01)

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_raw"] == pytest.approx(11.54, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(11.54, abs=0.01)
    # No closed action yet, and 11.54 sits below the 20.00 surcharge tier.
    assert advertiser["severity_index"] == pytest.approx(11.54, abs=0.01)
    assert advertiser["account_status"] == "WARNED"

    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "WARNING"
    assert actions[0]["origin"] == "SYSTEM_CASCADE"
    assert_instant_equals(
        actions[0]["effective_until"], "2026-08-31T00:00:00Z", "effective_until"
    )


# ---------------------------------------------------------------------------
# Shared setup for the surcharge-tier pair
# ---------------------------------------------------------------------------
def _lakeshore_case():
    """Three manual disapprovals that walk the account up to a live `RESTRICTION`.

    Spirits lines assess 6.00 * 1.50 = 9.00 and gambling lines 4.00 * 1.20 = 4.80,
    so the raw balance climbs 9.00, 18.00, 22.80. The fourth creative is authored and
    claimed but not yet decided, and its disapproval is each test's trigger.
    """
    spirits = fixtures.create_policy_rule(
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
        spirits["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    gambling = fixtures.create_policy_rule(
        GAMBLING,
        "RESTRICTED",
        4.00,
        title="Online gambling",
        requires_certification=True,
        confidence_auto_disapprove_threshold=0.88,
        confidence_manual_threshold=0.35,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        gambling["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        severity_multiplier=1.20,
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Lakeshore Leisure Corp",
        country_code="US",
        industry_code="GAMING",
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
        (spirits, 0.80, "Bourbon flight of the month", "Drink responsibly. 21+"),
        (spirits, 0.80, "Rye tasting club", "Drink responsibly. 21+"),
        (gambling, 0.50, "Play our slots tonight", None),
        (gambling, 0.50, "Weekend poker tables", None),
    ]
    creatives = []
    for index, (rule, _confidence, headline, disclaimer) in enumerate(specs):
        extras = {"disclaimer_text": disclaimer} if disclaimer else {}
        creatives.append(
            fixtures.create_creative(
                advertiser_id,
                [rule["code"]],
                ["US"],
                headline=headline,
                body_text=f"{headline} at Lakeshore Leisure, licensed and legal.",
                landing_page_url=f"https://www.lakeshore.example/offer-{index}",
                display_url="https://www.lakeshore.example",
                **extras,
            )
        )

    for creative, (rule, confidence, _headline, _disclaimer) in list(
        zip(creatives, specs)
    )[:3]:
        submitted = fixtures.submit_creative(creative["id"], advertiser_id)
        fixtures.screen_creative(
            submitted["id"], [(rule["id"], confidence)], submitted["version"]
        )
        task = fixtures.only_task_for_creative(creative["id"])
        fixtures.claim_task(task["id"], reviewer_id)
        fixtures.decide_task(
            task["id"],
            reviewer_id,
            "DISAPPROVE",
            reason_codes=["MANUAL_REVIEW"],
            note="Unlicensed regulated offer for the retained country.",
        )

    last = creatives[3]
    submitted_last = fixtures.submit_creative(last["id"], advertiser_id)
    fixtures.screen_creative(
        submitted_last["id"], [(gambling["id"], 0.50)], submitted_last["version"]
    )
    last_task = fixtures.only_task_for_creative(last["id"])
    fixtures.claim_task(last_task["id"], reviewer_id)
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer_id,
        "creatives": creatives,
        "pending_task": last_task,
    }


def test_the_surcharge_tier_is_keyed_on_the_base_index_alone():
    """PRD §3.9: "Step two picks an escalation surcharge keyed on the base index
    *alone*: 0.00 when the base index is below 20.00, 3.50 when it is at least 20.00
    but below 35.00, and 9.00 when it is 35.00 or more."

    PRD §3.9: "The tier chosen in step two is never re-chosen after the surcharge is
    added, even when the finished index lands in a higher tier — that re-evaluation is
    expressly not part of this rule."

    PRD §3.9: "Step one computes a base index: count the advertiser's enforcement
    actions whose `status` is `SUPERSEDED`, `LIFTED` or `EXPIRED` — actions still in
    force are excluded, so a currently effective action never inflates its own
    successor's index — multiply that closed-action count by 5.00, add the
    advertiser's `violation_points_decayed`, and round the total half-up to 2
    decimals."

    Design: Difficulty/combinatorial_formula/enforcement_surcharge_tier_locked_on_base_index_never_re_evaluated
    """
    case = _lakeshore_case()
    advertiser_id = case["advertiser_id"]

    before = fixtures.read_advertiser(advertiser_id)
    assert before["violation_points_raw"] == pytest.approx(22.80, abs=0.01)
    # 22.80 base plus the 3.50 tier chosen from 22.80.
    assert before["severity_index"] == pytest.approx(26.30, abs=0.01)
    assert before["account_status"] == "RESTRICTED"

    fixtures.decide_task(
        case["pending_task"]["id"],
        case["reviewer_id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Fourth unlicensed regulated offer on the same account.",
    )

    after = fixtures.read_advertiser(advertiser_id)
    assert after["violation_points_raw"] == pytest.approx(27.60, abs=0.01)
    assert after["violation_points_decayed"] == pytest.approx(27.60, abs=0.01)
    # One SUPERSEDED action closes a chapter: base = 5.00 + 27.60 = 32.60, whose tier
    # is 3.50, giving 36.10. Re-reading the tier off 36.10 would add 9.00 instead.
    assert after["severity_index"] == pytest.approx(36.10, abs=0.01)
    assert after["severity_index"] != pytest.approx(41.60, abs=0.01)


def test_an_index_reaching_the_suspension_band_raises_no_suspension():
    """PRD §3.9: "Step four selects an action type keyed on the post-surcharge
    `severity_index`: `SUSPENSION` when it is at least 40.00, otherwise `RESTRICTION`
    when it is at least 25.00, otherwise `WARNING` when it is at least 10.00, and
    otherwise none at all."

    PRD §3.9: "An **enforcement action** is created from that selection only when an
    action type was selected and either no action is currently in force on the
    advertiser or the selected type is strictly more severe than the type of the action
    in force, severity running warning, then restriction, then suspension."

    Design: Difficulty/combinatorial_formula/enforcement_surcharge_tier_locked_on_base_index_never_re_evaluated
    """
    case = _lakeshore_case()
    advertiser_id = case["advertiser_id"]

    fixtures.decide_task(
        case["pending_task"]["id"],
        case["reviewer_id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Fourth unlicensed regulated offer on the same account.",
    )

    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 2, f"expected exactly two actions, got {actions}"
    by_type = {action["action_type"]: action for action in actions}
    assert set(by_type) == {"WARNING", "RESTRICTION"}
    assert by_type["WARNING"]["status"] == "SUPERSEDED"
    assert by_type["RESTRICTION"]["status"] == "ACTIVE"
    # The finished index of 36.10 stops short of the 40.00 suspension threshold.
    assert [a for a in actions if a["action_type"] == "SUSPENSION"] == []

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["account_status"] == "RESTRICTED"
    for creative in case["creatives"]:
        row = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
        assert row["review_status"] != "SUSPENDED_HOLD"
    assert (
        fixtures.read_creative(case["creatives"][0]["id"], advertiser_id=advertiser_id)[
            "review_status"
        ]
        == "DISAPPROVED"
    )
    assert (
        fixtures.read_creative(case["creatives"][2]["id"], advertiser_id=advertiser_id)[
            "review_status"
        ]
        == "DISAPPROVED"
    )
