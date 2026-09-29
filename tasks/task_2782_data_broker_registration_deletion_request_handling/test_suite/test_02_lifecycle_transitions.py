"""Lifecycle transitions the compliance office declares, and the ones it refuses.

Each test drives one parallel state machine of the contract — registry filings,
downstream recipients, deletion requests, propagation tasks, suppression
windows, the consumer consent dimension and regulator inquiries — and pins both
the transition itself and the counters or audit events it is allowed to move.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_ALPHA_HEADERS,
    REVIEWER_BETA_HEADERS,
    ApiErrorId,
    api_client,
    assert_cents_equals,
    assert_instant_equals,
    assert_ratio_equals,
    assert_score_equals,
    create_downstream_recipient_payload,
    create_suppression_entry,
    fetch_broker,
    fetch_consumer,
    fetch_deletion_request,
    fetch_inquiry,
    fetch_propagation_task,
    fetch_recipient,
    fetch_registration,
    fetch_suppression_entry,
    find_task,
    make_consumer_headers,
    make_platform_admin_headers,
    make_privacy_reviewer_headers,
    make_regulator_headers,
    onboard_broker,
    open_deletion_request,
    open_draft_registration,
    open_inquiry,
    record_consumer,
    register_recipient,
    set_recipient_status,
    setup_executing_deletion_request,
    setup_verified_deletion_request,
    validate_error,
    validate_paginated,
    validate_success,
)

LIFT_JUSTIFICATION_FIRST = (
    "Suppression lifted after the consumer submitted a fresh opt-in for "
    "marketing contact."
)
LIFT_JUSTIFICATION_SECOND = (
    "Duplicate lift attempt filed by a second reviewer working the same queue "
    "item."
)


def audit_event_total(broker_id, headers, event_type):
    """How many events of one type the broker's trail carries."""
    response = api_client.list_audit_events(
        broker_id, headers, params={"event_type": event_type}
    )
    _, meta = validate_paginated(response)
    return meta["total_count"]


def test_accept_from_draft_is_refused_and_settles_no_fee():
    """PRD §2.6: "The registration's current `status` declares the requested
    transition: `DRAFT` or `REJECTED` for disclosure insertion, `DRAFT` for
    submit, `SUBMITTED` for accept and for reject, and any of `DRAFT`,
    `SUBMITTED`, or `ACCEPTED` for withdraw — otherwise
    `ERR_REGISTRATION_INVALID_STATE` (409)."
    PRD §3.2: "A `PlatformAdmin` acting as registry examiner accepts a
    `SUBMITTED` filing, moving it `SUBMITTED → ACCEPTED`."
    PRD §3.2: "The filing is created in `DRAFT` with a
    `disclosure_completeness_score` of 0.00, a `revision_count` of 0, a
    `charged_fee_cents` of 0, a `provisional_filing_fee_cents` of 0, a null
    `final_filing_fee_cents`, null `submitted_at` and `accepted_at`, and a null
    `rejection_reason_code`."
    PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."

    Design: Corner/state_machines/registration_accept_attempted_from_draft_rejected
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=500000, clock=CLOCK_TEST_INSTANT
    )
    registration = open_draft_registration(
        ctx["broker_id"], ctx["broker_headers"], state_code="CA"
    )
    assert registration["status"] == "DRAFT"

    response = api_client.accept_registration(
        registration["id"], make_platform_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_REGISTRATION_INVALID_STATE, 409)

    stored = fetch_registration(registration["id"], ctx["broker_headers"])
    assert stored["status"] == "DRAFT"
    assert stored["accepted_at"] is None
    assert_cents_equals(stored["charged_fee_cents"], 0, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 500000, "fee_credit_cents")


def test_new_downstream_recipient_starts_active_at_the_reliability_baseline():
    """PRD §3.6: "The recipient starts `ACTIVE` with `reliability_score` at
    90.00 and all four lifetime counters — `on_time_ack_count`,
    `late_ack_count`, `fail_count`, and `waive_count` — at zero, and a
    `RECIPIENT_REGISTERED` audit event is appended."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"
    PRD §4: "Every creation endpoint answers 201 with the created resource in
    `data`"

    Design: Corner/state_machines/downstream_recipient_starts_active_at_the_reliability_baseline
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    payload = create_downstream_recipient_payload(
        ctx["broker_id"],
        name="Northwind Audience Partners",
        contract_propagation_required=True,
        ack_sla_days=5,
    )

    response = api_client.create_downstream_recipient(payload, ctx["broker_headers"])
    recipient = validate_success(response, 201)

    assert recipient["status"] == "ACTIVE"
    assert_score_equals(recipient["reliability_score"], "90.00", "reliability_score")
    assert recipient["on_time_ack_count"] == 0
    assert recipient["late_ack_count"] == 0
    assert recipient["fail_count"] == 0
    assert recipient["waive_count"] == 0
    assert recipient["version"] == 1


