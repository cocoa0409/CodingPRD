"""The pinned score and fee calculations, exercised on their stated boundaries.

Each test drives one calculation of the contract — identity assurance in its
fraud-weighted variant, disclosure completeness with the provisional filing fee
it funds, recipient reliability after a late acknowledgement, and the registry
standing derivation over a multi-state broker — and pins every component the
contract names, not merely the final figure.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    OPTIONAL_DISCLOSURE_CATEGORIES,
    REQUIRED_DISCLOSURE_CATEGORIES,
    accept_registration,
    add_disclosures,
    api_client,
    assert_cents_equals,
    assert_instant_equals,
    assert_ratio_equals,
    assert_score_equals,
    dispatch_task,
    fetch_broker,
    fetch_deletion_request,
    fetch_recipient,
    fetch_registration,
    find_task,
    make_intake_agent_headers,
    make_platform_admin_headers,
    onboard_broker,
    open_deletion_request,
    open_draft_registration,
    record_consumer,
    set_clock,
    setup_executing_deletion_request,
    submit_registration,
    validate_paginated,
    validate_success,
)

ALL_DISCLOSURE_CATEGORIES = list(REQUIRED_DISCLOSURE_CATEGORIES) + list(
    OPTIONAL_DISCLOSURE_CATEGORIES
)


def audit_event_total(broker_id, headers, event_type):
    """How many events of one type the broker's trail carries."""
    response = api_client.list_audit_events(
        broker_id, headers, params={"event_type": event_type}
    )
    _, meta = validate_paginated(response)
    return meta["total_count"]


def record_attempt(request_id, method, evidence_points_count, document_quality_score):
    """One verification attempt captured by the intake desk."""
    response = api_client.create_verification_attempt(
        request_id,
        {
            "method": method,
            "evidence_points_count": evidence_points_count,
            "document_quality_score": document_quality_score,
        },
        make_intake_agent_headers(),
    )
    return response


