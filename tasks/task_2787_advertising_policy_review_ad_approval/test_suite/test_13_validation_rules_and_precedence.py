"""Refusals that read more than the request body, and the fixed order they read it in.

Most of the checks here cannot be decided from the payload alone: a category tier, a
country variation, the owning advertiser's eligibility axis, a destination finding
recorded by somebody else. The rest are about ordering — when one request breaks two
rules at once, exactly one of them is allowed to be reported.
"""

import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PROH_WEAPONS = "PROH_WEAPONS"
GAM_CASINO = "GAM_CASINO"
POL_ISSUE = "POL_ISSUE"
ALC_SPIRITS = "ALC_SPIRITS"
FIN_CREDIT = "FIN_CREDIT"
SUP_HEALTH = "SUP_HEALTH"

UNKNOWN_RULE_ID = "00000000-0000-4000-8000-000000000001"


# ---------------------------------------------------------------------------
# A prohibited finding that stopped short of an automatic disapproval
# ---------------------------------------------------------------------------
def _prohibited_finding_claimed():
    """A claimed STANDARD task whose only finding sits on a PROHIBITED rule.

    The auto threshold is 0.95 and the match came in at 0.50, so the run routed the
    creative to a human instead of disapproving it outright. No country variation
    exists, so the rule's tier alone decides the disposition.
    """
    rule = fixtures.create_policy_rule(
        PROH_WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.95,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Ridgeline Outfitters",
        country_code="US",
        industry_code="SPORTING_GOODS",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev Alvarez", max_concurrent_claims=3
    )
    creative, task = fixtures.claimed_task(
        advertiser["id"],
        [PROH_WEAPONS],
        [(rule["id"], 0.50)],
        reviewer["id"],
        ["US"],
        headline="Range day gear",
        body_text="Range day gear and accessories for the whole season.",
        landing_page_url="https://www.ridgeline.example/range",
        display_url="https://www.ridgeline.example/range",
    )
    return {
        "rule_id": rule["id"],
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "task": task,
    }