def test_execute_forks_the_pinned_internal_target_set_in_order():
    """PRD §3.5: "On success the request moves `VERIFIED → EXECUTING`,
    `executed_by_user_id` is set to the acting `X-User-ID` and `executed_at` to
    the current clock instant, the consumer's collection dimension moves to
    `PURGE_PENDING` with its `consent_status` untouched, and a
    `DELETION_EXECUTED` audit event is appended."
    PRD §3.5: "`ACTIVE_DATABASE` is always included."
    PRD §3.5: "`BACKUP_ARCHIVE` is included only when the request's
    `requested_scope` is `DELETE_ALL`, because backups are rewritten only for a
    full deletion and a `DELETE_SENSITIVE_ONLY` request leaves them alone."
    PRD §3.5: "`DERIVED_DATASET` is included only when the consumer's
    `derived_profile_count` is greater than zero."
    PRD §3.5: "The minting order is pinned: first the internal targets in the
    literal order `ACTIVE_DATABASE`, `BACKUP_ARCHIVE`, `DERIVED_DATASET`, then
    the ranked recipients."
    PRD §3.5: "An internal task records its `target_kind`, a null
    `recipient_id`, a `weight` of 40 for `ACTIVE_DATABASE`, 20 for
    `BACKUP_ARCHIVE`, and 20 for `DERIVED_DATASET`, and an `sla_days` of 5 for
    `ACTIVE_DATABASE`, 45 for `BACKUP_ARCHIVE`, and 15 for `DERIVED_DATASET`"
    PRD §3.5: "Every task's `due_at` is the execution clock instant advanced by
    its own `sla_days` whole days, which preserves time of day."
    PRD §3.5: "The request's counters are then set from the minted set:
    `propagation_required_count` is the number of internal targets plus the
    number of eligible recipients, `downstream_task_count` is the number of
    eligible recipients alone, and `outstanding_task_count` starts equal to
    `propagation_required_count`."
    PRD §3.5: "`completion_ratio` is computed at the fork and is 0.0000, because
    nothing has been acknowledged yet."
    PRD §3.3: "a consumer created with an empty `sensitive_categories` array
    starts in `NOT_REQUIRED`"

    Design: Corner/state_machines/execute_forks_the_pinned_internal_target_set_in_order
    """
    ctx = setup_verified_deletion_request(
        clock=CLOCK_TEST_INSTANT,
        derived_profile_count=0,
        recipient_count=0,
        request_overrides={"requested_scope": "DELETE_ALL"},
    )

    response = api_client.execute_deletion_request(
        ctx["request_id"], REVIEWER_BETA_HEADERS
    )
    request = validate_success(response, 200)

    assert request["status"] == "EXECUTING"
    assert request["propagation_required_count"] == 2
    assert request["downstream_task_count"] == 0
    assert request["outstanding_task_count"] == 2
    assert_ratio_equals(request["completion_ratio"], "0.0000")
    assert request["executed_by_user_id"] == "reviewer-beta"
    assert_instant_equals(request["executed_at"], "2026-09-01T00:00:00Z", "executed_at")

    listing = api_client.list_propagation_tasks(
        REVIEWER_BETA_HEADERS, params={"deletion_request_id": ctx["request_id"]}
    )
    tasks, meta = validate_paginated(listing)
    assert meta["total_count"] == 2

    active_database, backup_archive = tasks
    assert active_database["target_kind"] == "ACTIVE_DATABASE"
    assert active_database["weight"] == 40
    assert active_database["sla_days"] == 5
    assert_instant_equals(
        active_database["due_at"], "2026-09-06T00:00:00.000Z", "due_at"
    )
    assert active_database["status"] == "PENDING"
    assert active_database["recipient_id"] is None

    assert backup_archive["target_kind"] == "BACKUP_ARCHIVE"
    assert backup_archive["weight"] == 20
    assert backup_archive["sla_days"] == 45
    assert_instant_equals(
        backup_archive["due_at"], "2026-10-16T00:00:00.000Z", "due_at"
    )
    assert backup_archive["status"] == "PENDING"
    assert backup_archive["recipient_id"] is None

    assert not [task for task in tasks if task["target_kind"] == "DERIVED_DATASET"]

    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "PURGE_PENDING"
    assert consumer["consent_status"] == "NOT_REQUIRED"


