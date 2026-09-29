"""Authentication, role authorization, resource ownership and segregation of duties.

Every test builds its own state from scratch: the harness restarts the API server
and wipes the database before each individual test.
"""

import pytest

from test_helpers import (
    CLOCK_TEST_INSTANT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_disclosures,
    api_client,
    assert_cents_equals,
    assert_score_equals,
    fetch_broker,
    fetch_deletion_request,
    fetch_registration,
    make_consumer_headers,
    make_headers,
    make_platform_admin_headers,
    make_privacy_reviewer_headers,
    make_regulator_headers,
    onboard_broker,
    open_deletion_request,
    open_draft_registration,
    record_consumer,
    setup_verified_deletion_request,
    submit_registration,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER_WHO_DECIDED = "reviewer-alpha"
REVIEWER_WHO_EXECUTES = "reviewer-beta"


def _submitted_ca_filing() -> dict:
    """One broker funded with 500000 cents holding a SUBMITTED CA filing that
    covers 2026-09-01 through 2027-03-01 with all four required disclosures."""
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT)
    registration = open_draft_registration(ctx["broker_id"], ctx["broker_headers"])
    ctx["disclosures"] = add_disclosures(registration["id"], ctx["broker_headers"])
    ctx["registration"] = submit_registration(registration["id"], ctx["broker_headers"])
    ctx["registration_id"] = registration["id"]
    return ctx


def _verified_request_decided_by_alpha() -> dict:
    """A DELETE_ALL deletion request in VERIFIED for a consumer with no derived
    profiles and no downstream recipients, adjudicated by reviewer-alpha."""
    return setup_verified_deletion_request(
        clock=CLOCK_TEST_INSTANT,
        decider=make_privacy_reviewer_headers(REVIEWER_WHO_DECIDED),
        request_overrides={"requested_scope": "DELETE_ALL"},
        derived_profile_count=0,
        recipient_count=0,
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-User-Role": "BrokerAdmin", "Content-Type": "application/json"},
        make_headers("", "BrokerAdmin"),
    ],
    ids=["no_auth_headers", "missing_user_id_header", "empty_user_id_header"],
)
def test_a_read_without_both_auth_headers_is_rejected_before_the_broker_lookup(headers):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, declaring the capacity it acts in."
    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD §2.6: "every rule below carries a priority, all applicable rules are
    considered, and the **lowest-numbered violated rule alone** determines the
    `error_id` and HTTP status returned"

    Design: Corner/rbac/missing_auth_headers_and_unknown_roles_are_rejected_before_lookup
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)

    response = api_client.get_broker(ctx["broker_id"], headers)

    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)
    assert response.json()["response_type"] == "error"


def test_an_unknown_role_is_rejected_before_the_broker_is_looked_up():
    """PRD §2.1: "If `X-User-Role` carries a string that is not one of the seven
    roles below, the rejection is `ERR_UNKNOWN_ROLE` (HTTP 401)."
    PRD §2.6: "`X-User-Role` names one of the seven declared roles — otherwise
    `ERR_UNKNOWN_ROLE` (401)."
    PRD §2.6: "The addressed or referenced `DataBroker` exists — otherwise
    `ERR_BROKER_NOT_FOUND` (404)."
    PRD §2.6: "every rule below carries a priority, all applicable rules are
    considered, and the **lowest-numbered violated rule alone** determines the
    `error_id` and HTTP status returned"

    Design: Corner/rbac/missing_auth_headers_and_unknown_roles_are_rejected_before_lookup
    """
    onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)

    response = api_client.get_broker(
        NON_EXISTENT_UUID, make_headers("someone", "DataJanitor")
    )

    error = validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE, 401)
    assert error["error_id"] != ApiErrorId.ERR_BROKER_NOT_FOUND.value
    assert response.json()["response_type"] == "error"