def test_a_prohibited_finding_can_be_disapproved_but_never_approved():
    """PRD §3.7: "The hardest gate is first: an `APPROVE` or `APPROVE_WITH_LIMITS`
    verdict is refused outright when any rule matched by a qualifying classifier decision
    of the creative's latest screening run has `category_class` `PROHIBITED`, and equally
    when the strictest disposition of any matched rule is `BLOCKED` for a country the
    decision retains — every element of `target_country_codes` under a plain approval, and
    every element of `limited_country_codes` under a limited approval."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    PRD §3.9: "Each finding line records the matched rule's code as its
    `policy_rule_code`, the source reason as its `reason_code`, and as its `line_points`
    the matched rule's `base_severity_weight` multiplied by the country multiplier of that
    rule for this creative and then multiplied by the reason factor of the source reason,
    rounded half-up to 2 decimals."

    Design: Corner/From Table 4 (Validations)/violation_approving_a_prohibited_category_finding_returns_prohibited_category_blocked
    """
    case = _prohibited_finding_claimed()
    task_id = case["task"]["id"]
    headers = make_reviewer_headers(case["reviewer_id"])

    # The routing decision was ROUTE_MANUAL, so the automatic disapproval clause never
    # fired and the human is the one being stopped here.
    assert case["task"]["status"] == "CLAIMED"
    assert case["task"]["queue"] == "STANDARD"

    validate_error(
        api_client.decide_review_task(
            task_id,
            factories.decide_review_task_payload(
                "APPROVE",
                None,
                None,
                "Attempting to approve a prohibited-category finding.",
            ),
            headers,
        ),
        ApiErrorId.ERR_PROHIBITED_CATEGORY_BLOCKED,
        422,
    )

    refused = fixtures.read_task(task_id)
    assert refused["status"] == "CLAIMED"
    assert refused["resolution"] == "PENDING"
    assert refused["version"] == case["task"]["version"]
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 1
    assert fixtures.list_notices_for_creative(case["creative_id"]) == []

    resolved = fixtures.decide_task(
        task_id,
        case["reviewer_id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Prohibited category confirmed.",
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "DISAPPROVE"

    notice = fixtures.only_notice_for_creative(case["creative_id"])
    assert notice["policy_rule_codes"] == [PROH_WEAPONS]
    # 12.00 weight * 1.00 country multiplier * 1.00 MANUAL_REVIEW factor.
    assert notice["assessment_lines"] == [
        {
            "policy_rule_code": PROH_WEAPONS,
            "reason_code": "MANUAL_REVIEW",
            "line_points": pytest.approx(12.00, abs=0.01),
        }
    ]
    assert notice["assessed_points"] == pytest.approx(12.00, abs=0.01)

    creative = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert creative["review_status"] == "DISAPPROVED"

    advertiser = fixtures.read_advertiser(case["advertiser_id"])
    assert advertiser["severity_index"] == pytest.approx(12.00, abs=0.01)
    assert advertiser["account_status"] == "WARNED"


# ---------------------------------------------------------------------------
# One rule, two countries, two different answers
# ---------------------------------------------------------------------------
def _two_claimed_tasks_diverging_only_on_country():
    """Two claimed tasks on one RESTRICTED rule, one targeting US and one CA.

    The US variation is `ALLOWED_WITH_DISCLAIMER` and the CA variation is `BLOCKED`;
    both multipliers are 1.00 so nothing but the disposition differs.
    """
    rule = fixtures.create_policy_rule(
        GAM_CASINO,
        "RESTRICTED",
        6.00,
        title="Casino gambling",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        rule["id"],
        "US",
        "ALLOWED_WITH_DISCLAIMER",
        requires_disclaimer=True,
        severity_multiplier=1.00,
    )
    fixtures.add_country_override(
        rule["id"], "CA", "BLOCKED", severity_multiplier=1.00
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Riverbend Gaming Inc",
        country_code="US",
        industry_code="GAMING",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"],
        ["US", "CA"],
        display_name="Rev Alvarez",
        max_concurrent_claims=3,
    )
    specs = [
        ("us", "US table games", "Table games and tournaments at our riverfront property.", "Play responsibly. 21+"),
        ("ca", "CA table games", "Table games and tournaments for our Canadian guests.", "Play responsibly. 19+"),
    ]
    creatives = {}
    tasks = {}
    for key, headline, body, disclaimer in specs:
        creative, task = fixtures.claimed_task(
            advertiser["id"],
            [GAM_CASINO],
            [(rule["id"], 0.50)],
            reviewer["id"],
            [key.upper()],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.riverbend.example/{key}",
            display_url=f"https://www.riverbend.example/{key}",
            disclaimer_text=disclaimer,
        )
        creatives[key] = creative
        tasks[key] = task
    return {
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creatives": creatives,
        "tasks": tasks,
    }


def test_the_blocked_country_variation_alone_decides_which_approval_lands():
    """PRD §3.1: "The **strictest disposition** of a rule for a creative is the harshest
    of those dispositions across the creative's target countries, where harshness runs
    `BLOCKED` first, then `RESTRICTED_CERT_REQUIRED`, then `ALLOWED_WITH_DISCLAIMER`, then
    `ALLOWED`."

    PRD §3.7: "Either way the refusal is `ERR_PROHIBITED_CATEGORY_BLOCKED` (HTTP 422)."

    PRD §3.7: "All three resolving branches — `APPROVE`, `APPROVE_WITH_LIMITS` and
    `DISAPPROVE` — require that the task is `CLAIMED`, that `assigned_reviewer_id` equals
    the acting `X-User-ID`, and that the creative's `review_status` is
    `PENDING_MANUAL_REVIEW`; each advances the task `CLAIMED → RESOLVED`, writes the
    chosen `resolution`, decrements the holder's `claimed_task_count` by 1, increments the
    reviewer's `version` by 1, increments the task's `version` by 1, and drives the
    matching move on the creative's review axis together with that move's full cascade."

    Design: Corner/From Table 4 (Validations)/satisfaction_a_country_override_decides_whether_the_same_restricted_rule_is_approvable
    """
    case = _two_claimed_tasks_diverging_only_on_country()
    reviewer_id = case["reviewer_id"]

    approved_task = fixtures.decide_task(
        case["tasks"]["us"]["id"],
        reviewer_id,
        "APPROVE",
        note="US disposition allows the category with a disclaimer.",
    )
    assert approved_task["status"] == "RESOLVED"
    us_creative = fixtures.read_creative(
        case["creatives"]["us"]["id"], advertiser_id=case["advertiser_id"]
    )
    assert us_creative["review_status"] == "AUTO_APPROVED"

    validate_error(
        api_client.decide_review_task(
            case["tasks"]["ca"]["id"],
            factories.decide_review_task_payload(
                "APPROVE",
                None,
                None,
                "Attempting to approve a country whose disposition is BLOCKED.",
            ),
            make_reviewer_headers(reviewer_id),
        ),
        ApiErrorId.ERR_PROHIBITED_CATEGORY_BLOCKED,
        422,
    )

    ca_creative = fixtures.read_creative(
        case["creatives"]["ca"]["id"], advertiser_id=case["advertiser_id"]
    )
    assert ca_creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert fixtures.read_task(case["tasks"]["ca"]["id"])["status"] == "CLAIMED"

    # The resolved US task gave its slot back; the refused CA task never gave up its own.
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1

    for key in ("us", "ca"):
        assert fixtures.list_notices_for_creative(case["creatives"][key]["id"]) == []


# ---------------------------------------------------------------------------
# Eligibility that lives on the advertiser, not on the request
# ---------------------------------------------------------------------------
def _political_task_claimed_without_eligibility():
    """A claimed POLITICAL task whose owner has never asked for political eligibility.

    The single match came in at 0.30 against a 0.55 manual threshold, so the run has no
    qualifying decision at all; the creative reached a human purely because
    `political_flag` is true.
    """
    rule = fixtures.create_policy_rule(
        POL_ISSUE,
        "REGULATED",
        5.00,
        title="Political and social issue advertising",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Civic Voice Committee",
        country_code="US",
        industry_code="POLITICAL_COMMITTEE",
    )
    assert advertiser["political_eligibility_status"] == "NOT_REQUESTED"
    reviewer = fixtures.create_reviewer(
        ["POLITICAL"], ["US"], display_name="Rev Okafor", max_concurrent_claims=2
    )
    creative, task = fixtures.claimed_task(
        advertiser["id"],
        [POL_ISSUE],
        [(rule["id"], 0.30)],
        reviewer["id"],
        ["US"],
        headline="Vote yes on measure four",
        body_text="Measure four funds neighbourhood transit repairs across the county.",
        landing_page_url="https://www.civicvoice.example/measure4",
        display_url="https://www.civicvoice.example/measure4",
        political_flag=True,
        disclaimer_text="Paid for by Civic Voice Committee",
    )
    assert task["queue"] == "POLITICAL"
    return {
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "task": task,
    }


def test_the_same_approval_is_refused_then_accepted_as_the_owner_becomes_eligible():
    """PRD §3.7: "Next, approving a creative whose `political_flag` is true while the
    owning advertiser's `political_eligibility_status` is anything other than `ELIGIBLE` is
    refused with `ERR_POLITICAL_ELIGIBILITY_MISSING` (HTTP 422)."

    PRD §3.2: "Recording an outcome writes the one matching status field and increments
    the advertiser's `version` by 1."

    PRD §3.7: "On success the task becomes `RESOLVED` with `resolution` `APPROVE`, a
    political creative gains exactly one archive entry, and the creative's
    `risk_score_final`, `serving_eligible` and `blocking_reason_codes` are recomputed
    before its `version` increments by 1."

    PRD §3.7: "Its `archived_at` is the logical clock and its `retention_until` is
    `archived_at` plus 2555 whole days, which is exactly seven 365-day years; nothing is
    ever deleted before that instant, and in fact no endpoint deletes or mutates an archive
    entry at all."

    Design: Corner/From Table 4 (Validations)/cross_entity_political_eligibility_is_read_from_the_advertiser_at_decision_time
    """
    case = _political_task_claimed_without_eligibility()
    task_id = case["task"]["id"]
    approval = factories.decide_review_task_payload(
        "APPROVE", None, None, "Attempting an approval before eligibility is recorded."
    )

    validate_error(
        api_client.decide_review_task(
            task_id, approval, make_reviewer_headers(case["reviewer_id"])
        ),
        ApiErrorId.ERR_POLITICAL_ELIGIBILITY_MISSING,
        422,
    )

    refused = fixtures.read_task(task_id)
    assert refused["status"] == "CLAIMED"
    assert refused["version"] == case["task"]["version"]
    assert fixtures.archive_entries_for_creative(case["creative_id"]) == []

    # Nothing about the creative or the task changes; only the owner's axis moves.
    advertiser = fixtures.record_verification(
        case["advertiser_id"], "POLITICAL_ELIGIBILITY", "ELIGIBLE"
    )
    assert advertiser["political_eligibility_status"] == "ELIGIBLE"

    validate_success(
        api_client.decide_review_task(
            task_id, approval, make_reviewer_headers(case["reviewer_id"])
        )
    )

    assert fixtures.read_task(task_id)["status"] == "RESOLVED"
    creative = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert creative["review_status"] == "AUTO_APPROVED"

    entries = fixtures.archive_entries_for_creative(case["creative_id"])
    assert len(entries) == 1
    assert_instant_equals(
        entries[0]["archived_at"], "2026-08-01T00:00:00Z", "archived_at"
    )
    assert_instant_equals(
        entries[0]["retention_until"], "2033-07-30T00:00:00Z", "retention_until"
    )
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 0


# ---------------------------------------------------------------------------
# A validity interval that never opens
# ---------------------------------------------------------------------------
def _licence_holder_awaiting_a_window():
    """A spirits rule and the advertiser that will try to licence itself against it."""
    rule = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    fixtures.record_verification(advertiser["id"], "IDENTITY", "VERIFIED")
    return rule["id"], advertiser["id"]


def _certification_attempt(advertiser_id, rule_id, valid_from, valid_until, license_number):
    """One certification submission by the holding advertiser."""
    return api_client.create_certification(
        factories.create_certification_payload(
            advertiser_id,
            rule_id,
            valid_from,
            valid_until,
            "US",
            license_number=license_number,
        ),
        make_advertiser_headers(advertiser_id),
    )


def test_a_zero_length_validity_window_is_refused_exactly_like_a_reversed_one():
    """PRD §3.5: "The interval is inclusive at `valid_from` and exclusive at
    `valid_until`, and `valid_until` must be strictly after `valid_from` — a submission
    where it is equal or earlier is refused with `ERR_INVALID_VALIDITY_WINDOW` (HTTP 422)."

    PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    Design: Corner/From Table 4 (Validations)/temporal_a_certification_window_that_does_not_move_forward_is_rejected
    """
    rule_id, advertiser_id = _licence_holder_awaiting_a_window()

    validate_error(
        _certification_attempt(
            advertiser_id,
            rule_id,
            "2026-09-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
            "TTB-NL-ZERO",
        ),
        ApiErrorId.ERR_INVALID_VALIDITY_WINDOW,
        422,
    )
    validate_error(
        _certification_attempt(
            advertiser_id,
            rule_id,
            "2026-10-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
            "TTB-NL-REVERSED",
        ),
        ApiErrorId.ERR_INVALID_VALIDITY_WINDOW,
        422,
    )

    # One second forward is a real interval, so the same shape of request now lands.
    accepted = validate_success(
        _certification_attempt(
            advertiser_id,
            rule_id,
            "2026-09-01T00:00:00Z",
            "2026-09-01T00:00:01Z",
            "TTB-NL-VALID",
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["revocation_reason"] is None

    _rows, pagination = validate_paginated(
        api_client.list_certifications(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert pagination["total_count"] == 1, "a rejected window must leave no row behind"


# ---------------------------------------------------------------------------
# A ceiling that only the collection can breach
# ---------------------------------------------------------------------------
def _three_queued_tasks_under_a_ceiling_of_two():
    """Three QUEUED STANDARD tasks and the one reviewer allowed to hold two of them."""
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev Alvarez", max_concurrent_claims=2
    )
    specs = [
        ("Offer one", "The first of three credit offers submitted for review.", "one"),
        ("Offer two", "The second of three credit offers submitted for review.", "two"),
        ("Offer three", "The third of three credit offers submitted for review.", "three"),
    ]
    tasks = []
    for headline, body, slug in specs:
        _creative, task = fixtures.creative_in_manual_review(
            advertiser["id"],
            [FIN_CREDIT],
            [(rule["id"], 0.50)],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.beaconlending.example/{slug}",
            display_url=f"https://www.beaconlending.example/{slug}",
        )
        tasks.append(task)
    return reviewer["id"], tasks


def test_only_the_claim_past_the_ceiling_is_refused_and_a_release_reopens_it():
    """PRD §3.6: "Capacity comes last: the reviewer's `claimed_task_count` must be
    strictly less than their `max_concurrent_claims`, and a reviewer already at their
    ceiling is refused with `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409) — an aggregate
    check, in that each held task is individually legal while the collection may not exceed
    the ceiling."

    PRD §2.8: "A reviewer's `claimed_task_count` tracks exactly how many of their tasks
    are currently held, and is conserved by the claim/release pair."

    PRD §3.6: "Release deliberately does *not* recompute `priority_score` or
    `sla_deadline_at` — the task returns to its queue holding the position and the deadline
    it already had, so releasing is not a way to buy time."

    Design: Corner/From Table 4 (Validations)/aggregate_reviewer_capacity_rejects_only_the_claim_past_the_ceiling
    """
    reviewer_id, tasks = _three_queued_tasks_under_a_ceiling_of_two()
    first, second, third = tasks

    fixtures.claim_task(first["id"], reviewer_id)
    fixtures.claim_task(second["id"], reviewer_id)
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2

    validate_error(
        api_client.claim_review_task(third["id"], make_reviewer_headers(reviewer_id)),
        ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED,
        409,
    )
    refused = fixtures.read_task(third["id"])
    assert refused["status"] == "QUEUED"
    assert refused["assigned_reviewer_id"] is None
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2

    released = fixtures.release_task(second["id"], reviewer_id)
    assert released["status"] == "QUEUED"
    assert released["assigned_reviewer_id"] is None
    assert released["claimed_at"] is None
    # A release is not an escalation cycle and buys no time.
    assert released["cycle_count"] == 0
    assert released["priority_score"] == pytest.approx(
        second["priority_score"], abs=0.01
    )
    assert released["sla_deadline_at"] == second["sla_deadline_at"]
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1

    reclaimed = validate_success(
        api_client.claim_review_task(third["id"], make_reviewer_headers(reviewer_id))
    )
    assert reclaimed["status"] == "CLAIMED"
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2


# ---------------------------------------------------------------------------
# A disclosure demand that only one of two rules makes
# ---------------------------------------------------------------------------
def _two_bare_creatives_under_two_rules():
    """Two claimed tasks on disclaimer-free creatives, one per rule.

    `SUP_HEALTH` sets `requires_disclaimer` false and `ALC_SPIRITS` sets it true;
    neither rule carries a country variation, so the flag on the rule is the only thing
    that can separate the two approvals.
    """
    supplements = fixtures.create_policy_rule(
        SUP_HEALTH,
        "REGULATED",
        3.00,
        title="Health supplements",
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    spirits = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=False,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Wellspring Commerce Inc",
        country_code="US",
        industry_code="RETAIL",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev Alvarez", max_concurrent_claims=2
    )
    specs = [
        (
            "supplements",
            supplements["id"],
            SUP_HEALTH,
            "Daily greens",
            "Our daily greens supplement supports everyday wellness routines.",
            "greens",
        ),
        (
            "spirits",
            spirits["id"],
            ALC_SPIRITS,
            "Cask finish",
            "Our cask finish spirit is bottled in limited numbers each season.",
            "cask",
        ),
    ]
    creatives = {}
    tasks = {}
    for key, rule_id, code, headline, body, slug in specs:
        creative, task = fixtures.claimed_task(
            advertiser["id"],
            [code],
            [(rule_id, 0.50)],
            reviewer["id"],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.wellspring.example/{slug}",
            display_url=f"https://www.wellspring.example/{slug}",
        )
        assert creative["disclaimer_text"] is None
        assert creative["political_flag"] is False
        creatives[key] = creative
        tasks[key] = task
    return {
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creatives": creatives,
        "tasks": tasks,
    }


def test_a_missing_disclaimer_only_blocks_the_rule_that_demands_one():
    """PRD §3.7: "Next, approving while `disclaimer_text` is null or empty is refused with
    `ERR_POLITICAL_DISCLOSURE_MISSING` (HTTP 422) whenever disclosure is demanded — that
    is, whenever `political_flag` is true, or any matched rule has `requires_disclaimer`
    true, or any retained country's variation on a matched rule has `requires_disclaimer`
    true."

    PRD §3.1: "Two booleans state what an approval demands: `requires_certification`,
    which when true means an approval of a matched creative must be backed by a covering
    licence, and `requires_disclaimer`, which when true means an approval demands non-empty
    disclosure text on the creative."

    PRD §3.7: "`APPROVE` advances `PENDING_MANUAL_REVIEW → AUTO_APPROVED`."

    Design: Corner/From Table 4 (Validations)/conditional_disclaimer_is_demanded_only_when_a_matched_rule_or_country_requires_one
    """
    case = _two_bare_creatives_under_two_rules()
    reviewer_id = case["reviewer_id"]

    fixtures.decide_task(
        case["tasks"]["supplements"]["id"],
        reviewer_id,
        "APPROVE",
        note="No disclosure is demanded for this category.",
    )
    supplements = fixtures.read_creative(
        case["creatives"]["supplements"]["id"], advertiser_id=case["advertiser_id"]
    )
    assert supplements["review_status"] == "AUTO_APPROVED"

    # The refusal names a political error id on a creative that is not political at all.
    validate_error(
        api_client.decide_review_task(
            case["tasks"]["spirits"]["id"],
            factories.decide_review_task_payload(
                "APPROVE",
                None,
                None,
                "Attempting to approve a disclaimer-bearing category with no disclaimer.",
            ),
            make_reviewer_headers(reviewer_id),
        ),
        ApiErrorId.ERR_POLITICAL_DISCLOSURE_MISSING,
        422,
    )

    spirits = fixtures.read_creative(
        case["creatives"]["spirits"]["id"], advertiser_id=case["advertiser_id"]
    )
    assert spirits["review_status"] == "PENDING_MANUAL_REVIEW"
    assert fixtures.read_task(case["tasks"]["spirits"]["id"])["status"] == "CLAIMED"
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1


# ---------------------------------------------------------------------------
# A reason code that only a destination finding can justify
# ---------------------------------------------------------------------------
def _claimed_task_with_an_untested_destination():
    """A claimed STANDARD task whose destination axis is still `DESTINATION_PENDING`."""
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev Alvarez", max_concurrent_claims=3
    )
    creative, task = fixtures.claimed_task(
        advertiser["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.70)],
        reviewer["id"],
        ["US"],
        headline="Redirected offer",
        body_text="An offer whose landing page later resolves to a partner host.",
        landing_page_url="https://www.beaconlending.example/redirect",
        display_url="https://www.beaconlending.example/redirect",
    )
    assert creative["destination_status"] == "DESTINATION_PENDING"
    return {
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "task_id": task["id"],
    }


def test_destination_mismatch_becomes_an_admissible_reason_only_once_it_is_proven():
    """PRD §3.7: "First the supplied `reason_codes` are checked against the creative's
    current state, and each code has its own precondition: `CLOAKING` demands that
    `destination_status` is `CLOAKING_CONFIRMED`; `DESTINATION_MISMATCH` demands that
    `destination_status` is `MISMATCH_FLAGGED`; `POLITICAL_DISCLOSURE` demands that
    `political_flag` is true; `CERT_MISSING` demands that at least one matched rule has
    `requires_certification` true; `MANUAL_REVIEW` is always permitted; and
    `AUTO_SCREENING` is never permitted on a reviewer's decision, since it is reserved for
    system-issued notices."

    PRD §3.8: "Third, the result is `MISMATCH` with `mismatch_detail` `HOST_MISMATCH`
    when the host of the check's `fetched_final_url` differs from the host of the creative's
    `display_url`, which is the declared reference host."

    PRD §3.8: "A creative already sitting in `PENDING_MANUAL_REVIEW` keeps the review task
    it already has and gains no second one, and a creative in `DISAPPROVED` or
    `SUSPENDED_HOLD` has its review axis left alone entirely."

    PRD §3.9: "Each integrity line has a null `policy_rule_code`, the reason code itself
    as its `reason_code`, and as its `line_points` an integrity base weight of 10.00
    multiplied by the creative's strictest multiplier and then multiplied by that reason
    code's reason factor, rounded half-up to 2 decimals."

    Design: Corner/From Table 4 (Validations)/cascading_reason_code_consistency_is_checked_against_the_live_destination_axis
    """
    case = _claimed_task_with_an_untested_destination()
    task_id = case["task_id"]
    headers = make_reviewer_headers(case["reviewer_id"])
    mismatch_payload = factories.decide_review_task_payload(
        "DISAPPROVE",
        ["MANUAL_REVIEW", "DESTINATION_MISMATCH"],
        None,
        "Claiming a mismatch before any destination evidence exists.",
    )

    validate_error(
        api_client.decide_review_task(task_id, mismatch_payload, headers),
        ApiErrorId.ERR_INVALID_REASON_CODE,
        422,
    )
    validate_error(
        api_client.decide_review_task(
            task_id,
            factories.decide_review_task_payload(
                "DISAPPROVE",
                ["AUTO_SCREENING"],
                None,
                "Claiming an automated reason on a human decision.",
            ),
            headers,
        ),
        ApiErrorId.ERR_INVALID_REASON_CODE,
        422,
    )
    assert fixtures.list_notices_for_creative(case["creative_id"]) == []
    assert fixtures.read_task(task_id)["status"] == "CLAIMED"

    check = fixtures.record_destination_check(
        case["creative_id"], "https://partner-lp.example/redirect"
    )
    assert check["result"] == "MISMATCH"
    assert check["mismatch_detail"] == "HOST_MISMATCH"

    flagged = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert flagged["destination_status"] == "MISMATCH_FLAGGED"
    assert flagged["review_status"] == "PENDING_MANUAL_REVIEW"
    assert len(fixtures.list_tasks_for_creative(case["creative_id"])) == 1
    assert fixtures.read_task(task_id)["status"] == "CLAIMED"

    validate_success(
        api_client.decide_review_task(task_id, mismatch_payload, headers)
    )

    notice = fixtures.only_notice_for_creative(case["creative_id"])
    assert notice["reason_codes"] == ["MANUAL_REVIEW", "DESTINATION_MISMATCH"]
    assert notice["policy_rule_codes"] == [FIN_CREDIT]
    # 4.00 * 1.00 * 1.00 for the finding, then 10.00 * 1.00 * 1.25 for the integrity line.
    assert notice["assessment_lines"] == [
        {
            "policy_rule_code": FIN_CREDIT,
            "reason_code": "MANUAL_REVIEW",
            "line_points": pytest.approx(4.00, abs=0.01),
        },
        {
            "policy_rule_code": None,
            "reason_code": "DESTINATION_MISMATCH",
            "line_points": pytest.approx(12.50, abs=0.01),
        },
    ]
    assert notice["assessed_points"] == pytest.approx(16.50, abs=0.01)

    assert (
        fixtures.read_creative(
            case["creative_id"], advertiser_id=case["advertiser_id"]
        )["review_status"]
        == "DISAPPROVED"
    )
    advertiser = fixtures.read_advertiser(case["advertiser_id"])
    assert advertiser["severity_index"] == pytest.approx(16.50, abs=0.01)
    assert advertiser["account_status"] == "WARNED"


# ---------------------------------------------------------------------------
# Catalogue rules that are business checks rather than type checks
# ---------------------------------------------------------------------------
def test_threshold_inversion_and_duplicate_codes_leave_the_catalogue_untouched():
    """PRD §3.1: "Their *ordering* is a separate business rule rather than a type
    constraint: the auto-disapprove threshold must be strictly greater than the manual
    threshold, and a rule submitted with an auto-disapprove threshold less than or equal to
    the manual threshold is rejected with `ERR_INVALID_THRESHOLD_ORDER` (HTTP 422)."

    PRD §3.1: "Registering a rule whose `code` already exists is rejected with
    `ERR_DUPLICATE_POLICY_CODE` (HTTP 409)."

    PRD §3.1: "At most one variation may exist for any one rule and country: a second
    attempt on the same pair is rejected with `ERR_DUPLICATE_POLICY_CODE` (HTTP 409)."

    PRD §3.1: "Attaching a variation increments the parent rule's `country_override_count`
    by 1 and advances the rule's `version` by 1."

    Design: Corner/From Table 4 (Validations)/violation_policy_rule_creation_rejects_threshold_inversion_and_duplicate_codes
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
    )
    fixtures.add_country_override(
        rule["id"], "US", "ALLOWED", severity_multiplier=1.50
    )

    # Equal thresholds are structurally fine but break the ordering rule, so this is a
    # 422 business refusal and not a 400 body-shape refusal.
    validate_error(
        api_client.create_policy_rule(
            factories.create_policy_rule_payload(
                SUP_HEALTH,
                "REGULATED",
                3.00,
                title="Health supplements",
                confidence_auto_disapprove_threshold=0.50,
                confidence_manual_threshold=0.50,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_THRESHOLD_ORDER,
        422,
    )

    validate_error(
        api_client.create_policy_rule(
            factories.create_policy_rule_payload(
                FIN_CREDIT,
                "REGULATED",
                9.00,
                title="Consumer credit offers, second attempt",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_POLICY_CODE,
        409,
    )

    # The same error id also guards the rule-and-country pair.
    validate_error(
        api_client.create_country_override(
            rule["id"],
            factories.create_country_override_payload(
                "US", "BLOCKED", severity_multiplier=2.00
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_POLICY_CODE,
        409,
    )

    _rows, pagination = validate_paginated(api_client.list_policy_rules(ADMIN))
    assert pagination["total_count"] == 1

    stored = fixtures.read_policy_rule(rule["id"])
    assert stored["country_override_count"] == 1
    assert stored["version"] == 2


# ---------------------------------------------------------------------------
# The head of the precedence ladder
# ---------------------------------------------------------------------------
def test_the_role_check_is_reported_ahead_of_the_body_and_pagination_checks():
    """PRD §2.1: "A syntactically valid request whose role is not among those authorized
    for the addressed operation — the authorized set for each operation is given in the §4
    table — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.10: "4. Request-body shape: valid JSON, no unknown fields, every required
    field present, and every value satisfying its declared type, enum membership, string
    length, decimal precision, non-empty-array and no-duplicate-element constraints, and
    the `https://` prefix requirement on URL fields — `ERR_INVALID_REQUEST`."

    PRD §2.3: "A `limit` outside the range 1 through 100, a non-integer `limit`, a
    negative `offset`, or a non-integer `offset` is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    PRD §2.10: "The ordering places safety and compliance ahead of capacity, because a
    prohibited-category ad must be refused even when the queue is full:"

    Design: Corner/From Table 4 (Validations)/priority_ordering_the_role_check_outranks_body_validation_on_the_same_request
    """
    fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )

    # This body is missing `title`, `category_class` and `base_severity_weight`, yet the
    # role check is the one that gets to answer.
    validate_error(
        api_client.create_policy_rule(
            {"code": "BAD_CODE"}, make_reviewer_headers("reviewer-not-yet-created")
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    validate_error(
        api_client.list_policy_rules(ADMIN, {"limit": 500}),
        ApiErrorId.ERR_INVALID_PAGINATION,
        400,
    )

    # With the role check satisfied, the body check does run.
    validate_error(
        api_client.create_policy_rule(
            {
                "code": SUP_HEALTH,
                "category_class": "REGULATED",
                "base_severity_weight": 3.00,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _rows, pagination = validate_paginated(api_client.list_policy_rules(ADMIN))
    assert pagination["total_count"] == 1


def test_an_unknown_path_id_is_reported_ahead_of_an_unknown_body_foreign_key():
    """PRD §2.5: "Each identifier position has its own dedicated not-found error, all of
    them HTTP 404: an unresolvable `advertiser_id` yields `ERR_ADVERTISER_NOT_FOUND`, an
    unresolvable `ad_creative_id` yields `ERR_AD_CREATIVE_NOT_FOUND`, an unresolvable
    `policy_rule_id` yields `ERR_POLICY_RULE_NOT_FOUND`, an unresolvable `reviewer_id`
    yields `ERR_REVIEWER_NOT_FOUND`, an unresolvable `screening_run_id` yields
    `ERR_SCREENING_RUN_NOT_FOUND`, an unresolvable `review_task_id` yields
    `ERR_REVIEW_TASK_NOT_FOUND`, an unresolvable `certification_id` yields
    `ERR_CERTIFICATION_NOT_FOUND`, an unresolvable `disapproval_notice_id` yields
    `ERR_DISAPPROVAL_NOTICE_NOT_FOUND`, an unresolvable `appeal_id` yields
    `ERR_APPEAL_NOT_FOUND`, and an unresolvable `enforcement_action_id` yields
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND`."

    PRD §2.5: "The same discipline applies to foreign keys arriving in a request body."

    PRD §3.4: "Every `policy_rule_id` in `decisions` is checked in submitted order and
    the first unresolvable one rejects the entire run with `ERR_POLICY_RULE_NOT_FOUND`,
    leaving no run and no decisions behind."

    PRD §2.10: "6. Resolution of path identifiers, left to right, as described in §2.5."

    PRD §2.10: "7. Resolution of foreign keys supplied in the body, as described in §2.5."

    Design: Corner/From Table 4 (Validations)/priority_ordering_path_id_resolution_outranks_body_foreign_key_resolution
    """
    fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    creative = fixtures.create_creative(
        advertiser["id"],
        [FIN_CREDIT],
        ["US"],
        headline="Real creative",
        body_text="A real creative used as the control for the two not-found paths.",
        landing_page_url="https://www.beaconlending.example/real",
        display_url="https://www.beaconlending.example/real",
    )
    submitted = fixtures.submit_creative(creative["id"], advertiser["id"])

    payload = factories.create_screening_run_payload(
        [
            factories.classifier_decision_payload(
                UNKNOWN_RULE_ID, 0.50, "unknown on unknown"
            )
        ],
        submitted["version"],
        "clf-2026.07",
    )

    # Both identifiers are unresolvable; the path one is the only one reported.
    validate_error(
        api_client.create_screening_run(NON_EXISTENT_UUID, payload, ADMIN),
        ApiErrorId.ERR_AD_CREATIVE_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_screening_run(creative["id"], payload, ADMIN),
        ApiErrorId.ERR_POLICY_RULE_NOT_FOUND,
        404,
    )

    assert fixtures.runs_for_creative(creative["id"]) == []
    assert (
        fixtures.read_creative(creative["id"], advertiser_id=advertiser["id"])[
            "screening_run_count"
        ]
        == 0
    )