def test_acknowledging_a_freshly_minted_pending_task_is_refused():
    """PRD §2.6: "The propagation task's current `status` declares the requested
    transition: `PENDING` or `FAILED` for dispatch, `DISPATCHED` for ack and for
    fail, `FAILED` for waive. A `DEFERRED` task is not dispatchable and must
    first return to `PENDING` by its recipient being restored to `ACTIVE` —
    otherwise `ERR_TASK_INVALID_STATE` (409)."
    PRD §3.5: "Every minted task starts in `PENDING` with `dispatched_at`,
    `acknowledged_at`, `failure_code`, `deferral_reason`, and
    `waiver_justification` all null, `ack_was_late` false, and `dispatch_count`
    zero, and carries the `deletion_request_id` of its owning request."
    PRD §3.6: "A `BrokerAdmin`, a `PrivacyReviewer`, or the `StatePlatform`
    acknowledges a `DISPATCHED` task."
    PRD §3.6: "The task moves `DISPATCHED → ACKED`, which is terminal, the owning
    request's `acked_task_count` increases by one and `outstanding_task_count`
    decreases by one, its `completion_ratio` is recomputed, and a
    `PROPAGATION_ACKED` audit event is appended."

    Design: Corner/state_machines/propagation_task_ack_from_pending_rejected
    """
    ctx = setup_executing_deletion_request(
        clock=CLOCK_TEST_INSTANT,
        derived_profile_count=0,
        recipient_count=0,
        request_overrides={"requested_scope": "DELETE_ALL"},
    )
    task = find_task(
        ctx["request_id"], REVIEWER_BETA_HEADERS, target_kind="ACTIVE_DATABASE"
    )
    assert task["status"] == "PENDING"

    response = api_client.ack_propagation_task(task["id"], REVIEWER_BETA_HEADERS)
    validate_error(response, ApiErrorId.ERR_TASK_INVALID_STATE, 409)

    stored = fetch_propagation_task(task["id"], REVIEWER_BETA_HEADERS)
    assert stored["status"] == "PENDING"
    assert stored["acknowledged_at"] is None
    assert stored["dispatch_count"] == 0

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "EXECUTING"
    assert request["acked_task_count"] == 0
    assert request["outstanding_task_count"] == 2
    assert_ratio_equals(request["completion_ratio"], "0.0000")