def test_broker_admin_cannot_accept_its_own_submitted_filing():
    """PRD §2.1: "A syntactically valid role that is not authorized for the addressed
    operation is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403), and a role that is
    authorized in general but reaches for a resource it does not own is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.2: "A `PlatformAdmin` acting as registry examiner accepts a `SUBMITTED`
    filing, moving it `SUBMITTED → ACCEPTED`."
    PRD §3.2: "The provisional fee is the base of 40000 cents plus the plain sum of
    those already-rounded per-item surcharges, with **no proration whatsoever**."
    PRD §3.2: "Both `provisional_filing_fee_cents` and `charged_fee_cents` are set to
    that amount, `fee_credit_cents` decreases by it while `fee_paid_cents` increases by
    the same amount (`fee_deposited_cents` does not move), `submitted_at` is set to the
    current clock instant, the parent broker's `version` increases by one, and a
    `REGISTRATION_SUBMITTED` audit event is appended."

    Design: Corner/rbac/broker_admin_cannot_accept_its_own_registration
    """
    ctx = _submitted_ca_filing()

    response = api_client.accept_registration(
        ctx["registration_id"], ctx["broker_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    filing = fetch_registration(ctx["registration_id"], ctx["broker_headers"])
    assert filing["status"] == "SUBMITTED"
    assert filing["accepted_at"] is None
    assert_cents_equals(filing["charged_fee_cents"], 47000, "charged_fee_cents")
    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 47000, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 453000, "fee_credit_cents")


def test_platform_admin_acceptance_of_the_same_filing_settles_the_final_fee():
    """PRD §3.2: "A `PlatformAdmin` acting as registry examiner accepts a `SUBMITTED`
    filing, moving it `SUBMITTED → ACCEPTED`."
    PRD §3.2: "The proration ratio is `coverage_days` divided by 365, capped at 1.0 so
    that a coverage period longer than a year is never charged more than a full year."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount and
    `charged_fee_cents` is reset to it."
    PRD §3.2: "The settlement delta is the final fee minus the provisional fee: when
    that delta is negative, the broker's `fee_paid_cents` decreases by its magnitude and
    `fee_credit_cents` increases by the same magnitude (the over-charge is refunded to
    credit); when it is positive, the movement runs the other way, from credit into paid."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of `ACCEPTED`,
    and a coverage period whose `coverage_period_start` is at or before the current clock
    instant while its `coverage_period_end` is strictly after it, the standing is
    `COMPLIANT`."

    Design: Corner/rbac/broker_admin_cannot_accept_its_own_registration
    """
    ctx = _submitted_ca_filing()

    response = api_client.accept_registration(
        ctx["registration_id"], make_platform_admin_headers()
    )

    filing = validate_success(response, 200)
    assert filing["status"] == "ACCEPTED"
    assert_cents_equals(filing["charged_fee_cents"], 23307, "charged_fee_cents")
    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 23307, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 476693, "fee_credit_cents")
    assert broker["registry_standing"] == "COMPLIANT"


