"""Identity assurance scoring and the preconditions guarding execution."""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_BETA_HEADERS,
    ApiErrorId,
    accept_registration,
    add_disclosures,
    api_client,
    assert_cents_equals,
    assert_instant_equals,
    assert_ratio_equals,
    assert_score_equals,
    decide_verification,
    fetch_broker,
    fetch_consumer,
    fetch_deletion_request,
    fetch_registration,
    make_intake_agent_headers,
    make_state_platform_headers,
    onboard_broker,
    open_deletion_request,
    open_draft_registration,
    record_consumer,
    record_verification_attempt,
    setup_verified_deletion_request,
    submit_registration,
    validate_error,
    validate_success,
)

PLATFORM_ASSERTION_REFERENCE = "CA-DELETE-PLATFORM-2026-000771"


def _setup_request_on_channel(intake_channel, headers):
    """One broker, one consumer with no sensitive categories, and one RECEIVED
    deletion request taken in over `intake_channel`."""
    ctx = onboard_broker(operating_state_codes=("CA",), clock=CLOCK_TEST_INSTANT)
    consumer = record_consumer(
        ctx["broker_id"], state_code="CA", derived_profile_count=0
    )
    request = open_deletion_request(
        ctx["broker_id"], consumer, headers=headers, intake_channel=intake_channel
    )
    ctx["consumer"] = consumer
    ctx["consumer_id"] = consumer["id"]
    ctx["request"] = request
    ctx["request_id"] = request["id"]
    return ctx


def test_platform_asserted_variant_floors_a_zero_evidence_assertion_at_seventy():
    """PRD §3.4: "The calculation then selects one of two variants, and the selection requires three conditions to hold together: the `method` must be `PLATFORM_ASSERTION`, the `platform_assertion_reference` must be non-null, and the owning request's `intake_channel` must be `STATE_PLATFORM`."
    PRD §3.4: "When all three hold, `variant_applied` is `PLATFORM_ASSERTED`, and the score is the raw score minus the fraud penalty, raised to a floor of 70.00 if it came out lower, capped at a ceiling of 100.00 if it came out higher, and rounded half up to two decimal places."
    PRD §3.4: "The centralized platform's assertion substitutes that floor of 70.00, so a zero-evidence platform assertion scores exactly 70.00 and passes."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each credited evidence point plus 0.20 times the `document_quality_score`."
    PRD §3.4: "The `fraud_penalty_applied` is 12.00 multiplied by the number of failed attempts already on this request, using `failed_attempt_count` **as it stands before this attempt is scored**; the attempt currently being scored never penalises itself."
    PRD §3.4: "The attempt's `outcome` is derived from its `assurance_score` and is never accepted as input: `PASS` when the score is at least 70.00, `INCONCLUSIVE` when it is at least 50.00 but below 70.00, and `FAIL` when it is below 50.00."
    PRD §3.4: "A request's attempts are readable as a list, narrowable by `outcome` or by `method`, with their variant and score breakdown intact."

    Design: Difficulty/dual_variant_calc/identity_assurance_platform_asserted_floor_versus_fraud_weighted
    """
    state_platform = make_state_platform_headers()
    ctx = _setup_request_on_channel("STATE_PLATFORM", state_platform)

    attempt = record_verification_attempt(
        ctx["request_id"],
        state_platform,
        method="PLATFORM_ASSERTION",
        evidence_points_count=0,
        document_quality_score=0,
        platform_assertion_reference=PLATFORM_ASSERTION_REFERENCE,
    )

    assert attempt["variant_applied"] == "PLATFORM_ASSERTED"
    assert_score_equals(attempt["raw_score"], "25.00", "raw_score")
    assert_score_equals(
        attempt["fraud_penalty_applied"], "0.00", "fraud_penalty_applied"
    )
    assert_score_equals(attempt["assurance_score"], "70.00", "assurance_score")
    assert attempt["outcome"] == "PASS"