def test_only_four_evidence_points_are_credited_landing_on_the_pass_threshold():
    """PRD §3.4: "The credited evidence points are the smaller of the supplied
    `evidence_points_count` and 4 — only the first four corroborating points are
    ever credited, so a consumer who supplies ten is not rewarded for nine and is
    not penalised either."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each
    credited evidence point plus 0.20 times the `document_quality_score`. The
    method base values are 55.00 for `GOVT_ID`, 30.00 for `TWO_DATA_POINTS`,
    25.00 for `PLATFORM_ASSERTION`, and 35.00 for `AGENT_LOA`."
    PRD §3.4: "The `fraud_penalty_applied` is 12.00 multiplied by the number of
    failed attempts already on this request, using `failed_attempt_count` **as it
    stands before this attempt is scored**; the attempt currently being scored
    never penalises itself."
    PRD §3.4: "When any of the three conditions fails — including a
    `PLATFORM_ASSERTION` method presented on a `DIRECT_PORTAL` request —
    `variant_applied` is `FRAUD_WEIGHTED`, and the score is the raw score minus
    the fraud penalty, raised to a floor of 0.00, capped at 100.00, and rounded
    half up to two decimal places."
    PRD §3.4: "The attempt's `outcome` is derived from its `assurance_score` and
    is never accepted as input: `PASS` when the score is at least 70.00,
    `INCONCLUSIVE` when it is at least 50.00 but below 70.00, and `FAIL` when it
    is below 50.00."
    PRD §3.4: "Recording the attempt increments the request's
    `verification_attempt_count` by one, and increments `failed_attempt_count` by
    one when the outcome is `FAIL`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the
    maximum `assurance_score` across every attempt on the request, with no status
    filter, so it never regresses when a later attempt scores worse than an
    earlier one."
    PRD §3.4: "From `RECEIVED` the request moves `RECEIVED →
    VERIFICATION_PENDING`."
    PRD §4: "Every creation endpoint answers 201 with the created resource in
    `data`"

    Design: Corner/calculations/assurance_evidence_points_capped_at_four_lands_exactly_on_the_pass_threshold
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    request = open_deletion_request(
        ctx["broker_id"],
        consumer,
        intake_channel="DIRECT_PORTAL",
        requested_scope="DELETE_ALL",
    )

    response = record_attempt(request["id"], "TWO_DATA_POINTS", 5, 50)
    attempt = validate_success(response, 201)

    assert attempt["variant_applied"] == "FRAUD_WEIGHTED"
    assert_score_equals(attempt["raw_score"], "70.00", "raw_score")
    assert_score_equals(
        attempt["fraud_penalty_applied"], "0.00", "fraud_penalty_applied"
    )
    assert_score_equals(attempt["assurance_score"], "70.00", "assurance_score")
    assert attempt["outcome"] == "PASS"

    stored = fetch_deletion_request(request["id"], ctx["broker_headers"])
    assert_score_equals(
        stored["identity_assurance_score"], "70.00", "identity_assurance_score"
    )
    assert stored["verification_attempt_count"] == 1
    assert stored["failed_attempt_count"] == 0
    assert stored["status"] == "VERIFICATION_PENDING"


def test_fraud_penalty_counts_only_the_failures_observed_before_each_attempt():
    """PRD §3.4: "The `fraud_penalty_applied` is 12.00 multiplied by the number of
    failed attempts already on this request, using `failed_attempt_count` **as it
    stands before this attempt is scored**; the attempt currently being scored
    never penalises itself."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each
    credited evidence point plus 0.20 times the `document_quality_score`. The
    method base values are 55.00 for `GOVT_ID`, 30.00 for `TWO_DATA_POINTS`,
    25.00 for `PLATFORM_ASSERTION`, and 35.00 for `AGENT_LOA`."
    PRD §3.4: "The attempt's `outcome` is derived from its `assurance_score` and
    is never accepted as input: `PASS` when the score is at least 70.00,
    `INCONCLUSIVE` when it is at least 50.00 but below 70.00, and `FAIL` when it
    is below 50.00."
    PRD §3.4: "Recording the attempt increments the request's
    `verification_attempt_count` by one, and increments `failed_attempt_count` by
    one when the outcome is `FAIL`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the
    maximum `assurance_score` across every attempt on the request, with no status
    filter, so it never regresses when a later attempt scores worse than an
    earlier one."
    PRD §3.4: "From `VERIFICATION_PENDING` it stays `VERIFICATION_PENDING`, with
    the fraud penalty of that attempt using `failed_attempt_count` as observed
    before the attempt is scored."

    Design: Corner/calculations/assurance_fraud_penalty_uses_prior_fails_observed_before_scoring
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    request = open_deletion_request(
        ctx["broker_id"],
        consumer,
        intake_channel="DIRECT_PORTAL",
        requested_scope="DELETE_ALL",
    )

    first = validate_success(record_attempt(request["id"], "TWO_DATA_POINTS", 1, 40), 201)
    assert_score_equals(first["raw_score"], "45.50", "raw_score")
    assert_score_equals(first["fraud_penalty_applied"], "0.00", "fraud_penalty_applied")
    assert_score_equals(first["assurance_score"], "45.50", "assurance_score")
    assert first["outcome"] == "FAIL"

    second = validate_success(
        record_attempt(request["id"], "TWO_DATA_POINTS", 1, 40), 201
    )
    assert_score_equals(second["raw_score"], "45.50", "raw_score")
    assert_score_equals(
        second["fraud_penalty_applied"], "12.00", "fraud_penalty_applied"
    )
    assert_score_equals(second["assurance_score"], "33.50", "assurance_score")
    assert second["outcome"] == "FAIL"

    third = validate_success(record_attempt(request["id"], "GOVT_ID", 3, 80), 201)
    assert_score_equals(third["raw_score"], "93.50", "raw_score")
    assert_score_equals(third["fraud_penalty_applied"], "24.00", "fraud_penalty_applied")
    assert_score_equals(third["assurance_score"], "69.50", "assurance_score")
    assert third["outcome"] == "INCONCLUSIVE"

    stored = fetch_deletion_request(request["id"], ctx["broker_headers"])
    assert stored["verification_attempt_count"] == 3
    assert stored["failed_attempt_count"] == 2
    assert_score_equals(
        stored["identity_assurance_score"], "69.50", "identity_assurance_score"
    )
    assert stored["status"] == "VERIFICATION_PENDING"