def test_a_consumer_cannot_withdraw_another_consumers_deletion_request():
    """PRD §2.1: "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting
    `Consumer` row; ownership checks on any resource that references a consumer compare
    that resource's `consumer_id` to `X-User-ID`, and a consumer reading or driving its
    own record is compared against the addressed `Consumer.id` directly."
    PRD §3.4: "When the caller's role is `Consumer`, the acting `X-User-ID` must equal
    the request's `consumer_id`, or the withdrawal is refused with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.4: "Withdrawal moves the request to `WITHDRAWN`, decrements the broker's
    `request_open_count`, increments `request_terminated_count`, and appends a
    `DELETION_WITHDRAWN` audit event."

    Design: Corner/rbac/a_consumer_cannot_withdraw_another_consumers_deletion_request
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    consumer_a = record_consumer(ctx["broker_id"])
    consumer_b = record_consumer(ctx["broker_id"])
    request_a = open_deletion_request(
        ctx["broker_id"], consumer_a, headers=make_consumer_headers(consumer_a["id"])
    )
    request_b = open_deletion_request(
        ctx["broker_id"], consumer_b, headers=make_consumer_headers(consumer_b["id"])
    )

    response = api_client.withdraw_deletion_request(
        request_b["id"], make_consumer_headers(consumer_a["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
    assert (
        fetch_deletion_request(request_b["id"], ctx["broker_headers"])["status"]
        == "RECEIVED"
    )
    assert (
        fetch_deletion_request(request_a["id"], ctx["broker_headers"])["status"]
        == "RECEIVED"
    )

    owned = validate_success(
        api_client.withdraw_deletion_request(
            request_b["id"], make_consumer_headers(consumer_b["id"])
        ),
        200,
    )
    assert owned["status"] == "WITHDRAWN"
    _, meta = validate_paginated(
        api_client.list_audit_events(
            ctx["broker_id"],
            ctx["broker_headers"],
            params={"event_type": "DELETION_WITHDRAWN"},
        )
    )
    assert meta["total_count"] == 1


def test_a_broker_admin_cannot_read_another_brokers_audit_trail():
    """PRD §2.1: "When `X-User-Role` is `BrokerAdmin`, `X-User-ID` is the `id` of the
    acting `DataBroker`; ownership checks on any resource that references a broker compare
    that resource's `broker_id` to `X-User-ID`."
    PRD §2.6: "For an entity-backed role, `X-User-ID` matches the owning entity of the
    addressed resource: a `BrokerAdmin`'s `X-User-ID` equals the `DataBroker.id` reached
    through the resource's `broker_id`, and a `Consumer`'s `X-User-ID` equals the
    `Consumer.id` reached through the resource's `consumer_id` — otherwise
    `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD §3.1: "The enrolment appends a `BROKER_REGISTERED` audit event, which is
    therefore always sequence number 1 on that broker's trail."

    Design: Corner/rbac/a_broker_admin_cannot_read_another_brokers_audit_trail
    """
    alpha = onboard_broker(
        deposit_cents=0,
        clock=CLOCK_TEST_INSTANT,
        legal_name="Alpha Attribute Works",
        primary_contact_email="office@alpha.example",
    )
    beta = onboard_broker(
        deposit_cents=0,
        legal_name="Beta Household Index",
        primary_contact_email="office@beta.example",
    )

    response = api_client.list_audit_events(beta["broker_id"], alpha["broker_headers"])

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
    own_events, own_meta = validate_paginated(
        api_client.list_audit_events(alpha["broker_id"], alpha["broker_headers"])
    )
    assert own_meta["total_count"] == 1
    assert own_events[0]["event_type"] == "BROKER_REGISTERED"
    assert own_events[0]["sequence_no"] == 1


def test_the_reviewer_who_decided_the_verification_cannot_execute_the_deletion():
    """PRD §3.4: "Either decision records `verification_decided_by_user_id` as the acting
    `X-User-ID` and appends a `VERIFICATION_DECIDED` audit event."
    PRD §3.5: "And the acting `X-User-ID` must differ from the request's
    `verification_decided_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` answers — the
    reviewer who adjudicated identity may not also be the person who destroys the records,
    which is why the failed-then-reverified path preserves that user id."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each credited
    evidence point plus 0.20 times the `document_quality_score`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the maximum
    `assurance_score` across every attempt on the request, with no status filter, so it
    never regresses when a later attempt scores worse than an earlier one."

    Design: Corner/rbac/the_same_reviewer_cannot_decide_verification_and_then_execute
    """
    ctx = _verified_request_decided_by_alpha()
    assert_score_equals(
        ctx["request"]["identity_assurance_score"], 93.50, "identity_assurance_score"
    )
    assert ctx["request"]["verification_decided_by_user_id"] == REVIEWER_WHO_DECIDED

    response = api_client.execute_deletion_request(
        ctx["request_id"], make_privacy_reviewer_headers(REVIEWER_WHO_DECIDED)
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    refreshed = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert refreshed["status"] == "VERIFIED"
    assert refreshed["executed_at"] is None
    _, meta = validate_paginated(
        api_client.list_propagation_tasks(
            ctx["broker_headers"], params={"deletion_request_id": ctx["request_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_different_reviewer_executes_the_same_request_and_forks_its_plan():
    """PRD §3.5: "On success the request moves `VERIFIED → EXECUTING`,
    `executed_by_user_id` is set to the acting `X-User-ID` and `executed_at` to the
    current clock instant, the consumer's collection dimension moves to `PURGE_PENDING`
    with its `consent_status` untouched, and a `DELETION_EXECUTED` audit event is
    appended."
    PRD §3.5: "`ACTIVE_DATABASE` is always included."
    PRD §3.5: "`BACKUP_ARCHIVE` is included only when the request's `requested_scope` is
    `DELETE_ALL`, because backups are rewritten only for a full deletion and a
    `DELETE_SENSITIVE_ONLY` request leaves them alone."
    PRD §3.5: "`DERIVED_DATASET` is included only when the consumer's
    `derived_profile_count` is greater than zero."

    Design: Corner/rbac/the_same_reviewer_cannot_decide_verification_and_then_execute
    """
    ctx = _verified_request_decided_by_alpha()

    response = api_client.execute_deletion_request(
        ctx["request_id"], make_privacy_reviewer_headers(REVIEWER_WHO_EXECUTES)
    )

    executed = validate_success(response, 200)
    assert executed["status"] == "EXECUTING"
    assert executed["executed_by_user_id"] == REVIEWER_WHO_EXECUTES
    _, all_meta = validate_paginated(
        api_client.list_propagation_tasks(
            ctx["broker_headers"], params={"deletion_request_id": ctx["request_id"]}
        )
    )
    assert all_meta["total_count"] == 2
    for target_kind in ("ACTIVE_DATABASE", "BACKUP_ARCHIVE"):
        _, kind_meta = validate_paginated(
            api_client.list_propagation_tasks(
                ctx["broker_headers"],
                params={
                    "deletion_request_id": ctx["request_id"],
                    "target_kind": target_kind,
                },
            )
        )
        assert kind_meta["total_count"] == 1, target_kind


def test_the_regulator_reads_the_shared_surface_across_every_broker():
    """PRD §2.1: "`Regulator` is the state enforcement authority that opens, escalates,
    and closes inquiries and reads any broker's audit trail."
    PRD §2.10: "A broker's trail is readable in ascending `sequence_no` order and may be
    narrowed by `event_type`, by `subject_kind`, or by `subject_id`."
    PRD §3.3: "Creation also sets `opt_out_sale` and `opt_out_sharing` to false and
    `last_purged_at` to null, and appends a `CONSUMER_RECORDED` audit event."
    PRD §3.3: "Consumer records are readable individually and as a list, and the list may
    be narrowed by `broker_id`, by `identity_hash`, by `collection_status`, or by
    `consent_status`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` counts every record
    matching the applied filters before the page window is applied, and `has_more` states
    whether any record remains beyond the current window."

    Design: Corner/rbac/the_regulator_reads_the_shared_surface_across_every_broker
    """
    alpha = onboard_broker(
        deposit_cents=0,
        clock=CLOCK_TEST_INSTANT,
        legal_name="Alpha Attribute Works",
        primary_contact_email="office@alpha.example",
    )
    beta = onboard_broker(
        deposit_cents=0,
        legal_name="Beta Household Index",
        primary_contact_email="office@beta.example",
    )
    consumer = record_consumer(alpha["broker_id"])
    regulator_headers = make_regulator_headers("regulator-ca")

    alpha_events, alpha_meta = validate_paginated(
        api_client.list_audit_events(alpha["broker_id"], regulator_headers)
    )
    beta_events, beta_meta = validate_paginated(
        api_client.list_audit_events(beta["broker_id"], regulator_headers)
    )
    alpha_consumers, alpha_consumer_meta = validate_paginated(
        api_client.list_consumers(
            regulator_headers, params={"broker_id": alpha["broker_id"]}
        )
    )
    beta_consumers, beta_consumer_meta = validate_paginated(
        api_client.list_consumers(
            regulator_headers, params={"broker_id": beta["broker_id"]}
        )
    )

    assert alpha_meta["total_count"] == 2
    assert alpha_events[0]["event_type"] == "BROKER_REGISTERED"
    assert beta_meta["total_count"] == 1
    assert beta_events[0]["event_type"] == "BROKER_REGISTERED"
    assert alpha_consumer_meta["total_count"] == 1
    assert alpha_consumers[0]["id"] == consumer["id"]
    assert beta_consumer_meta["total_count"] == 0
    assert beta_consumer_meta["has_more"] is False
    assert beta_consumers == []