def test_platform_asserted_attempt_rolls_a_passing_score_up_to_the_request():
    """PRD §3.4: "The request's `identity_assurance_score` is then set to the maximum `assurance_score` across every attempt on the request, with no status filter, so it never regresses when a later attempt scores worse than an earlier one."
    PRD §3.4: "Recording the attempt increments the request's `verification_attempt_count` by one, and increments `failed_attempt_count` by one when the outcome is `FAIL`."
    PRD §3.4: "From `RECEIVED` the request moves `RECEIVED → VERIFICATION_PENDING`."

    Design: Difficulty/dual_variant_calc/identity_assurance_platform_asserted_floor_versus_fraud_weighted
    """
    state_platform = make_state_platform_headers()
    ctx = _setup_request_on_channel("STATE_PLATFORM", state_platform)

    record_verification_attempt(
        ctx["request_id"],
        state_platform,
        method="PLATFORM_ASSERTION",
        evidence_points_count=0,
        document_quality_score=0,
        platform_assertion_reference=PLATFORM_ASSERTION_REFERENCE,
    )

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert_score_equals(
        request["identity_assurance_score"], "70.00", "identity_assurance_score"
    )
    assert request["failed_attempt_count"] == 0
    assert request["verification_attempt_count"] == 1
    assert request["status"] == "VERIFICATION_PENDING"


def test_fraud_weighted_variant_scores_the_same_assertion_at_twenty_five_and_fails():
    """PRD §3.4: "When any of the three conditions fails — including a `PLATFORM_ASSERTION` method presented on a `DIRECT_PORTAL` request — `variant_applied` is `FRAUD_WEIGHTED`, and the score is the raw score minus the fraud penalty, raised to a floor of 0.00, capped at 100.00, and rounded half up to two decimal places."
    PRD §3.4: "No 70.00 floor applies in the fraud-weighted variant, so the burden of proof falls entirely on the evidence supplied and prior failures push the score toward failure; the same zero-evidence platform assertion that scores 70.00 and passes under `PLATFORM_ASSERTED` scores 25.00 and fails under `FRAUD_WEIGHTED`."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each credited evidence point plus 0.20 times the `document_quality_score`."
    PRD §3.4: "The attempt's `outcome` is derived from its `assurance_score` and is never accepted as input: `PASS` when the score is at least 70.00, `INCONCLUSIVE` when it is at least 50.00 but below 70.00, and `FAIL` when it is below 50.00."

    Design: Difficulty/dual_variant_calc/identity_assurance_platform_asserted_floor_versus_fraud_weighted
    """
    intake_agent = make_intake_agent_headers()
    ctx = _setup_request_on_channel("DIRECT_PORTAL", intake_agent)

    attempt = record_verification_attempt(
        ctx["request_id"],
        intake_agent,
        method="PLATFORM_ASSERTION",
        evidence_points_count=0,
        document_quality_score=0,
        platform_assertion_reference=PLATFORM_ASSERTION_REFERENCE,
    )

    assert attempt["variant_applied"] == "FRAUD_WEIGHTED"
    assert_score_equals(attempt["raw_score"], "25.00", "raw_score")
    assert_score_equals(attempt["assurance_score"], "25.00", "assurance_score")
    assert attempt["outcome"] == "FAIL"


def test_a_failing_attempt_is_counted_and_still_leaves_the_request_pending():
    """PRD §3.4: "Recording the attempt increments the request's `verification_attempt_count` by one, and increments `failed_attempt_count` by one when the outcome is `FAIL`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the maximum `assurance_score` across every attempt on the request, with no status filter, so it never regresses when a later attempt scores worse than an earlier one."
    PRD §3.4: "From `RECEIVED` the request moves `RECEIVED → VERIFICATION_PENDING`."

    Design: Difficulty/dual_variant_calc/identity_assurance_platform_asserted_floor_versus_fraud_weighted
    """
    intake_agent = make_intake_agent_headers()
    ctx = _setup_request_on_channel("DIRECT_PORTAL", intake_agent)

    record_verification_attempt(
        ctx["request_id"],
        intake_agent,
        method="PLATFORM_ASSERTION",
        evidence_points_count=0,
        document_quality_score=0,
        platform_assertion_reference=PLATFORM_ASSERTION_REFERENCE,
    )

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert_score_equals(
        request["identity_assurance_score"], "25.00", "identity_assurance_score"
    )
    assert request["failed_attempt_count"] == 1
    assert request["verification_attempt_count"] == 1
    assert request["status"] == "VERIFICATION_PENDING"


