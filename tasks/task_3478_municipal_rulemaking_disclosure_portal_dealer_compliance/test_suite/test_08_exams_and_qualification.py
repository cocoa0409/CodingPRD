"""Qualification examinations: inclusive pass marks, required series sets,
the 30-day half-open retake window, and the employer-organization gate
(PRD sections 2.7, 3.5, 3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_dealer_org,
    create_exam_attempt_payload,
    create_org_with_professional,
    create_professional,
    make_dealer_rep_headers,
    read_professional,
    record_exam,
    set_clock,
    suspend_organization,
    validate_error,
)

EXAM_ADMIN = TEST_USERS["exam_admin_headers"]

UNKNOWN_PROFESSIONAL_ID = "11111111-2222-3333-4444-555555555555"


def test_msrb_53_pass_mark_boundary_is_inclusive(api):
    """PRD section 3.6: "The attempt's `result` is computed against a
    per-series pass mark with an inclusive boundary: `MSRB_50` passes at a
    score of at least 70, `MSRB_52` at least 72, `MSRB_53` at least 75, and
    `MSRB_54` at least 80; anything below is a `FAIL`."

    Design: Difficulty/boundary_precision_check/exam_pass_score_exact_boundary
    """
    org = create_dealer_org(api, org_code="BD-600", name="Dealer Six")
    below = create_professional(
        api, org["id"], professional_class="MUNICIPAL_PRINCIPAL", full_name="Pro SeventyFour"
    )
    at = create_professional(
        api, org["id"], professional_class="MUNICIPAL_PRINCIPAL", full_name="Pro SeventyFive"
    )

    r74 = record_exam(api, below["id"], "MSRB_53", 74)
    assert r74["result"] == "FAIL", f"74 is below the MSRB_53 mark of 75, got {r74['result']!r}"
    r75 = record_exam(api, at["id"], "MSRB_53", 75)
    assert r75["result"] == "PASS", f"75 meets the MSRB_53 mark inclusively, got {r75['result']!r}"


def test_msrb_50_boundary_and_single_series_qualification(api):
    """PRD section 3.6: "`MSRB_50` passes at a score of at least 70" and
    "a `MUNICIPAL_ADVISOR_REP` needs `MSRB_50`"; "The attempt that
    completes the set automatically moves the professional from
    `UNQUALIFIED` to `QUALIFIED`".

    Design: Difficulty/boundary_precision_check/exam_pass_score_exact_boundary
    """
    org = create_dealer_org(api, org_code="BD-603", name="Dealer Fifty")
    below = create_professional(
        api, org["id"], professional_class="MUNICIPAL_ADVISOR_REP", full_name="Pro SixtyNine"
    )
    at = create_professional(
        api, org["id"], professional_class="MUNICIPAL_ADVISOR_REP", full_name="Pro Seventy"
    )

    r69 = record_exam(api, below["id"], "MSRB_50", 69)
    assert r69["result"] == "FAIL"
    assert read_professional(api, below["id"])["qualification_status"] == "UNQUALIFIED"

    r70 = record_exam(api, at["id"], "MSRB_50", 70)
    assert r70["result"] == "PASS"
    assert read_professional(api, at["id"])["qualification_status"] == "QUALIFIED", (
        "passing the lone required series must complete qualification"
    )


def test_principal_qualification_requires_both_series(api):
    """PRD section 3.6: "a `MUNICIPAL_PRINCIPAL` needs both `MSRB_53` and
    `MSRB_54`" — one passing series leaves the professional
    `UNQUALIFIED` until the set completes; the `MSRB_54` mark of 80 is
    inclusive, so 80 completes the set.

    Design: Corner/calculations/principal_qualification_requires_both_series
    """
    org = create_dealer_org(api, org_code="BD-2004", name="Dealer Principal")
    prof = create_professional(
        api, org["id"], professional_class="MUNICIPAL_PRINCIPAL", full_name="Pro Principal"
    )

    r1 = record_exam(api, prof["id"], "MSRB_53", 80)
    assert r1["result"] == "PASS"
    assert read_professional(api, prof["id"])["qualification_status"] == "UNQUALIFIED", (
        "MSRB_53 alone must not qualify a principal"
    )

    r2 = record_exam(api, prof["id"], "MSRB_54", 80)
    assert r2["result"] == "PASS"
    assert read_professional(api, prof["id"])["qualification_status"] == "QUALIFIED"


def test_exam_attempt_blocked_when_employer_org_suspended(api):
    """PRD section 3.6: "Three gates precede scoring, in §2.5 order: the
    professional's employer organization must be `ACTIVE`
    (`ERR_ORG_SUSPENDED`)". The professional's own standing remains ACTIVE
    — the gate is the employer's status.

    Design: Difficulty/cross_entity_state_dependency/exam_attempt_blocked_by_suspended_employer_org
    """
    org, prof = create_org_with_professional(api, org_code="BD-700", name="Dealer Seven")
    suspend_organization(api, org["id"], reason="regulatory action")
    assert read_professional(api, prof["id"])["standing"] == "ACTIVE"

    resp = api.create_exam_attempt(
        create_exam_attempt_payload(prof["id"], "MSRB_52", 80), EXAM_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)


def test_suspended_dealer_org_cannot_report_trades(api):
    """PRD section 3.5: "Suspension does not cascade to the organization's
    professionals or subscriptions, but it gates the future: filing
    disclosures, reporting trades, logging solicitations, sitting
    examinations (via the employer), and creating or activating data
    subscriptions all require the referenced organization to be `ACTIVE`
    and are otherwise rejected with `ERR_ORG_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/exam_attempt_blocked_by_suspended_employer_org
    """
    org = create_dealer_org(api, org_code="BD-701", name="Dealer Suspended Trades")
    suspend_organization(api, org["id"], reason="net capital deficiency")

    resp = api.create_trade_report(
        {
            "dealer_org_id": org["id"],
            "cusip": "123456789",
            "trade_type": "INTER_DEALER",
            "par_amount": 100000,
            "price": 100.0,
            "executed_at": "2026-09-01T00:00:00Z",
        },
        make_dealer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)


def test_retake_window_is_half_open_at_thirty_days(api):
    """PRD section 3.6: "the retake exclusion forbids a new attempt on the
    same professional-and-series pair while an earlier attempt on that pair
    is strictly younger than thirty days — a prior attempt exactly thirty
    days old does not block — with a violation rejected as
    `ERR_RETAKE_WINDOW_ACTIVE` (HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/exam_retake_half_open_thirty_day_window
    """
    org, prof = create_org_with_professional(api, org_code="BD-800", name="Dealer Eight")
    record_exam(api, prof["id"], "MSRB_52", 60)  # FAIL recorded at 2026-09-01T00:00:00Z

    set_clock(api, "2026-09-30T00:00:00Z")  # 29 days later: still inside the window
    blocked = api.create_exam_attempt(
        create_exam_attempt_payload(prof["id"], "MSRB_52", 80), EXAM_ADMIN
    )
    validate_error(blocked, ApiErrorId.ERR_RETAKE_WINDOW_ACTIVE)

    set_clock(api, "2026-10-01T00:00:00Z")  # exactly 30 days: outside the window
    retake = record_exam(api, prof["id"], "MSRB_52", 80)
    assert retake["result"] == "PASS"
    assert read_professional(api, prof["id"])["qualification_status"] == "QUALIFIED"


def test_retake_window_is_pair_scoped_and_counts_prior_passes(api):
    """PRD section 3.6: the exclusion forbids "a new attempt on the same
    professional-and-series pair while an earlier attempt on that pair is
    strictly younger than thirty days" — the rule names the pair and "an
    earlier attempt", so a prior PASS on the pair also blocks, while a
    different series for the same professional does not.

    Design: Difficulty/resource_temporal_overlap/exam_retake_half_open_thirty_day_window
    """
    org, prof = create_org_with_professional(api, org_code="BD-801", name="Dealer Pairs")
    record_exam(api, prof["id"], "MSRB_52", 80)  # PASS qualifies the dealer rep

    same_pair = api.create_exam_attempt(
        create_exam_attempt_payload(prof["id"], "MSRB_52", 90), EXAM_ADMIN
    )
    validate_error(same_pair, ApiErrorId.ERR_RETAKE_WINDOW_ACTIVE)

    other_series = record_exam(api, prof["id"], "MSRB_50", 80)
    assert other_series["result"] == "PASS", (
        "a different series on the same professional is a different pair and must not be blocked"
    )


def test_exam_attempt_with_unknown_professional_returns_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for municipal professionals that identifier is
    `ERR_PROFESSIONAL_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/exam_attempt_unknown_professional_returns_professional_not_found
    """
    resp = api.create_exam_attempt(
        create_exam_attempt_payload(UNKNOWN_PROFESSIONAL_ID, "MSRB_52", 80), EXAM_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PROFESSIONAL_NOT_FOUND)
