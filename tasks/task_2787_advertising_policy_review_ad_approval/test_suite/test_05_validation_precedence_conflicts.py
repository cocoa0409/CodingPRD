"""Requests that break two rules at once, and the single error each may report.

Every scenario here is built so that two numbered entries of the precedence order are
violated by one call. Each test asserts the winning error, and a companion call proves
the losing rule was genuinely live rather than simply unimplemented.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
)

SUPPLEMENTS = "SUPPLEMENTS_CLAIMS"
WEAPONS = "WEAPONS_FIREARMS"
POLITICAL = "POLITICAL_ISSUE"
SPIRITS = "ALC_SPIRITS"


# ---------------------------------------------------------------------------
# Claim: state precondition versus reviewer capacity
# ---------------------------------------------------------------------------
def _three_queued_tasks_and_two_reviewers():
    """Three STANDARD tasks, R1 at its ceiling of one, and t2 already held by R2."""
    rule = fixtures.create_policy_rule(
        SUPPLEMENTS,
        "REGULATED",
        4.02,
        title="Supplement health claims",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        rule["id"], "DE", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.15
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Rheinvale Wellness GmbH",
        country_code="DE",
        industry_code="SUPPLEMENTS",
    )
    reviewer_one = fixtures.create_reviewer(
        ["STANDARD"], ["DE"], display_name="Rev One", max_concurrent_claims=1
    )
    reviewer_two = fixtures.create_reviewer(
        ["STANDARD"], ["DE"], display_name="Rev Two", max_concurrent_claims=2
    )
    bodies = [
        ("Immunity boost one", "Our immunity boost formula supports daily wellness.", "a"),
        ("Immunity boost two", "Second immunity boost blend with added vitamins.", "b"),
        ("Immunity boost three", "Third immunity boost pack for the whole family.", "c"),
    ]
    tasks = []
    for headline, body, slug in bodies:
        creative, _run = fixtures.screened_creative(
            advertiser["id"],
            [SUPPLEMENTS],
            [(rule["id"], 0.60)],
            ["DE"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.rheinvale.example/{slug}",
            display_url=f"https://www.rheinvale.example/{slug}",
        )
        tasks.append(fixtures.only_task_for_creative(creative["id"]))
    fixtures.claim_task(tasks[0]["id"], reviewer_one["id"])
    fixtures.claim_task(tasks[1]["id"], reviewer_two["id"])
    return {
        "reviewer_one": reviewer_one,
        "reviewer_two": reviewer_two,
        "tasks": tasks,
    }


def test_the_task_state_check_outranks_the_reviewer_claim_ceiling():
    """PRD §2.10: "9. State preconditions on the addressed resource —
    `ERR_INVALID_CREATIVE_STATE`, `ERR_INVALID_TASK_STATE`, `ERR_NOTICE_NOT_APPEALABLE`,
    `ERR_APPEAL_NOT_PENDING`, `ERR_INVALID_CERTIFICATION_STATE`."

    PRD §2.10: "19. Reviewer claim ceiling — `ERR_REVIEWER_CAPACITY_EXCEEDED`."

    PRD §3.6: "A claim on a task that is not `QUEUED` reports `ERR_INVALID_TASK_STATE`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/task_state_error_outranks_reviewer_capacity_error_on_claim
    """
    case = _three_queued_tasks_and_two_reviewers()
    reviewer_one = case["reviewer_one"]
    held_by_two, still_queued = case["tasks"][1], case["tasks"][2]

    # R1 is full and the target task is already claimed: both rules are broken.
    assert (
        fixtures.read_reviewer(reviewer_one["id"])["claimed_task_count"]
        == reviewer_one["max_concurrent_claims"]
    )
    response = api_client.claim_review_task(
        held_by_two["id"], make_reviewer_headers(reviewer_one["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TASK_STATE, 409)

    # The same reviewer aiming at a still-QUEUED task shows the ceiling rule is live.
    response = api_client.claim_review_task(
        still_queued["id"], make_reviewer_headers(reviewer_one["id"])
    )
    validate_error(response, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED, 409)


def test_neither_rejected_claim_moves_a_task_or_a_counter():
    """PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    PRD §3.6: "Capacity comes last: the reviewer's `claimed_task_count` must be strictly
    less than their `max_concurrent_claims`, and a reviewer already at their ceiling is
    refused with `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409) — an aggregate check, in that
    each held task is individually legal while the collection may not exceed the ceiling."

    Design: Difficulty/priority_pair_validation_conflict/task_state_error_outranks_reviewer_capacity_error_on_claim
    """
    case = _three_queued_tasks_and_two_reviewers()
    reviewer_one, reviewer_two = case["reviewer_one"], case["reviewer_two"]
    held_by_two, still_queued = case["tasks"][1], case["tasks"][2]

    api_client.claim_review_task(
        held_by_two["id"], make_reviewer_headers(reviewer_one["id"])
    )
    api_client.claim_review_task(
        still_queued["id"], make_reviewer_headers(reviewer_one["id"])
    )

    unchanged = fixtures.read_task(held_by_two["id"])
    assert unchanged["status"] == "CLAIMED"
    assert unchanged["assigned_reviewer_id"] == reviewer_two["id"]
    untouched = fixtures.read_task(still_queued["id"])
    assert untouched["status"] == "QUEUED"
    assert untouched["assigned_reviewer_id"] is None
    assert fixtures.read_reviewer(reviewer_one["id"])["claimed_task_count"] == 1
    assert fixtures.read_reviewer(reviewer_two["id"])["claimed_task_count"] == 1


# ---------------------------------------------------------------------------
# Appeal: the closed window versus the evidence owner
# ---------------------------------------------------------------------------
def _stale_and_fresh_notices():
    """Two auto-disapproval notices, one past its window and one still inside it.

    A second, unrelated advertiser holds an `ACTIVE` certification, so every appeal
    below offers evidence it does not own.
    """
    rule = fixtures.create_policy_rule(
        WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(rule["id"], "SE", "BLOCKED", severity_multiplier=2.00)
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        severity_multiplier=1.00,
    )
    appellant = fixtures.create_advertiser(
        legal_name="Ironpoint Outfitters",
        country_code="US",
        industry_code="SPORTING_GOODS",
    )
    stranger = fixtures.create_advertiser(
        legal_name="Granite Range Supply",
        country_code="US",
        industry_code="SPORTING_GOODS",
    )
    foreign_certification = fixtures.create_certification(
        stranger["id"],
        rule["id"],
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
        license_number="FFL-GRS-2026-118",
        issuing_country_code="US",
        headers=make_advertiser_headers(stranger["id"]),
    )
    first = fixtures.create_creative(
        appellant["id"],
        [WEAPONS],
        ["SE", "US"],
        headline="Range day bundle",
        body_text="Range day bundle with two rifles and a case.",
        landing_page_url="https://www.ironpoint.example/bundle",
        display_url="https://www.ironpoint.example/bundle",
    )
    second = fixtures.create_creative(
        appellant["id"],
        [WEAPONS],
        ["SE", "US"],
        headline="Optics clearance",
        body_text="Optics clearance sale including rifle scopes.",
        landing_page_url="https://www.ironpoint.example/optics",
        display_url="https://www.ironpoint.example/optics",
    )
    submitted = fixtures.submit_creative(first["id"], appellant["id"])
    fixtures.screen_creative(
        submitted["id"], [(rule["id"], 0.95)], submitted["version"]
    )
    stale_notice = fixtures.only_notice_for_creative(first["id"])

    # No sweep is ever run, so the stale notice keeps its ISSUED status.
    fixtures.set_clock("2026-08-05T00:00:00Z")
    submitted = fixtures.submit_creative(second["id"], appellant["id"])
    fixtures.screen_creative(
        submitted["id"], [(rule["id"], 0.95)], submitted["version"]
    )
    fresh_notice = fixtures.only_notice_for_creative(second["id"])
    return {
        "appellant_id": appellant["id"],
        "foreign_certification": foreign_certification,
        "stale_notice": stale_notice,
        "fresh_notice": fresh_notice,
    }


def test_the_closed_appeal_window_outranks_the_evidence_owner_check():
    """PRD §2.10: "23. Appeal window still open — `ERR_APPEAL_WINDOW_CLOSED`."

    PRD §2.10: "30. Ownership of an evidence certification —
    `ERR_CERTIFICATION_OWNER_MISMATCH`."

    PRD §3.9: "An appeal is admissible only while the logical clock is *strictly* before
    `appeal_deadline_at`: at the deadline instant the window is already shut, and an
    attempt then or later is refused with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_closed_error_outranks_certification_owner_mismatch
    """
    case = _stale_and_fresh_notices()
    appellant_headers = make_advertiser_headers(case["appellant_id"])
    foreign_id = case["foreign_certification"]["id"]

    assert case["stale_notice"]["appeal_window_hours"] == 72
    assert_instant_equals(
        case["stale_notice"]["appeal_deadline_at"],
        "2026-08-04T00:00:00Z",
        "appeal_deadline_at",
    )
    assert_instant_equals(
        case["fresh_notice"]["appeal_deadline_at"],
        "2026-08-08T00:00:00Z",
        "appeal_deadline_at",
    )

    # Both the window rule and the ownership rule are broken by this one call.
    response = api_client.create_appeal(
        factories.create_appeal_payload(
            case["stale_notice"]["id"],
            justification=(
                "The Swedish targeting was a configuration mistake and has been corrected."
            ),
            evidence_certification_id=foreign_id,
        ),
        appellant_headers,
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, 409)

    # Dropping the evidence leaves the same refusal, so the window is what refuses.
    response = api_client.create_appeal(
        factories.create_appeal_payload(
            case["stale_notice"]["id"],
            justification="Resubmitting the same appeal without any evidence attachment.",
        ),
        appellant_headers,
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, 409)

    # Inside an open window the ownership rule surfaces, proving it is live.
    response = api_client.create_appeal(
        factories.create_appeal_payload(
            case["fresh_notice"]["id"],
            justification="Optics are not firearms and the listing should be reinstated.",
            evidence_certification_id=foreign_id,
        ),
        appellant_headers,
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_OWNER_MISMATCH, 422)


def test_no_refused_appeal_moves_a_notice_out_of_issued():
    """PRD §3.9: "A successful filing creates the appeal in status `SUBMITTED` with a
    null `decided_by_reviewer_id`, a null `decided_at` and a null
    `reinstated_review_status`, and advances the notice `ISSUED → APPEALED` with its
    `version` incremented by 1."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_closed_error_outranks_certification_owner_mismatch
    """
    case = _stale_and_fresh_notices()
    appellant_headers = make_advertiser_headers(case["appellant_id"])
    foreign_id = case["foreign_certification"]["id"]

    for notice_id in (case["stale_notice"]["id"], case["fresh_notice"]["id"]):
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice_id,
                justification="Please reconsider this disapproval on the merits today.",
                evidence_certification_id=foreign_id,
            ),
            appellant_headers,
        )

    assert fixtures.read_notice(case["stale_notice"]["id"])["status"] == "ISSUED"
    assert fixtures.read_notice(case["fresh_notice"]["id"])["status"] == "ISSUED"
    response = api_client.list_appeals(
        ADMIN, {"disapproval_notice_id": case["stale_notice"]["id"]}
    )
    rows, pagination = validate_paginated(response)
    assert rows == []
    assert pagination["total_count"] == 0


# ---------------------------------------------------------------------------
# Limited approval: missing disclosure versus missing licence coverage
# ---------------------------------------------------------------------------
def _two_claimed_political_tasks():
    """Two political creatives on an ELIGIBLE advertiser that holds no licence.

    The pair differ only in `disclaimer_text`, so the disclosure rule is broken by
    exactly one of them while the coverage shortfall applies to both.
    """
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
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Harbor Civic Media Inc",
        country_code="US",
        industry_code="POLITICAL_CONSULTING",
    )
    advertiser_id = advertiser["id"]
    fixtures.record_verification(advertiser_id, "POLITICAL_ELIGIBILITY", "ELIGIBLE")
    reviewer = fixtures.create_reviewer(
        ["POLITICAL"], ["US"], display_name="Rev Political US", max_concurrent_claims=2
    )
    decisions = [(political["id"], 0.70), (spirits["id"], 0.60)]

    without, _run = fixtures.screened_creative(
        advertiser_id,
        [POLITICAL, SPIRITS],
        decisions,
        ["US"],
        headline="Vote yes on measure 4",
        body_text="Our coalition urges a yes vote, sponsored with spirits industry support.",
        landing_page_url="https://www.harborcivic.example/m4",
        display_url="https://www.harborcivic.example/m4",
        political_flag=True,
    )
    with_text, _run = fixtures.screened_creative(
        advertiser_id,
        [POLITICAL, SPIRITS],
        decisions,
        ["US"],
        headline="Vote yes on measure 4 today",
        body_text="Same coalition message with spirits industry support disclosed.",
        landing_page_url="https://www.harborcivic.example/m4b",
        display_url="https://www.harborcivic.example/m4b",
        political_flag=True,
        disclaimer_text="Paid for by Harbor Civic Media Inc. 21+ only.",
    )
    task_without = fixtures.only_task_for_creative(without["id"])
    task_with = fixtures.only_task_for_creative(with_text["id"])
    fixtures.claim_task(task_without["id"], reviewer["id"])
    fixtures.claim_task(task_with["id"], reviewer["id"])
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer["id"],
        "creative_without": without,
        "creative_with": with_text,
        "task_without": task_without,
        "task_with": task_with,
    }


def _attempt_limited_approval(task_id, reviewer_id):
    return api_client.decide_review_task(
        task_id,
        factories.decide_review_task_payload(
            "APPROVE_WITH_LIMITS",
            None,
            ["US"],
            "Approving for US only.",
        ),
        make_reviewer_headers(reviewer_id),
    )


def test_the_disclosure_check_outranks_the_licence_coverage_check():
    """PRD §2.10: "14. Disclosure text presence — `ERR_POLITICAL_DISCLOSURE_MISSING`."

    PRD §2.10: "20. Certification coverage for a limited approval —
    `ERR_CERTIFICATION_MISSING`."

    PRD §3.7: "Next, approving while `disclaimer_text` is null or empty is refused with
    `ERR_POLITICAL_DISCLOSURE_MISSING` (HTTP 422) whenever disclosure is demanded — that
    is, whenever `political_flag` is true, or any matched rule has `requires_disclaimer`
    true, or any retained country's variation on a matched rule has `requires_disclaimer`
    true."

    Design: Difficulty/priority_pair_validation_conflict/political_disclosure_error_outranks_certification_missing_on_approval
    """
    case = _two_claimed_political_tasks()
    assert (
        fixtures.read_advertiser(case["advertiser_id"])["political_eligibility_status"]
        == "ELIGIBLE"
    )

    # No disclaimer and no licence: entries 14 and 20 are both broken.
    response = _attempt_limited_approval(
        case["task_without"]["id"], case["reviewer_id"]
    )
    validate_error(response, ApiErrorId.ERR_POLITICAL_DISCLOSURE_MISSING, 422)

    # With the disclaimer supplied, the coverage shortfall surfaces on its own.
    response = _attempt_limited_approval(case["task_with"]["id"], case["reviewer_id"])
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_MISSING, 422)


def test_a_refused_limited_approval_writes_nothing_at_all():
    """PRD §3.7: "On success the creative's `limited_country_codes` is written from the
    request sorted ascending, its `approved_under_certification_id` is written from the
    coverage selection — the candidate ranked first by `valid_until` descending with ties
    broken by `created_at` ascending — the task becomes `RESOLVED` with `resolution`
    `APPROVE_WITH_LIMITS`, a political creative gains exactly one archive entry, and
    `risk_score_final`, `serving_eligible` and `blocking_reason_codes` are recomputed before
    the creative's `version` increments by 1."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    Design: Difficulty/priority_pair_validation_conflict/political_disclosure_error_outranks_certification_missing_on_approval
    """
    case = _two_claimed_political_tasks()
    advertiser_id = case["advertiser_id"]

    _attempt_limited_approval(case["task_without"]["id"], case["reviewer_id"])
    _attempt_limited_approval(case["task_with"]["id"], case["reviewer_id"])

    for creative in (case["creative_without"], case["creative_with"]):
        row = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
        assert row["review_status"] == "PENDING_MANUAL_REVIEW"
        assert row["limited_country_codes"] == []
        assert row["approved_under_certification_id"] is None
        assert fixtures.list_notices_for_creative(creative["id"]) == []

    for task in (case["task_without"], case["task_with"]):
        assert fixtures.read_task(task["id"])["status"] == "CLAIMED"
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 2
    assert fixtures.archive_entries_for_advertiser(advertiser_id) == []