def _setup_draft_only_filing_with_received_request():
    """A broker whose only CA filing is still `DRAFT` — every required disclosure
    is attached but it was never submitted or accepted — plus one CA consumer and
    one `RECEIVED` deletion request for that consumer."""
    ctx = onboard_broker(operating_state_codes=("CA",), clock=CLOCK_TEST_INSTANT)
    registration = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code="CA"
    )
    add_disclosures(registration["id"], ctx["broker_headers"])
    consumer = record_consumer(
        ctx["broker_id"], state_code="CA", derived_profile_count=0
    )
    request = open_deletion_request(
        ctx["broker_id"], consumer, intake_channel="DIRECT_PORTAL"
    )
    ctx["registration"] = registration
    ctx["registration_id"] = registration["id"]
    ctx["consumer"] = consumer
    ctx["consumer_id"] = consumer["id"]
    ctx["request"] = request
    ctx["request_id"] = request["id"]
    return ctx


def test_execute_on_a_received_request_answers_the_state_precondition_first():
    """PRD §2.6: "The compliance office resolves that deterministically: every rule below carries a priority, all applicable rules are considered, and the **lowest-numbered violated rule alone** determines the `error_id` and HTTP status returned."
    PRD §2.6: "Nothing later in the list can mask something earlier in it, and a request that reaches the end of the list without a violation is executed."
    PRD §3.5: "A `PrivacyReviewer` or a `BrokerAdmin` executes a request that is in `VERIFIED`, and four preconditions are checked in the priority order of §2.6."
    PRD §3.5: "The request must be in `VERIFIED`, or `ERR_REQUEST_INVALID_STATE` answers."
    PRD §3.5: "The broker must hold an `ACCEPTED` filing for the consumer's `state_code` whose half-open coverage period contains the current clock instant, or `ERR_NO_ACCEPTED_REGISTRATION` answers."

    Design: Difficulty/priority_pair_validation_conflict/execute_request_state_precondition_outranks_missing_accepted_registration
    """
    ctx = _setup_draft_only_filing_with_received_request()

    response = api_client.execute_deletion_request(
        ctx["request_id"], REVIEWER_BETA_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_REQUEST_INVALID_STATE, 409)

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "RECEIVED"
    assert request["executed_at"] is None


