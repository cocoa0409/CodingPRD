"""Freeze cascade, the consent loop, and request/record cross-entity dependencies."""
from test_helpers import (
    setup_verification_stack,
    setup_request_with_signed_attestation,
    setup_verified_span_stack,
    freeze_employer_to_active,
    release_freeze,
    lapse_freeze,
    get_employer,
    get_record,
    get_request,
    get_attestation,
    get_dispute,
    file_dispute,
    submit_request,
    permit_request,
    reconsent_request,
    validate_currency,
    get_verifier,
    set_clock,
    make_employer_headers,
    make_worker_headers,
    make_verifier_headers,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_freeze_cascade_freezes_records_and_declines_open_requests(api):
    """PRD §2.7: "Once `ACTIVE`, the freeze propagates outward in ordered hops: the
    employer's `EmploymentRecord` rows move to `FROZEN` and record the employer version
    they observed, every `VerificationRequest` of that employer sitting in `PERMITTED`
    or `VALIDATED` is declined with `EMPLOYER_FROZEN` and its fee released".
    PRD §2.7: "The instant a record freezes, it records in `frozen_by_employer_version`
    the employer version that stood immediately before the freeze cascade's own version
    increment".

    Design: Difficulty/transitive_cascade/freeze_cascade_freezes_records_declines_requests_and_invalidates_attestations
    """
    ctx = setup_request_with_signed_attestation(clock="2026-09-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    record_id = ctx["record"]["id"]
    request_id = ctx["request"]["id"]

    freeze_employer_to_active(employer_id)

    record = get_record(record_id)
    assert record["currency_state"] == "FROZEN"
    assert record["frozen_by_employer_version"] is not None

    request = get_request(request_id, make_verifier_headers(ctx["verifier"]["id"]))
    assert request["request_state"] == "DECLINED"
    assert request["decline_reason"] == "EMPLOYER_FROZEN"

    attestation = get_attestation(ctx["attestation"]["id"], ctx["verifier"]["id"])
    assert attestation["attestation_state"] == "INVALIDATED"


def test_first_freeze_filing_only_requests_and_freezes_nothing(api):
    """PRD §2.7: "filing a freeze moves it to `REQUESTED` and records the
    `freeze_reason_code`".
    PRD §2.7: "A second filing against an employer already in `REQUESTED` activates the
    freeze".

    Design: Difficulty/transitive_cascade/freeze_cascade_freezes_records_declines_requests_and_invalidates_attestations
    """
    ctx = setup_request_with_signed_attestation(clock="2026-09-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    record_id = ctx["record"]["id"]

    first = api.freeze_employer(employer_id, "EMPLOYER_DIRECTIVE", make_employer_headers(employer_id))
    requested = validate_success(first, 200)
    assert requested["freeze_state"] == "REQUESTED"
    assert requested["freeze_reason_code"] == "EMPLOYER_DIRECTIVE"
    assert get_record(record_id)["currency_state"] == "CURRENT"


def test_release_moves_frozen_records_to_stale_and_clears_the_recorded_version(api):
    """PRD §2.7: "Releasing or lapsing the freeze runs the same cascade in reverse by
    moving frozen records to `STALE` and clearing the recorded employer version".

    Design: Difficulty/transitive_cascade/freeze_cascade_freezes_records_declines_requests_and_invalidates_attestations
    """
    ctx = setup_verification_stack(clock="2026-09-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    record_id = ctx["record"]["id"]

    freeze_employer_to_active(employer_id)
    assert get_record(record_id)["currency_state"] == "FROZEN"

    released = release_freeze(employer_id)
    assert released["freeze_state"] == "RELEASED"
    record = get_record(record_id)
    assert record["currency_state"] == "STALE"
    assert record["frozen_by_employer_version"] is None


def test_dispute_filing_is_refused_while_the_employer_freeze_is_active(api):
    """PRD §3.6: "Filing is permitted only when the worker owns the span's
    `covered_worker_id`, the span's employer has `freeze_state` `NONE`, and the span's
    `currency_state` is not `FROZEN`; aim it at a frozen span and the freeze guard of
    §2.10 refuses it with `ERR_EMPLOYER_FROZEN` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/record_dispute_requires_owning_employer_unfrozen
    """
    ctx = setup_verified_span_stack(pay_period_end_date="2026-08-31T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    record_id = ctx["record"]["id"]

    freeze_employer_to_active(employer_id)
    version = get_record(record_id)["version"]
    response = api.create_dispute(
        {
            "employment_record_id": record_id,
            "covered_worker_id": worker_id,
            "claimed_field": "EMPLOYMENT_STATUS",
            "claimed_correct_value": "TERMINATED",
            "expected_employment_record_version": version,
        },
        make_worker_headers(worker_id),
    )
    validate_error(response, ApiErrorId.ERR_EMPLOYER_FROZEN)


def test_dispute_filing_succeeds_after_the_freeze_is_released(api):
    """PRD §2.7: "lapsed and released employers can be frozen again, returning
    `freeze_state` to `NONE`."

    Design: Difficulty/cross_entity_state_dependency/record_dispute_requires_owning_employer_unfrozen
    """
    ctx = setup_verified_span_stack(pay_period_end_date="2026-08-31T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    record_id = ctx["record"]["id"]

    freeze_employer_to_active(employer_id)
    released = release_freeze(employer_id)
    assert released["freeze_state"] == "RELEASED"
    assert get_record(record_id)["currency_state"] == "STALE"

    dispute = file_dispute(worker_id, record_id)
    assert dispute["dispute_state"] == "AWAITING_EMPLOYER"
    assert get_record(record_id)["record_state"] == "DISPUTED"


def test_validated_request_reopens_after_a_resolved_record_leaves_current(api):
    """PRD §3.5: "If any resolved record later moves out of `CURRENT` — a stale feed,
    a freeze — the request falls back from `VALIDATED` to `PERMITTED`, resets
    `records_matched_count` to 0, and decrements `transaction_count` by one so the
    count reflects only live validations."

    Design: Difficulty/cross_entity_state_dependency/validated_request_reopens_when_a_resolved_record_leaves_current
    """
    ctx = setup_verification_stack(
        clock="2026-09-01T00:00:00Z",
        validate=True,
        pay_period_end_date="2026-08-31T00:00:00Z",
    )
    request_id = ctx["request"]["id"]
    verifier_id = ctx["verifier"]["id"]

    assert get_request(request_id, make_verifier_headers(verifier_id))["records_matched_count"] == 1
    assert get_verifier(verifier_id, make_verifier_headers(verifier_id))["transaction_count"] == 1

    set_clock("2026-10-01T00:00:00Z")
    request = get_request(request_id, make_verifier_headers(verifier_id))
    assert request["request_state"] == "PERMITTED"
    assert request["records_matched_count"] == 0


def test_stale_feed_releases_the_matched_count_and_the_transaction_count(api):
    """PRD §3.5: "resets `records_matched_count` to 0, and decrements
    `transaction_count` by one".
    PRD §3.8: "an employer is `CURRENT` while its staleness is no greater than one
    cadence interval, `DELAYED` while staleness is greater than one interval and no
    greater than three intervals".

    Design: Difficulty/cross_entity_state_dependency/validated_request_reopens_when_a_resolved_record_leaves_current
    """
    ctx = setup_verification_stack(
        clock="2026-09-01T00:00:00Z",
        validate=True,
        pay_period_end_date="2026-08-31T00:00:00Z",
    )
    request_id = ctx["request"]["id"]
    verifier_id = ctx["verifier"]["id"]
    record_id = ctx["record"]["id"]

    set_clock("2026-10-01T00:00:00Z")
    request = get_request(request_id, make_verifier_headers(verifier_id))
    assert request["request_state"] == "PERMITTED"
    assert request["records_matched_count"] == 0
    assert get_verifier(verifier_id, make_verifier_headers(verifier_id))["transaction_count"] == 0
    assert get_employer(ctx["employer"]["id"])["feed_status"] == "DELAYED"
    assert get_record(record_id)["currency_state"] == "STALE"


def test_permit_reconsent_permit_loop_re_snapshots_the_tier(api):
    """PRD §2.13: "A `PERMITTED` request may be returned to `SUBMITTED` by the worker —
    clearing its `resolved_product_tier` and its `consumer_authorization_id` — but only
    once at least 7 days have elapsed since its `submitted_at`".

    Design: Difficulty/non_linear_state_machine/verification_request_permitted_reconsent_then_permit_again_loop
    """
    ctx = setup_verification_stack()
    request_id = ctx["request"]["id"]
    worker_id = ctx["worker"]["id"]
    auth_id = ctx["authorization"]["id"]
    verifier_id = ctx["verifier"]["id"]

    assert get_request(request_id, make_verifier_headers(verifier_id))["resolved_product_tier"] == "EMPLOYMENT_INCOME"
    set_clock("2026-09-15T00:00:00Z")
    after_reconsent = reconsent_request(worker_id, request_id)
    assert after_reconsent["request_state"] == "SUBMITTED"
    assert after_reconsent["resolved_product_tier"] is None

    again = permit_request(worker_id, request_id, auth_id)
    assert again["request_state"] == "PERMITTED"
    assert again["resolved_product_tier"] == "EMPLOYMENT_INCOME"


def test_consent_loop_leaves_no_response_and_no_counted_transaction(api):
    """PRD §3.5: "A requesting party's `transaction_count` counts the requests it has
    taken to `VALIDATED` or `RESPONDED`."

    Design: Difficulty/non_linear_state_machine/verification_request_permitted_reconsent_then_permit_again_loop
    """
    from test_helpers import list_responses
    ctx = setup_verification_stack()
    request_id = ctx["request"]["id"]
    worker_id = ctx["worker"]["id"]
    verifier_id = ctx["verifier"]["id"]

    set_clock("2026-09-15T00:00:00Z")
    reconsent_request(worker_id, request_id)
    permit_request(worker_id, request_id, ctx["authorization"]["id"])

    assert list_responses(request_id, verifier_id) == []
    assert get_verifier(verifier_id, make_verifier_headers(verifier_id))["transaction_count"] == 0