"""The registry filing lifecycle: the revision cycle, coverage-period adjacency,
the submission rejection order and the completeness threshold.

A rejected filing is re-entrant into DRAFT through the disclosure endpoint, so a
filing can visit SUBMITTED twice and be re-assessed against the enlarged
disclosure set. Coverage periods are half-open, so touching endpoints are
adjacency rather than overlap. Submission checks run in the fixed rejection order
of the compliance office, with the fiscal check last of all.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REQUIRED_DISCLOSURE_CATEGORIES,
    ApiErrorId,
    add_disclosures,
    api_client,
    assert_cents_equals,
    assert_instant_equals,
    assert_score_equals,
    create_registration_payload,
    create_rejection_payload,
    fetch_broker,
    fetch_registration,
    get_success_data,
    make_platform_admin_headers,
    onboard_broker,
    open_draft_registration,
    setup_accepted_registration,
    submit_registration,
    validate_error,
    validate_paginated,
    validate_success,
)

COVERAGE_START = "2026-09-01T00:00:00Z"
COVERAGE_END = "2027-03-01T00:00:00Z"
RENEWAL_START = "2027-03-01T00:00:00Z"
RENEWAL_END = "2027-09-01T00:00:00Z"
OVERLAPPING_START = "2027-02-28T23:59:59Z"
OVERLAPPING_END = "2027-08-01T00:00:00Z"
SHORT_SOURCES_CONTENT = "Loyalty and survey panels."
SHORT_RETENTION_CONTENT = "Kept thirty-six months."
SHORT_RECIPIENTS_CONTENT = "Ad networks and analytics vendors."


def _broker_with_draft_filing(
    operating_state_codes=("CA",),
    deposit_cents=500000,
    state_code="CA",
    coverage_period_end=COVERAGE_END,
):
    """Broker enrolled at the pinned clock instant with one DRAFT filing."""
    ctx = onboard_broker(
        operating_state_codes=operating_state_codes,
        deposit_cents=deposit_cents,
        clock=CLOCK_TEST_INSTANT,
    )
    registration = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code=state_code,
        coverage_period_start=COVERAGE_START,
        coverage_period_end=coverage_period_end,
    )
    ctx["registration"] = registration
    ctx["registration_id"] = registration["id"]
    return ctx


def _rejected_filing_after_first_submission():
    """A CA filing carrying the four required disclosures at full length, taken
    through DRAFT -> SUBMITTED -> REJECTED with a FEE_DISPUTE reason code."""
    ctx = _broker_with_draft_filing()
    add_disclosures(
        ctx["registration_id"],
        ctx["broker_headers"],
        categories=REQUIRED_DISCLOSURE_CATEGORIES,
    )
    submit_registration(ctx["registration_id"], ctx["broker_headers"])
    ctx["registration"] = get_success_data(
        api_client.reject_registration(
            ctx["registration_id"],
            create_rejection_payload("FEE_DISPUTE"),
            make_platform_admin_headers(),
        )
    )
    return ctx


def _revise_resubmit_and_accept(ctx):
    """Reopen the rejected filing with a sensitive-flagged disclosure, submit it a
    second time and have the registry accept it."""
    add_disclosures(
        ctx["registration_id"],
        ctx["broker_headers"],
        categories=("SENSITIVE_CATEGORIES",),
        sensitive_categories=("SENSITIVE_CATEGORIES",),
    )
    submit_registration(ctx["registration_id"], ctx["broker_headers"])
    return validate_success(
        api_client.accept_registration(
            ctx["registration_id"], make_platform_admin_headers()
        )
    )


def test_rejected_filing_reopened_by_a_disclosure_counts_one_revision():
    """PRD §3.2: "From `REJECTED` the same act **reopens the filing for
    revision**: the transition is `REJECTED → DRAFT`, `revision_count` increases
    by one, and `rejection_reason_code` is cleared to null."
    PRD §3.2: "The full revision loop is therefore `DRAFT → SUBMITTED → REJECTED →
    DRAFT`, and each pass through it increments `revision_count`."
    PRD §3.2: "A `PlatformAdmin` acting as registry examiner accepts a `SUBMITTED`
    filing, moving it `SUBMITTED → ACCEPTED`."
    PRD §3.2: "The six category weights are 20.00 for `SOURCES`, 25.00 for
    `RECIPIENTS`, 15.00 for `RETENTION`, 20.00 for `OPT_OUT_MECHANISM`, 12.00 for
    `SENSITIVE_CATEGORIES`, and 8.00 for `MINORS_DATA`."
    PRD §3.2: "The filing's `disclosure_completeness_score` is the sum of every
    item's `weight_credit`, rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/registration_reject_to_draft_revision_cycle_reassesses_both_fee_variants
    """
    ctx = _rejected_filing_after_first_submission()

    registration = _revise_resubmit_and_accept(ctx)

    assert registration["status"] == "ACCEPTED", (
        f"Expected the revised filing to be ACCEPTED, got {registration['status']}"
    )
    assert registration["revision_count"] == 1, (
        f"Expected revision_count 1, got {registration['revision_count']}"
    )
    assert registration["rejection_reason_code"] is None, (
        "Expected rejection_reason_code cleared to null, got "
        f"{registration['rejection_reason_code']!r}"
    )
    assert_score_equals(
        registration["disclosure_completeness_score"],
        92.00,
        "disclosure_completeness_score",
    )


def test_revision_cycle_reassesses_both_fee_variants_over_the_enlarged_set():
    """PRD §3.2: "The provisional fee is the base of 40000 cents plus the plain
    sum of those already-rounded per-item surcharges, with **no proration
    whatsoever**."
    PRD §3.2: "The final fee is computed by first aggregating the base 40000 cents
    with the same sum of per-item surcharges (re-read as the disclosure set stands
    **at acceptance time**, so a disclosure added during a rejection-and-revision
    loop changes the final fee relative to the provisional fee frozen at the
    earlier submission), then multiplying that aggregate by a proration ratio, and
    only then rounding half up to a whole cent — exactly one rounding step,
    applied at the very end."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount
    and `charged_fee_cents` is reset to it."
    PRD §2.7: "The broker's filing-fee account obeys a conservation law that must
    hold after every deposit, every submission, every acceptance settlement, and
    every withdrawal, rejection, or expiry refund: `fee_deposited_cents` always
    equals `fee_paid_cents` plus `fee_credit_cents`."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or
    before the current clock instant while its `coverage_period_end` is strictly
    after it, the standing is `COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/registration_reject_to_draft_revision_cycle_reassesses_both_fee_variants
    """
    ctx = _rejected_filing_after_first_submission()

    registration = _revise_resubmit_and_accept(ctx)

    assert_cents_equals(
        registration["provisional_filing_fee_cents"],
        55100,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(
        registration["final_filing_fee_cents"], 27324, "final_filing_fee_cents"
    )
    assert_cents_equals(registration["charged_fee_cents"], 27324, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 27324, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 472676, "fee_credit_cents")
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert broker["registry_standing"] == "COMPLIANT", (
        f"Expected registry_standing COMPLIANT, got {broker['registry_standing']}"
    )


def test_renewal_starting_on_the_incumbent_coverage_end_is_adjacency_not_overlap():
    """PRD §3.2: "A new filing may not overlap an existing `SUBMITTED` or
    `ACCEPTED` filing of the same broker for the same state."
    PRD §3.2: "Overlap is measured on the half-open intervals, so two periods that
    merely touch — one ending exactly where the next begins — are adjacent and
    permitted, while any genuine intersection is refused with
    `ERR_COVERAGE_PERIOD_OVERLAP`."
    PRD §3.2: "The filing is created in `DRAFT` with a
    `disclosure_completeness_score` of 0.00, a `revision_count` of 0, a
    `charged_fee_cents` of 0, a `provisional_filing_fee_cents` of 0, a null
    `final_filing_fee_cents`, null `submitted_at` and `accepted_at`, and a null
    `rejection_reason_code`."
    PRD §3.2: "`coverage_days` is computed from the half-open interval as the whole
    number of days it spans."

    Design: Difficulty/resource_temporal_overlap/registration_coverage_adjacency_allowed_but_one_second_overlap_rejected
    """
    ctx = setup_accepted_registration()
    broker_version = fetch_broker(ctx["broker_id"], ctx["broker_headers"])["version"]

    renewal = validate_success(
        api_client.create_registration(
            create_registration_payload(
                ctx["broker_id"],
                broker_version,
                state_code="CA",
                coverage_period_start=RENEWAL_START,
                coverage_period_end=RENEWAL_END,
                business_description=(
                    "California renewal filing for the licensed consumer contact "
                    "index business."
                ),
            ),
            ctx["broker_headers"],
        ),
        201,
    )

    assert renewal["status"] == "DRAFT", (
        f"Expected the adjacent renewal to be DRAFT, got {renewal['status']}"
    )
    assert_instant_equals(
        renewal["coverage_period_start"], RENEWAL_START, "coverage_period_start"
    )
    assert renewal["coverage_days"] == 184, (
        f"Expected coverage_days 184, got {renewal['coverage_days']}"
    )


def test_filing_overlapping_the_incumbent_by_one_second_is_refused():
    """PRD §3.2: "Overlap is measured on the half-open intervals, so two periods
    that merely touch — one ending exactly where the next begins — are adjacent and
    permitted, while any genuine intersection is refused with
    `ERR_COVERAGE_PERIOD_OVERLAP`."
    PRD §3.2: "A new filing may not overlap an existing `SUBMITTED` or `ACCEPTED`
    filing of the same broker for the same state."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts
    every record matching the applied filters before the page window is applied,
    and `has_more` states whether any record remains beyond the current window."

    Design: Difficulty/resource_temporal_overlap/registration_coverage_adjacency_allowed_but_one_second_overlap_rejected
    """
    ctx = setup_accepted_registration()
    open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code="CA",
        coverage_period_start=RENEWAL_START,
        coverage_period_end=RENEWAL_END,
    )
    broker_version = fetch_broker(ctx["broker_id"], ctx["broker_headers"])["version"]

    response = api_client.create_registration(
        create_registration_payload(
            ctx["broker_id"],
            broker_version,
            state_code="CA",
            coverage_period_start=OVERLAPPING_START,
            coverage_period_end=OVERLAPPING_END,
            business_description=(
                "California overlapping filing for the licensed consumer contact "
                "index business."
            ),
        ),
        ctx["broker_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP, 409)

    _, meta = validate_paginated(
        api_client.list_registrations(
            ctx["broker_headers"], params={"broker_id": ctx["broker_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected 2 filings for the broker, got {meta['total_count']}"
    )

    incumbent = fetch_registration(ctx["registration_id"], ctx["broker_headers"])
    assert incumbent["status"] == "ACCEPTED", (
        f"Expected the incumbent filing to stay ACCEPTED, got {incumbent['status']}"
    )
    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 23307, "fee_paid_cents")


def _draft_filing_short_of_completeness_and_credit():
    """A CA filing whose SOURCES and RETENTION answers are under 40 characters,
    owned by a broker that never deposited, so both the completeness rule and the
    fee rule are violated by the same submission."""
    ctx = _broker_with_draft_filing(deposit_cents=0)
    ctx["disclosures"] = add_disclosures(
        ctx["registration_id"],
        ctx["broker_headers"],
        categories=REQUIRED_DISCLOSURE_CATEGORIES,
        content_overrides={
            "SOURCES": SHORT_SOURCES_CONTENT,
            "RETENTION": SHORT_RETENTION_CONTENT,
        },
    )
    return ctx


def test_disclosure_incompleteness_is_reported_ahead_of_the_fee_shortfall():
    """PRD §2.6: "The compliance office resolves that deterministically: every rule
    below carries a priority, all applicable rules are considered, and the
    **lowest-numbered violated rule alone** determines the `error_id` and HTTP
    status returned."
    PRD §2.6: "The business tier is ordered by what the office cares about most: a
    consumer's deletion rights and an active suppression window outrank referential
    concerns, which outrank constraint satisfaction, which outranks temporal
    conflicts, and fiscal checks come last of all."
    PRD §3.2: "The `disclosure_completeness_score` must be at least 80.00, or the
    submission is refused with `ERR_DISCLOSURE_INCOMPLETE`."
    PRD §3.2: "Each item earns its category's full weight when its `content_length`
    is at least 40 characters, and exactly half of that weight when the content is
    shorter than 40 characters — a short answer is treated as a partial answer
    rather than no answer at all."

    Design: Difficulty/priority_pair_validation_conflict/submit_disclosure_incompleteness_outranks_filing_fee_shortfall
    """
    ctx = _draft_filing_short_of_completeness_and_credit()

    response = api_client.submit_registration(
        ctx["registration_id"], ctx["broker_headers"]
    )

    validate_error(response, ApiErrorId.ERR_DISCLOSURE_INCOMPLETE, 422)

    registration = fetch_registration(ctx["registration_id"], ctx["broker_headers"])
    assert registration["status"] == "DRAFT", (
        f"Expected the refused filing to stay DRAFT, got {registration['status']}"
    )
    assert_score_equals(
        registration["disclosure_completeness_score"],
        62.50,
        "disclosure_completeness_score",
    )


def test_fee_shortfall_surfaces_only_once_the_completeness_rule_is_satisfied():
    """PRD §2.6: "The compliance office resolves that deterministically: every rule
    below carries a priority, all applicable rules are considered, and the
    **lowest-numbered violated rule alone** determines the `error_id` and HTTP
    status returned."
    PRD §3.2: "Finally, and last of all, the broker's `fee_credit_cents` must be at
    least the provisional filing fee this submission assesses, or the submission is
    refused with `ERR_FILING_FEE_UNPAID` (402)."
    PRD §3.2: "The filing's `disclosure_completeness_score` is the sum of every
    item's `weight_credit`, rounded half up to two decimal places."
    PRD §3.2: "Five business conditions guard that transition, and they are
    evaluated in the priority order of §2.6."

    Design: Difficulty/priority_pair_validation_conflict/submit_disclosure_incompleteness_outranks_filing_fee_shortfall
    """
    ctx = _draft_filing_short_of_completeness_and_credit()
    validate_error(
        api_client.submit_registration(ctx["registration_id"], ctx["broker_headers"]),
        ApiErrorId.ERR_DISCLOSURE_INCOMPLETE,
        422,
    )

    add_disclosures(
        ctx["registration_id"],
        ctx["broker_headers"],
        categories=("SENSITIVE_CATEGORIES", "MINORS_DATA"),
    )
    response = api_client.submit_registration(
        ctx["registration_id"], ctx["broker_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FILING_FEE_UNPAID, 402)

    registration = fetch_registration(ctx["registration_id"], ctx["broker_headers"])
    assert_score_equals(
        registration["disclosure_completeness_score"],
        82.50,
        "disclosure_completeness_score",
    )
    assert registration["status"] == "DRAFT", (
        f"Expected the refused filing to stay DRAFT, got {registration['status']}"
    )
    assert_cents_equals(registration["charged_fee_cents"], 0, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_credit_cents"], 0, "fee_credit_cents")
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")


def _two_filings_at_the_completeness_boundary():
    """One broker operating in CA and NY with a funded fee account and two DRAFT
    filings over the same period: the CA filing answers the four mandatory
    categories at full length, while the NY filing shortens RECIPIENTS and adds a
    full-length SENSITIVE_CATEGORIES item instead."""
    ctx = onboard_broker(
        operating_state_codes=("CA", "NY"),
        deposit_cents=500000,
        clock=CLOCK_TEST_INSTANT,
    )
    california = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code="CA",
        coverage_period_start=COVERAGE_START,
        coverage_period_end=COVERAGE_END,
    )
    new_york = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code="NY",
        coverage_period_start=COVERAGE_START,
        coverage_period_end=COVERAGE_END,
    )
    add_disclosures(
        california["id"],
        ctx["broker_headers"],
        categories=REQUIRED_DISCLOSURE_CATEGORIES,
    )
    add_disclosures(
        new_york["id"],
        ctx["broker_headers"],
        categories=list(REQUIRED_DISCLOSURE_CATEGORIES) + ["SENSITIVE_CATEGORIES"],
        content_overrides={"RECIPIENTS": SHORT_RECIPIENTS_CONTENT},
    )
    ctx["california_id"] = california["id"]
    ctx["new_york_id"] = new_york["id"]
    return ctx


def test_submission_at_exactly_eighty_completeness_is_accepted_for_filing():
    """PRD §3.2: "Submission requires a completeness score of at least 80.00. The
    comparison is inclusive: exactly 80.00 passes, and 79.99 does not."
    PRD §3.2: "A `BrokerAdmin` files with the state registry, moving the filing
    `DRAFT → SUBMITTED`."
    PRD §3.2: "The six category weights are 20.00 for `SOURCES`, 25.00 for
    `RECIPIENTS`, 15.00 for `RETENTION`, 20.00 for `OPT_OUT_MECHANISM`, 12.00 for
    `SENSITIVE_CATEGORIES`, and 8.00 for `MINORS_DATA`."
    PRD §3.2: "Both `provisional_filing_fee_cents` and `charged_fee_cents` are set
    to that amount, `fee_credit_cents` decreases by it while `fee_paid_cents`
    increases by the same amount (`fee_deposited_cents` does not move),
    `submitted_at` is set to the current clock instant, the parent broker's
    `version` increases by one, and a `REGISTRATION_SUBMITTED` audit event is
    appended."

    Design: Difficulty/boundary_precision_check/submit_at_exactly_eighty_completeness_passes_and_seventy_nine_point_five_fails
    """
    ctx = _two_filings_at_the_completeness_boundary()

    registration = validate_success(
        api_client.submit_registration(ctx["california_id"], ctx["broker_headers"])
    )

    assert_score_equals(
        registration["disclosure_completeness_score"],
        80.00,
        "disclosure_completeness_score",
    )
    assert registration["status"] == "SUBMITTED", (
        f"Expected the filing to be SUBMITTED, got {registration['status']}"
    )
    assert_cents_equals(
        registration["provisional_filing_fee_cents"],
        47000,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(registration["charged_fee_cents"], 47000, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 47000, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 453000, "fee_credit_cents")


def test_submission_at_seventy_nine_point_five_completeness_is_refused():
    """PRD §3.2: "Submission requires a completeness score of at least 80.00. The
    comparison is inclusive: exactly 80.00 passes, and 79.99 does not."
    PRD §3.2: "Each item earns its category's full weight when its `content_length`
    is at least 40 characters, and exactly half of that weight when the content is
    shorter than 40 characters — a short answer is treated as a partial answer
    rather than no answer at all."
    PRD §2.6: "`disclosure_completeness_score` is at least 80.00, where exactly
    80.00 passes — otherwise `ERR_DISCLOSURE_INCOMPLETE` (422)."
    PRD §3.2: "The filing's `disclosure_completeness_score` is the sum of every
    item's `weight_credit`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/submit_at_exactly_eighty_completeness_passes_and_seventy_nine_point_five_fails
    """
    ctx = _two_filings_at_the_completeness_boundary()

    response = api_client.submit_registration(
        ctx["new_york_id"], ctx["broker_headers"]
    )

    validate_error(response, ApiErrorId.ERR_DISCLOSURE_INCOMPLETE, 422)

    registration = fetch_registration(ctx["new_york_id"], ctx["broker_headers"])
    assert_score_equals(
        registration["disclosure_completeness_score"],
        79.50,
        "disclosure_completeness_score",
    )
    assert registration["status"] == "DRAFT", (
        f"Expected the refused filing to stay DRAFT, got {registration['status']}"
    )
    assert_cents_equals(registration["charged_fee_cents"], 0, "charged_fee_cents")