def test_execute_after_verification_surfaces_the_missing_accepted_registration():
    """PRD §3.5: "The broker must hold an `ACCEPTED` filing for the consumer's `state_code` whose half-open coverage period contains the current clock instant, or `ERR_NO_ACCEPTED_REGISTRATION` answers."
    PRD §3.4: "`VERIFIED` moves the request `VERIFICATION_PENDING → VERIFIED`; `FAILED` moves it `VERIFICATION_PENDING → VERIFICATION_FAILED`, which is not terminal, because a further verification attempt reopens it."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each credited evidence point plus 0.20 times the `document_quality_score`."
    PRD §3.4: "The method base values are 55.00 for `GOVT_ID`, 30.00 for `TWO_DATA_POINTS`, 25.00 for `PLATFORM_ASSERTION`, and 35.00 for `AGENT_LOA`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the maximum `assurance_score` across every attempt on the request, with no status filter, so it never regresses when a later attempt scores worse than an earlier one."
    PRD §3.5: "On success the request moves `VERIFIED → EXECUTING`, `executed_by_user_id` is set to the acting `X-User-ID` and `executed_at` to the current clock instant, the consumer's collection dimension moves to `PURGE_PENDING` with its `consent_status` untouched, and a `DELETION_EXECUTED` audit event is appended."

    Design: Difficulty/priority_pair_validation_conflict/execute_request_state_precondition_outranks_missing_accepted_registration
    """
    ctx = _setup_draft_only_filing_with_received_request()
    validate_error(
        api_client.execute_deletion_request(ctx["request_id"], REVIEWER_BETA_HEADERS),
        ApiErrorId.ERR_REQUEST_INVALID_STATE,
        409,
    )

    record_verification_attempt(
        ctx["request_id"],
        method="GOVT_ID",
        evidence_points_count=3,
        document_quality_score=80,
    )
    decide_verification(ctx["request_id"], "VERIFIED")

    response = api_client.execute_deletion_request(
        ctx["request_id"], REVIEWER_BETA_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_NO_ACCEPTED_REGISTRATION, 409)

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "VERIFIED"
    assert_score_equals(
        request["identity_assurance_score"], "93.50", "identity_assurance_score"
    )
    assert request["propagation_required_count"] == 0
    assert request["executed_at"] is None

    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "ACTIVE"
    assert (
        fetch_registration(ctx["registration_id"], ctx["broker_headers"])["status"]
        == "DRAFT"
    )


def _setup_verified_request_for_an_uncovered_state():
    """A broker operating in CA and NV whose only ACCEPTED filing is the CA one,
    plus a VERIFIED deletion request for a consumer resident in NV."""
    return setup_verified_deletion_request(
        state_code="CA",
        operating_state_codes=("CA", "NV"),
        consumer_state_code="NV",
        clock=CLOCK_TEST_INSTANT,
    )


def _accept_filing_for_state(ctx, state_code):
    """Carry a fresh filing for `state_code` from DRAFT through to ACCEPTED."""
    registration = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code=state_code
    )
    add_disclosures(registration["id"], ctx["broker_headers"])
    submit_registration(registration["id"], ctx["broker_headers"])
    return accept_registration(registration["id"])


def test_execute_refused_when_no_accepted_filing_covers_the_consumers_state():
    """PRD §2.6: "The broker holds an `ACCEPTED` registration for the consumer's `state_code` whose half-open coverage period contains the current clock instant — otherwise `ERR_NO_ACCEPTED_REGISTRATION` (409)."
    PRD §3.5: "The broker must hold an `ACCEPTED` filing for the consumer's `state_code` whose half-open coverage period contains the current clock instant, or `ERR_NO_ACCEPTED_REGISTRATION` answers."
    PRD §3.5: "On success the request moves `VERIFIED → EXECUTING`, `executed_by_user_id` is set to the acting `X-User-ID` and `executed_at` to the current clock instant, the consumer's collection dimension moves to `PURGE_PENDING` with its `consent_status` untouched, and a `DELETION_EXECUTED` audit event is appended."

    Design: Difficulty/cross_entity_state_dependency/execute_gated_on_an_accepted_registration_for_the_consumers_own_state
    """
    ctx = _setup_verified_request_for_an_uncovered_state()

    response = api_client.execute_deletion_request(
        ctx["request_id"], REVIEWER_BETA_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_NO_ACCEPTED_REGISTRATION, 409)

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "VERIFIED"
    assert request["executed_at"] is None
    assert (
        fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])["collection_status"]
        == "ACTIVE"
    )