def test_lifting_an_already_lifted_suppression_entry_is_refused():
    """PRD §2.6: "The suppression entry is `ACTIVE` — otherwise
    `ERR_SUPPRESSION_INVALID_STATE` (409). Applies to
    `POST /suppression-entries/{id}/lift`."
    PRD §3.7: "A `PrivacyReviewer` or a `PlatformAdmin` lifts an `ACTIVE` entry,
    supplying a `lift_justification` of at least 20 and at most 400 characters,
    or `ERR_LIFT_JUSTIFICATION_REQUIRED` answers; an entry that is already
    `LIFTED` or `EXPIRED` answers `ERR_SUPPRESSION_INVALID_STATE`. The entry
    moves `ACTIVE → LIFTED`, the justification is stored, and a
    `SUPPRESSION_LIFTED` audit event is appended."
    PRD §3.7: "Both `LIFTED` and `EXPIRED` are terminal."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/state_machines/suppression_lift_twice_second_attempt_rejected
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    request = open_deletion_request(
        ctx["broker_id"], consumer, intake_channel="EMAIL", requested_scope="DELETE_ALL"
    )
    entry = create_suppression_entry(
        ctx["broker_id"],
        consumer["id"],
        headers=REVIEWER_ALPHA_HEADERS,
        originating_request_id=request["id"],
        source_scope="ALL_SOURCES",
    )
    assert entry["status"] == "ACTIVE"

    first = api_client.lift_suppression_entry(
        entry["id"],
        {"lift_justification": LIFT_JUSTIFICATION_FIRST},
        REVIEWER_ALPHA_HEADERS,
    )
    lifted = validate_success(first, 200)
    assert lifted["status"] == "LIFTED"
    assert lifted["version"] == 2

    second = api_client.lift_suppression_entry(
        entry["id"],
        {"lift_justification": LIFT_JUSTIFICATION_SECOND},
        make_privacy_reviewer_headers("reviewer-gamma"),
    )
    validate_error(second, ApiErrorId.ERR_SUPPRESSION_INVALID_STATE, 409)

    stored = fetch_suppression_entry(entry["id"], ctx["broker_headers"])
    assert stored["status"] == "LIFTED"
    assert stored["version"] == 2
    assert stored["lift_justification"] == LIFT_JUSTIFICATION_FIRST

    assert (
        audit_event_total(ctx["broker_id"], ctx["broker_headers"], "SUPPRESSION_LIFTED")
        == 1
    )


def test_terminated_recipient_refuses_every_further_posture_change():
    """PRD §2.6: "The recipient's requested `status` change is declared from its
    current status: `ACTIVE` and `SUSPENDED` may move to each other in both
    directions, either may move to `TERMINATED`, and nothing leaves `TERMINATED`
    — otherwise `ERR_RECIPIENT_INVALID_STATE` (409). Applies to
    `POST /downstream-recipients/{id}/status`."
    PRD §3.6: "Termination is allowed from `ACTIVE` and from `SUSPENDED`, is
    terminal, and abandons the recipient's remaining work"
    PRD §3.6: "Every posture change appends a `RECIPIENT_STATUS_CHANGED` audit
    event."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/state_machines/recipient_terminated_is_terminal_and_rejects_reactivation
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    recipient = register_recipient(
        ctx["broker_id"],
        ctx["broker_headers"],
        name="Northwind Audience Partners",
        contract_propagation_required=True,
        ack_sla_days=5,
    )
    terminated = set_recipient_status(
        recipient["id"], "TERMINATED", ctx["broker_headers"]
    )
    assert terminated["status"] == "TERMINATED"

    reactivation = api_client.set_recipient_status(
        recipient["id"], {"status": "ACTIVE"}, ctx["broker_headers"]
    )
    validate_error(reactivation, ApiErrorId.ERR_RECIPIENT_INVALID_STATE, 409)

    suspension = api_client.set_recipient_status(
        recipient["id"], {"status": "SUSPENDED"}, make_platform_admin_headers()
    )
    validate_error(suspension, ApiErrorId.ERR_RECIPIENT_INVALID_STATE, 409)

    stored = fetch_recipient(recipient["id"], ctx["broker_headers"])
    assert stored["status"] == "TERMINATED"
    assert stored["version"] == 2

    assert (
        audit_event_total(
            ctx["broker_id"], ctx["broker_headers"], "RECIPIENT_STATUS_CHANGED"
        )
        == 1
    )