def test_optional_disclosure_categories_count_at_their_declared_weights():
    """PRD §3.2: "Each item earns its category's full weight when its
    `content_length` is at least 40 characters, and exactly half of that weight
    when the content is shorter than 40 characters — a short answer is treated as
    a partial answer rather than no answer at all. The six category weights are
    20.00 for `SOURCES`, 25.00 for `RECIPIENTS`, 15.00 for `RETENTION`, 20.00 for
    `OPT_OUT_MECHANISM`, 12.00 for `SENSITIVE_CATEGORIES`, and 8.00 for
    `MINORS_DATA`. Those six weights total exactly 100.00, so a filing that
    answers every category at full length scores exactly 100.00 and no clamp is
    needed."
    PRD §3.2: "The filing's `disclosure_completeness_score` is the sum of every
    item's `weight_credit`, rounded half up to two decimal places."
    PRD §3.2: "Each item records its own `content_length`, the exact character
    count of `content`; its own `weight_credit`, the points it contributes to the
    filing's completeness; and its own `surcharge_cents`, the per-category filing
    surcharge it carries."
    PRD §3.2: "It starts from a base filing fee of 40000 cents and adds the
    surcharge of every disclosure item on the filing."
    PRD §3.2: "it is that category's surcharge — 1500 cents for `SOURCES`, 2500
    for `RECIPIENTS`, 1200 for `RETENTION`, 6000 for `SENSITIVE_CATEGORIES`, 1800
    for `OPT_OUT_MECHANISM`, and 7500 for `MINORS_DATA` — multiplied by 1.35 when
    that item's `covers_sensitive_categories` is true and by 1.0 when it is
    false, with the product rounded half up to a whole cent at that point."
    PRD §3.2: "The provisional fee is the base of 40000 cents plus the plain sum
    of those already-rounded per-item surcharges, with **no proration
    whatsoever**."
    PRD §3.2: "Both `provisional_filing_fee_cents` and `charged_fee_cents` are set
    to that amount, `fee_credit_cents` decreases by it while `fee_paid_cents`
    increases by the same amount (`fee_deposited_cents` does not move),
    `submitted_at` is set to the current clock instant, the parent broker's
    `version` increases by one, and a `REGISTRATION_SUBMITTED` audit event is
    appended."
    PRD §3.2: "A `BrokerAdmin` files with the state registry, moving the filing
    `DRAFT → SUBMITTED`."

    Design: Corner/calculations/disclosure_completeness_counts_optional_categories_at_declared_weights
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=500000, clock=CLOCK_TEST_INSTANT
    )
    registration = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code="CA"
    )
    items = add_disclosures(
        registration["id"],
        ctx["broker_headers"],
        categories=ALL_DISCLOSURE_CATEGORIES,
    )
    items_by_category = {item["category"]: item for item in items}

    sources = items_by_category["SOURCES"]
    assert_score_equals(sources["weight_credit"], "20.00", "weight_credit")
    assert sources["content_length"] == 93
    assert_cents_equals(sources["surcharge_cents"], 1500, "surcharge_cents")

    sensitive = items_by_category["SENSITIVE_CATEGORIES"]
    assert_score_equals(sensitive["weight_credit"], "12.00", "weight_credit")
    assert_cents_equals(sensitive["surcharge_cents"], 6000, "surcharge_cents")

    minors = items_by_category["MINORS_DATA"]
    assert_score_equals(minors["weight_credit"], "8.00", "weight_credit")
    assert_cents_equals(minors["surcharge_cents"], 7500, "surcharge_cents")

    drafted = fetch_registration(registration["id"], ctx["broker_headers"])
    assert_score_equals(
        drafted["disclosure_completeness_score"],
        "100.00",
        "disclosure_completeness_score",
    )

    response = api_client.submit_registration(
        registration["id"], ctx["broker_headers"]
    )
    submitted = validate_success(response, 200)
    assert submitted["status"] == "SUBMITTED"
    assert_cents_equals(
        submitted["provisional_filing_fee_cents"],
        60500,
        "provisional_filing_fee_cents",
    )
    assert_cents_equals(submitted["charged_fee_cents"], 60500, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 60500, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 439500, "fee_credit_cents")
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")


def test_late_acknowledgement_costs_five_points_and_keeps_the_recipient_active():
    """PRD §3.6: "Acknowledgement sets `acknowledged_at` to the current clock
    instant and sets `ack_was_late` true exactly when `acknowledged_at` is
    strictly after `due_at` — an acknowledgement landing exactly on `due_at` is on
    time."
    PRD §3.6: "When `recipient_id` is not null, the recipient's
    `on_time_ack_count` or `late_ack_count` increments accordingly and its
    reliability is re-scored."
    PRD §3.6: "The raw score starts at 90.00, gains 2.00 for each
    `on_time_ack_count`, loses 5.00 for each `late_ack_count`, loses 20.00 for
    each `fail_count`, and loses 25.00 for each `waive_count`."
    PRD §3.6: "Auto-suspension is strict: a re-scored recipient whose
    `reliability_score` falls strictly below 70.00 while its `status` is `ACTIVE`
    is moved `ACTIVE → SUSPENDED`; a score of exactly 70.00 stays `ACTIVE`, and
    69.99 suspends."
    PRD §3.5: "A downstream task records `target_kind` `DOWNSTREAM_RECIPIENT`, the
    `recipient_id` of its recipient, a `weight` of 20, and an `sla_days` taken
    from that recipient's own contractual `ack_sla_days`."
    PRD §3.5: "Every task's `due_at` is the execution clock instant advanced by
    its own `sla_days` whole days, which preserves time of day."
    PRD §3.6: "The task moves `DISPATCHED → ACKED`, which is terminal, the owning
    request's `acked_task_count` increases by one and `outstanding_task_count`
    decreases by one, its `completion_ratio` is recomputed, and a
    `PROPAGATION_ACKED` audit event is appended."
    PRD §3.6: "The numerator is the sum of `weight` over tasks in `ACKED`, plus
    one half of the sum of `weight` over tasks in `WAIVED`. The denominator is the
    sum of `weight` over **every** task of the request, with no status filter, so
    `ABANDONED` tasks remain in the denominator and contribute nothing to the
    numerator — which is precisely what makes the ratio fall when the sweep
    abandons work. The ratio is rounded half up to four decimal places, and is
    1.0000 by definition when the denominator is zero."

    Design: Corner/calculations/recipient_reliability_applies_the_late_ack_penalty_and_stays_active
    """
    ctx = setup_executing_deletion_request(
        clock=CLOCK_TEST_INSTANT,
        derived_profile_count=0,
        recipient_count=1,
        recipient_overrides={"contract_propagation_required": True, "ack_sla_days": 5},
        request_overrides={"requested_scope": "DELETE_ALL"},
    )
    task = find_task(
        ctx["request_id"], ctx["broker_headers"], target_kind="DOWNSTREAM_RECIPIENT"
    )
    dispatch_task(task["id"], ctx["broker_headers"])
    set_clock("2026-09-10T00:00:00Z")

    response = api_client.ack_propagation_task(task["id"], ctx["broker_headers"])
    acked = validate_success(response, 200)
    assert acked["status"] == "ACKED"
    assert_instant_equals(acked["due_at"], "2026-09-06T00:00:00.000Z", "due_at")
    assert_instant_equals(
        acked["acknowledged_at"], "2026-09-10T00:00:00Z", "acknowledged_at"
    )
    assert acked["ack_was_late"] is True
    assert acked["weight"] == 20

    recipient = fetch_recipient(ctx["recipient_id"], ctx["broker_headers"])
    assert recipient["late_ack_count"] == 1
    assert recipient["on_time_ack_count"] == 0
    assert_score_equals(recipient["reliability_score"], "85.00", "reliability_score")
    assert recipient["status"] == "ACTIVE"

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["propagation_required_count"] == 3
    assert request["downstream_task_count"] == 1
    assert request["acked_task_count"] == 1
    assert request["outstanding_task_count"] == 2
    assert_ratio_equals(request["completion_ratio"], "0.2500")
    assert request["status"] == "EXECUTING"


def test_standing_turns_compliant_only_once_every_operating_state_is_covered():
    """PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or
    before the current clock instant while its `coverage_period_end` is strictly
    after it, the standing is `COMPLIANT`. Fourth and otherwise, the standing is
    `DELINQUENT`."
    PRD §3.1: "Because it holds no accepted filing anywhere yet, its
    `registry_standing` is initialised to `DELINQUENT` and its `delinquent_since`
    is set to the enrolment instant, which is also its `created_at`."
    PRD §3.1: "On a transition into `COMPLIANT`, `delinquent_since` is cleared to
    null."
    PRD §3.1: "When the derived value actually differs from the stored one, a
    `STANDING_CHANGED` audit event is appended; when it comes out the same,
    nothing is appended and no downstream cascade fires."
    PRD §3.2: "Acceptance recomputes `coverage_days` as the whole number of days
    in the half-open interval and then runs the final variant of the fee
    calculation, which prorates."
    PRD §3.2: "The proration ratio is `coverage_days` divided by 365, capped at
    1.0 so that a coverage period longer than a year is never charged more than a
    full year."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount
    and `charged_fee_cents` is reset to it."
    PRD §3.2: "The settlement delta is the final fee minus the provisional fee:
    when that delta is negative, the broker's `fee_paid_cents` decreases by its
    magnitude and `fee_credit_cents` increases by the same magnitude (the
    over-charge is refunded to credit); when it is positive, the movement runs the
    other way, from credit into paid. `fee_deposited_cents` never changes during
    settlement."
    PRD §3.2: "A `PlatformAdmin` acting as registry examiner accepts a `SUBMITTED`
    filing, moving it `SUBMITTED → ACCEPTED`."

    Design: Corner/calculations/registry_standing_requires_every_operating_state_to_be_covered
    """
    ctx = onboard_broker(
        operating_state_codes=("CA", "NV"),
        deposit_cents=500000,
        clock=CLOCK_TEST_INSTANT,
    )
    california = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code="CA"
    )
    add_disclosures(california["id"], ctx["broker_headers"])
    submit_registration(california["id"], ctx["broker_headers"])
    accept_registration(california["id"])

    half_covered = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert half_covered["registry_standing"] == "DELINQUENT"
    assert_instant_equals(
        half_covered["delinquent_since"], "2026-09-01T00:00:00Z", "delinquent_since"
    )

    nevada = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code="NV"
    )
    add_disclosures(nevada["id"], ctx["broker_headers"])
    submit_registration(nevada["id"], ctx["broker_headers"])

    response = api_client.accept_registration(
        nevada["id"], make_platform_admin_headers()
    )
    accepted = validate_success(response, 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["coverage_days"] == 181
    assert_cents_equals(
        accepted["provisional_filing_fee_cents"], 47000, "provisional_filing_fee_cents"
    )
    assert_cents_equals(
        accepted["final_filing_fee_cents"], 23307, "final_filing_fee_cents"
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["registry_standing"] == "COMPLIANT"
    assert broker["delinquent_since"] is None
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_cents_equals(broker["fee_paid_cents"], 46614, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 453386, "fee_credit_cents")

    assert (
        audit_event_total(ctx["broker_id"], ctx["broker_headers"], "STANDING_CHANGED")
        == 1
    )