def test_execute_succeeds_once_the_consumers_own_state_is_covered():
    """PRD §3.5: "On success the request moves `VERIFIED → EXECUTING`, `executed_by_user_id` is set to the acting `X-User-ID` and `executed_at` to the current clock instant, the consumer's collection dimension moves to `PURGE_PENDING` with its `consent_status` untouched, and a `DELETION_EXECUTED` audit event is appended."
    PRD §3.5: "`ACTIVE_DATABASE` is always included."
    PRD §3.5: "`BACKUP_ARCHIVE` is included only when the request's `requested_scope` is `DELETE_ALL`, because backups are rewritten only for a full deletion and a `DELETE_SENSITIVE_ONLY` request leaves them alone."
    PRD §3.5: "`DERIVED_DATASET` is included only when the consumer's `derived_profile_count` is greater than zero."
    PRD §3.5: "The request's counters are then set from the minted set: `propagation_required_count` is the number of internal targets plus the number of eligible recipients, `downstream_task_count` is the number of eligible recipients alone, and `outstanding_task_count` starts equal to `propagation_required_count`."
    PRD §3.5: "`completion_ratio` is computed at the fork and is 0.0000, because nothing has been acknowledged yet."

    Design: Difficulty/cross_entity_state_dependency/execute_gated_on_an_accepted_registration_for_the_consumers_own_state
    """
    ctx = _setup_verified_request_for_an_uncovered_state()
    validate_error(
        api_client.execute_deletion_request(ctx["request_id"], REVIEWER_BETA_HEADERS),
        ApiErrorId.ERR_NO_ACCEPTED_REGISTRATION,
        409,
    )

    _accept_filing_for_state(ctx, "NV")

    executed = validate_success(
        api_client.execute_deletion_request(ctx["request_id"], REVIEWER_BETA_HEADERS),
        200,
    )
    assert executed["status"] == "EXECUTING"
    assert_instant_equals(executed["executed_at"], CLOCK_TEST_INSTANT, "executed_at")
    assert executed["propagation_required_count"] == 2
    assert executed["downstream_task_count"] == 0
    assert executed["outstanding_task_count"] == 2
    assert_ratio_equals(executed["completion_ratio"], "0.0000")
    assert (
        fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])["collection_status"]
        == "PURGE_PENDING"
    )


def test_accepting_the_missing_state_filing_settles_the_fee_and_restores_standing():
    """PRD §3.2: "The final fee is computed by first aggregating the base 40000 cents with the same sum of per-item surcharges (re-read as the disclosure set stands **at acceptance time**, so a disclosure added during a rejection-and-revision loop changes the final fee relative to the provisional fee frozen at the earlier submission), then multiplying that aggregate by a proration ratio, and only then rounding half up to a whole cent — exactly one rounding step, applied at the very end."
    PRD §3.2: "The proration ratio is `coverage_days` divided by 365, capped at 1.0 so that a coverage period longer than a year is never charged more than a full year."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount and `charged_fee_cents` is reset to it."
    PRD §3.2: "The settlement delta is the final fee minus the provisional fee: when that delta is negative, the broker's `fee_paid_cents` decreases by its magnitude and `fee_credit_cents` increases by the same magnitude (the over-charge is refunded to credit); when it is positive, the movement runs the other way, from credit into paid."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one registration of this broker with a matching `state_code`, a `status` of `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or before the current clock instant while its `coverage_period_end` is strictly after it, the standing is `COMPLIANT`."
    PRD §3.1: "On a transition into `COMPLIANT`, `delinquent_since` is cleared to null."

    Design: Difficulty/cross_entity_state_dependency/execute_gated_on_an_accepted_registration_for_the_consumers_own_state
    """
    ctx = _setup_verified_request_for_an_uncovered_state()
    validate_error(
        api_client.execute_deletion_request(ctx["request_id"], REVIEWER_BETA_HEADERS),
        ApiErrorId.ERR_NO_ACCEPTED_REGISTRATION,
        409,
    )

    nv_registration = _accept_filing_for_state(ctx, "NV")
    validate_success(
        api_client.execute_deletion_request(ctx["request_id"], REVIEWER_BETA_HEADERS),
        200,
    )

    assert nv_registration["status"] == "ACCEPTED"
    assert_cents_equals(
        nv_registration["final_filing_fee_cents"], 23307, "final_filing_fee_cents"
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["registry_standing"] == "COMPLIANT"
    assert broker["delinquent_since"] is None
    assert_cents_equals(broker["fee_paid_cents"], 46614, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 453386, "fee_credit_cents")