def test_consent_actions_undeclared_from_not_required_are_refused():
    """PRD §2.6: "The requested consent `action` is declared from the consumer's
    current `consent_status`: `REQUEST` from `NOT_REQUIRED` or
    `CONSENT_REVOKED`, `GRANT` from `CONSENT_PENDING`, `REVOKE` from
    `CONSENT_GRANTED` — otherwise `ERR_CONSENT_INVALID_TRANSITION` (409).
    Applies to `POST /consumers/{id}/consent`."
    PRD §3.3: "a request is only meaningful when `sensitive_categories` is
    non-empty, and a request against a consumer with no sensitive categories is
    refused with `ERR_CONSENT_INVALID_TRANSITION`."
    PRD §3.3: "Any action not declared from the current `consent_status` is
    refused with `ERR_CONSENT_INVALID_TRANSITION`."
    PRD §3.3: "Every accepted consent act leaves `collection_status` completely
    untouched and appends a `CONSENT_CHANGED` audit event."
    PRD §3.3: "a newly recorded consumer starts `ACTIVE` with
    `collection_event_count` set to 1, counting the creating call itself"
    PRD §3.3: "a consumer created with an empty `sensitive_categories` array
    starts in `NOT_REQUIRED`"

    Design: Corner/state_machines/consent_actions_undeclared_from_not_required_are_rejected
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    assert consumer["consent_status"] == "NOT_REQUIRED"

    grant = api_client.record_consent_action(
        consumer["id"], {"action": "GRANT"}, make_consumer_headers(consumer["id"])
    )
    validate_error(grant, ApiErrorId.ERR_CONSENT_INVALID_TRANSITION, 409)

    request = api_client.record_consent_action(
        consumer["id"], {"action": "REQUEST"}, ctx["broker_headers"]
    )
    validate_error(request, ApiErrorId.ERR_CONSENT_INVALID_TRANSITION, 409)

    stored = fetch_consumer(consumer["id"], ctx["broker_headers"])
    assert stored["consent_status"] == "NOT_REQUIRED"
    assert stored["collection_status"] == "ACTIVE"
    assert stored["version"] == 1

    assert (
        audit_event_total(ctx["broker_id"], ctx["broker_headers"], "CONSENT_CHANGED")
        == 0
    )


def test_closing_an_open_inquiry_is_refused_on_the_state_check():
    """PRD §2.6: "The regulator inquiry's current `status` declares the requested
    transition: `OPEN` or `ESCALATED` for respond, `RESPONDED` for close,
    `RESPONDED` for escalate — otherwise `ERR_INQUIRY_INVALID_STATE` (409).
    Applies to `POST /regulator-inquiries/{id}/respond`, `/close`, and
    `/escalate`."
    PRD §3.8: "A `Regulator` closes a `RESPONDED` inquiry, and only when its
    `adequacy_verdict` is `ADEQUATE`, or `ERR_RESPONSE_INADEQUATE` answers; an
    inquiry in any other status answers `ERR_INQUIRY_INVALID_STATE`."
    PRD §3.8: "The inquiry is created in `OPEN` with `adequacy_verdict`
    `UNRATED`, `cited_audit_event_ids` an empty array, `cited_event_count` at 0,
    `coverage_bonus_applied` false, `evidence_score`, `deficiency_penalty`,
    `late_response_penalty`, and `adequacy_score` all at 0.00,
    `escalation_count` at 0, and `responded_at`, `deficiency_code` null."

    Design: Corner/state_machines/inquiry_close_attempted_from_open_rejected
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    regulator_headers = make_regulator_headers("regulator-ca")
    inquiry = open_inquiry(
        ctx["broker_id"],
        response_due_at="2026-10-01T00:00:00Z",
        headers=regulator_headers,
        scope_note=(
            "Produce evidence of your deletion request handling for the current "
            "registration period."
        ),
    )
    assert inquiry["status"] == "OPEN"

    response = api_client.close_inquiry(inquiry["id"], regulator_headers)
    validate_error(response, ApiErrorId.ERR_INQUIRY_INVALID_STATE, 409)

    stored = fetch_inquiry(inquiry["id"], regulator_headers)
    assert stored["status"] == "OPEN"
    assert stored["adequacy_verdict"] == "UNRATED"
    assert stored["responded_at"] is None


def test_denial_from_received_moves_the_broker_request_counters():
    """PRD §3.4: "A `PrivacyReviewer` may deny a request from `RECEIVED`,
    `VERIFICATION_PENDING`, or `VERIFICATION_FAILED`, supplying a
    `denial_reason_code` of `IDENTITY_UNVERIFIED`, `EXEMPT_RECORD`, or
    `DUPLICATE_REQUEST`. The code is stored, the broker's `request_open_count`
    decreases by one while `request_terminated_count` increases by one, and a
    `DELETION_DENIED` audit event is appended."
    PRD §3.4: "`DENIED`, `WITHDRAWN`, and `SUPERSEDED` are all terminal, as are
    `COMPLETED` and `PARTIALLY_COMPLETED`."
    PRD §3.4: "The broker's `request_intake_total` and `request_open_count` each
    increase by one."

    Design: Corner/state_machines/deny_from_received_moves_the_broker_request_counters
    """
    ctx = onboard_broker(
        operating_state_codes=("CA",), deposit_cents=0, clock=CLOCK_TEST_INSTANT
    )
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    request = open_deletion_request(
        ctx["broker_id"], consumer, intake_channel="EMAIL", requested_scope="DELETE_ALL"
    )
    assert request["status"] == "RECEIVED"

    response = api_client.deny_deletion_request(
        request["id"], {"denial_reason_code": "EXEMPT_RECORD"}, REVIEWER_ALPHA_HEADERS
    )
    denied = validate_success(response, 200)
    assert denied["status"] == "DENIED"
    assert denied["denial_reason_code"] == "EXEMPT_RECORD"

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["request_intake_total"] == 1
    assert broker["request_open_count"] == 0
    assert broker["request_terminated_count"] == 1
    assert broker["request_completed_count"] == 0

    assert (
        audit_event_total(ctx["broker_id"], ctx["broker_headers"], "DELETION_DENIED")
        == 1
    )
