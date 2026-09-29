"""Broker, consumer and request record basics at intake.

Enrolment defaults, read-back projections, list pagination, per-family
not-found codes, payload validation, server-generated system fields, the
append-only audit trail and single-broker integrity at deletion intake.
"""

import pytest

from test_helpers import (
    AUDIT_RETENTION_DAYS,
    CLOCK_TEST_INSTANT,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_append_only_entity,
    assert_audit_event,
    assert_broker,
    assert_cents_equals,
    assert_consumer,
    assert_deletion_request,
    assert_instant_equals,
    assert_score_equals,
    assert_suppression_entry,
    create_broker_payload,
    create_consumer_payload,
    create_deletion_request_payload,
    create_registration_payload,
    days_after,
    fetch_broker,
    onboard_broker,
    open_deletion_request,
    record_consumer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import REVIEWER_ALPHA_HEADERS, make_broker_admin_headers

PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
INTAKE_AGENT_HEADERS = TEST_USERS["intake_agent_headers"]
REGULATOR_HEADERS = TEST_USERS["regulator_headers"]


def test_broker_enrolment_starts_delinquent_with_a_zeroed_ledger():
    """PRD §3.1: "A newly enrolled broker is **not** compliant."
    PRD §3.1: "Because it holds no accepted filing anywhere yet, its
    `registry_standing` is initialised to `DELINQUENT` and its
    `delinquent_since` is set to the enrolment instant, which is also its
    `created_at`."
    PRD §3.1: "Every counter on the broker starts at zero:
    `fee_deposited_cents`, `fee_paid_cents`, `fee_credit_cents`,
    `open_breach_count`, `request_intake_total`, `request_open_count`,
    `request_completed_count`, `request_terminated_count`, and
    `audit_sequence_high_water`."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"
    PRD §4: "Every creation endpoint answers 201 with the created resource in
    `data`"

    Design: Corner/entities/broker_creation_initialises_ledger_counters_and_delinquent_standing
    """
    set_clock(CLOCK_TEST_INSTANT)

    response = api_client.create_broker(
        create_broker_payload(
            home_state_code="CA", operating_state_codes=["CA", "TX"]
        ),
        PLATFORM_ADMIN_HEADERS,
    )

    broker = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert_broker(broker)
    assert broker["version"] == 1
    assert broker["registry_standing"] == "DELINQUENT"
    assert_instant_equals(
        broker["delinquent_since"], CLOCK_TEST_INSTANT, "delinquent_since"
    )
    assert_instant_equals(broker["created_at"], CLOCK_TEST_INSTANT, "created_at")
    assert_cents_equals(broker["fee_deposited_cents"], 0, "fee_deposited_cents")
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 0, "fee_credit_cents")
    assert broker["open_breach_count"] == 0
    assert broker["request_intake_total"] == 0
    assert broker["request_open_count"] == 0
    assert broker["request_completed_count"] == 0
    assert broker["request_terminated_count"] == 0
    assert broker["operating_state_codes"] == ["CA", "TX"]


def test_broker_read_returns_the_stored_projection_without_advancing_version():
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"
    PRD §3.1: "It is derived, and it is re-derived at every point where its
    inputs could have moved: after every registration status change, after
    every `compliance_breach` flip on a deletion request, after every fee
    settlement, and once per broker during the deferred-action sweep."

    Design: Corner/entities/broker_retrieval_returns_the_stored_projection_unchanged
    """
    ctx = onboard_broker(
        operating_state_codes=("CA", "TX"),
        deposit_cents=0,
        clock=CLOCK_TEST_INSTANT,
        home_state_code="CA",
    )
    created = ctx["broker"]

    response = api_client.get_broker(ctx["broker_id"], REGULATOR_HEADERS)

    read_back = validate_success(response, 200)
    assert_broker(read_back)
    assert read_back["id"] == created["id"]
    assert read_back["legal_name"] == created["legal_name"]
    assert read_back["home_state_code"] == "CA"
    assert read_back["operating_state_codes"] == ["CA", "TX"]
    assert read_back["version"] == 1
    assert read_back["registry_standing"] == "DELINQUENT"
    assert_instant_equals(
        read_back["updated_at"], created["updated_at"], "updated_at"
    )


def test_consumer_list_pages_report_total_count_and_has_more():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    counts every record matching the applied filters before the page window is
    applied, and `has_more` states whether any record remains beyond the
    current window."
    PRD §2.3: "Unless a specific endpoint says otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/entities/consumer_listing_paginates_with_total_count_and_has_more
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    recorded_ids = [
        record_consumer(ctx["broker_id"], state_code="CA")["id"] for _ in range(3)
    ]

    first_page, first_meta = validate_paginated(
        api_client.list_consumers(
            PLATFORM_ADMIN_HEADERS,
            params={"broker_id": ctx["broker_id"], "limit": 2, "offset": 0},
        )
    )
    second_page, second_meta = validate_paginated(
        api_client.list_consumers(
            PLATFORM_ADMIN_HEADERS,
            params={"broker_id": ctx["broker_id"], "limit": 2, "offset": 2},
        )
    )

    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == set(recorded_ids)


UNKNOWN_ID_CASES = [
    ("get_broker", ApiErrorId.ERR_BROKER_NOT_FOUND),
    ("get_registration", ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
    ("get_consumer", ApiErrorId.ERR_CONSUMER_NOT_FOUND),
    ("get_deletion_request", ApiErrorId.ERR_DELETION_REQUEST_NOT_FOUND),
    ("get_propagation_task", ApiErrorId.ERR_PROPAGATION_TASK_NOT_FOUND),
    ("get_downstream_recipient", ApiErrorId.ERR_RECIPIENT_NOT_FOUND),
    ("get_suppression_entry", ApiErrorId.ERR_SUPPRESSION_ENTRY_NOT_FOUND),
    ("get_regulator_inquiry", ApiErrorId.ERR_INQUIRY_NOT_FOUND),
]


@pytest.mark.parametrize(
    "reader, expected_error",
    UNKNOWN_ID_CASES,
    ids=[case[1].value for case in UNKNOWN_ID_CASES],
)
def test_unknown_id_answers_the_entity_specific_not_found_error(reader, expected_error):
    """PRD §2.6: "The addressed or referenced `DataBroker` exists — otherwise
    `ERR_BROKER_NOT_FOUND` (404). Applies to `GET /brokers/{id}`, `POST
    /brokers/{id}/fee-deposits`, `GET /brokers/{id}/audit-events`, and every
    endpoint carrying `broker_id` in its payload."
    PRD §2.6: "The addressed `Registration` exists — otherwise
    `ERR_REGISTRATION_NOT_FOUND` (404). Applies to every
    `/registrations/{id}...` endpoint."
    PRD §2.6: "The addressed or referenced `Consumer` exists — otherwise
    `ERR_CONSUMER_NOT_FOUND` (404). Applies to every `/consumers/{id}...`
    endpoint and to every payload carrying `consumer_id`."
    PRD §2.6: "The addressed or referenced `DeletionRequest` exists — otherwise
    `ERR_DELETION_REQUEST_NOT_FOUND` (404). Applies to every
    `/deletion-requests/{id}...` endpoint and to every payload carrying
    `originating_request_id`."
    PRD §2.6: "The addressed `PropagationTask` exists — otherwise
    `ERR_PROPAGATION_TASK_NOT_FOUND` (404). Applies to every
    `/propagation-tasks/{id}...` endpoint."
    PRD §2.6: "The addressed or referenced `DownstreamRecipient` exists —
    otherwise `ERR_RECIPIENT_NOT_FOUND` (404). Applies to every
    `/downstream-recipients/{id}...` endpoint."
    PRD §2.6: "The addressed `SuppressionEntry` exists — otherwise
    `ERR_SUPPRESSION_ENTRY_NOT_FOUND` (404). Applies to every
    `/suppression-entries/{id}...` endpoint."
    PRD §2.6: "The addressed `RegulatorInquiry` exists — otherwise
    `ERR_INQUIRY_NOT_FOUND` (404). Applies to every
    `/regulator-inquiries/{id}...` endpoint."

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
    """
    set_clock(CLOCK_TEST_INSTANT)

    response = getattr(api_client, reader)(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS)

    validate_error(response, expected_error.value, 404)
    assert response.json()["response_type"] == "error"


def test_registration_create_without_state_code_rejected():
    """PRD §2.6: "Every required input field is present, every enum value is a
    declared member, every `*_cents` amount is a non-negative integer, every
    score falls inside its declared range, and every timestamp parses as ISO
    8601 UTC — otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."
    PRD §3.2: "The payload names the `broker_id` the filing belongs to, the
    `state_code` of the registry being filed in (exactly two uppercase letters,
    and it must appear in that broker's `operating_state_codes`), the half-open
    coverage interval the filing covers as `coverage_period_start` and
    `coverage_period_end`, the `business_description` as filed with this
    particular state, and the `expected_broker_version` token of §2.5."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/entities/registration_create_without_state_code_rejected_as_invalid_request
    """
    ctx = onboard_broker(deposit_cents=500000, clock=CLOCK_TEST_INSTANT)
    funded_version = ctx["broker"]["version"]
    assert funded_version == 2

    payload = create_registration_payload(
        ctx["broker_id"],
        funded_version,
        coverage_period_start="2026-09-01T00:00:00Z",
        coverage_period_end="2027-03-01T00:00:00Z",
        business_description=(
            "California registry filing with the state code deliberately omitted."
        ),
    )
    payload.pop("state_code")

    response = api_client.create_registration(payload, ctx["broker_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    filings, filings_meta = validate_paginated(
        api_client.list_registrations(
            ctx["broker_headers"], params={"broker_id": ctx["broker_id"]}
        )
    )
    assert filings_meta["total_count"] == 0
    assert filings == []
    assert fetch_broker(ctx["broker_id"], ctx["broker_headers"])["version"] == 2


def test_broker_create_with_a_spelled_out_state_code_rejected():
    """PRD §2.6: "Every required input field is present, every enum value is a
    declared member, every `*_cents` amount is a non-negative integer, every
    score falls inside its declared range, and every timestamp parses as ISO
    8601 UTC — otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."
    PRD §3.1: "a `home_state_code` of exactly two uppercase letters naming the
    state of incorporation"
    PRD §3.1: "`operating_state_codes` must be a non-empty array of distinct
    two-uppercase-letter codes with at most 12 entries."

    Design: Corner/entities/broker_create_with_a_non_two_letter_state_code_rejected
    """
    set_clock(CLOCK_TEST_INSTANT)

    response = api_client.create_broker(
        create_broker_payload(
            home_state_code="California", operating_state_codes=["California"]
        ),
        PLATFORM_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_deletion_request_omitting_requested_scope_stores_delete_all():
    """PRD §3.4: "Two fields are optional: `requested_scope`, which is either
    `DELETE_ALL` or `DELETE_SENSITIVE_ONLY` and defaults to `DELETE_ALL`; and
    `agent_loa_reference`, a letter-of-authority reference of 1 to 80
    characters that is required whenever `intake_channel` is
    `AUTHORIZED_AGENT` and null otherwise."
    PRD §3.4: "An accepted request is created in `RECEIVED` with
    `intake_user_id` set to the acting `X-User-ID`, `identity_assurance_score`
    at 0.00, `verification_attempt_count` and `failed_attempt_count` at 0,
    every propagation counter (`propagation_required_count`,
    `downstream_task_count`, `acked_task_count`, `waived_task_count`,
    `abandoned_task_count`, `outstanding_task_count`) at 0, `completion_ratio`
    at 0.0000, `compliance_breach` false, and
    `verification_decided_by_user_id`, `executed_by_user_id`, `executed_at`,
    and `denial_reason_code` all null."
    PRD §3.4: "The broker's `request_intake_total` and `request_open_count`
    each increase by one."

    Design: Corner/entities/deletion_request_requested_scope_defaults_to_delete_all
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    consumer = record_consumer(ctx["broker_id"], state_code="CA")

    payload = create_deletion_request_payload(
        ctx["broker_id"],
        consumer["id"],
        consumer["version"],
        intake_channel="EMAIL",
    )
    assert "requested_scope" not in payload

    response = api_client.create_deletion_request(payload, INTAKE_AGENT_HEADERS)

    request = validate_success(response, 201)
    assert_deletion_request(request)
    assert request["requested_scope"] == "DELETE_ALL"
    assert request["status"] == "RECEIVED"
    assert request["verification_attempt_count"] == 0
    assert request["failed_attempt_count"] == 0
    assert_score_equals(
        request["identity_assurance_score"], "0.00", "identity_assurance_score"
    )

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["request_intake_total"] == 1
    assert broker["request_open_count"] == 1


def test_suppression_entry_defaults_window_to_the_clock_and_730_days():
    """PRD §3.7: "Two fields are optional and defaulted from the clock:
    `window_start` defaults to the current clock instant, and `window_end`
    defaults to `window_start` advanced by 730 whole days, which is the
    office's two-year re-collection bar."
    PRD §3.7: "The entry is created `ACTIVE` with `blocked_recollection_count`
    at zero and `lift_justification` null, and a `SUPPRESSION_CREATED` audit
    event is appended."
    PRD §2.7: "Adding n days to an instant advances it by exactly n times
    twenty-four hours and preserves the time-of-day component of the base
    instant; the result is stored as ISO 8601 UTC with three fractional
    digits."

    Design: Corner/entities/suppression_entry_window_defaults_to_the_clock_and_seven_hundred_thirty_days
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    consumer = record_consumer(ctx["broker_id"], state_code="CA")
    request = open_deletion_request(
        ctx["broker_id"],
        consumer,
        intake_channel="EMAIL",
        requested_scope="DELETE_ALL",
    )

    response = api_client.create_suppression_entry(
        {
            "broker_id": ctx["broker_id"],
            "consumer_id": consumer["id"],
            "originating_request_id": request["id"],
            "source_scope": "ALL_SOURCES",
        },
        REVIEWER_ALPHA_HEADERS,
    )

    entry = validate_success(response, 201)
    assert_suppression_entry(entry)
    assert_instant_equals(
        entry["window_start"], "2026-09-01T00:00:00Z", "window_start"
    )
    assert_instant_equals(entry["window_end"], "2028-08-31T00:00:00Z", "window_end")
    assert entry["status"] == "ACTIVE"
    assert entry["blocked_recollection_count"] == 0
    assert entry["lift_justification"] is None


def test_consumer_creation_stamps_the_server_generated_system_fields():
    """PRD §3.3: "a newly recorded consumer starts `ACTIVE` with
    `collection_event_count` set to 1, counting the creating call itself"
    PRD §3.3: "a consumer created with an empty `sensitive_categories` array
    starts in `NOT_REQUIRED`, while a consumer created with a non-empty one is
    initialised directly in `CONSENT_PENDING`"
    PRD §3.3: "Creation also sets `opt_out_sale` and `opt_out_sharing` to false
    and `last_purged_at` to null, and appends a `CONSUMER_RECORDED` audit
    event."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/entities/consumer_system_fields_are_server_generated_and_client_values_ignored
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)

    response = api_client.create_consumer(
        create_consumer_payload(
            ctx["broker_id"], state_code="CA", derived_profile_count=0
        ),
        INTAKE_AGENT_HEADERS,
    )

    consumer = validate_success(response, 201)
    assert_consumer(consumer)
    assert consumer["version"] == 1
    assert consumer["collection_status"] == "ACTIVE"
    assert consumer["consent_status"] == "NOT_REQUIRED"
    assert consumer["collection_event_count"] == 1
    assert consumer["opt_out_sale"] is False
    assert consumer["opt_out_sharing"] is False
    assert consumer["last_purged_at"] is None


def test_broker_registered_audit_event_is_append_only_at_sequence_one():
    """PRD §2.4: "Three record families are append-only evidence rather than
    mutable state, and they carry only `id` and `created_at`: a data-practice
    disclosure item, a verification attempt, and an audit event. For those
    three, both `updated_at` and `version` are absent from the resource
    entirely."
    PRD §2.10: "the trail is append-only: no event is ever edited or deleted,
    which is why audit events carry no `updated_at` and no `version`"
    PRD §2.10: "Each event records the `broker_id` whose compliance record it
    belongs to, a `sequence_no` that is a per-broker monotonic counter starting
    at 1, an `event_type`, a `subject_kind` naming the entity family the event
    is about, a `subject_id` identifying the specific instance,"
    PRD §2.10: "`retention_expires_at` is the event's `created_at` plus 2555
    days — a seven-year retention floor."
    PRD §3.1: "The enrolment appends a `BROKER_REGISTERED` audit event, which
    is therefore always sequence number 1 on that broker's trail."
    PRD §2.10: "A broker's trail is readable in ascending `sequence_no` order
    and may be narrowed by `event_type`, by `subject_kind`, or by `subject_id`."

    Design: Corner/entities/audit_events_are_append_only_and_carry_no_version_field
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)

    events, meta = validate_paginated(
        api_client.list_audit_events(
            ctx["broker_id"],
            REGULATOR_HEADERS,
            params={"event_type": "BROKER_REGISTERED"},
        )
    )

    assert meta["total_count"] == 1
    event = events[0]
    assert_audit_event(event)
    assert_append_only_entity(event, "audit_event")
    assert "version" not in event
    assert "updated_at" not in event
    assert event["event_type"] == "BROKER_REGISTERED"
    assert event["sequence_no"] == 1
    assert event["subject_kind"] == "BROKER"
    assert event["subject_id"] == ctx["broker_id"]
    assert event["broker_id"] == ctx["broker_id"]
    assert_instant_equals(
        event["retention_expires_at"],
        days_after(event["created_at"], AUDIT_RETENTION_DAYS),
        "retention_expires_at",
    )


def test_deletion_request_referencing_another_brokers_consumer_rejected():
    """PRD §2.6: "Every entity referenced in one request belongs to the same
    broker: a deletion request's `consumer_id` must resolve to a consumer whose
    `broker_id` equals the supplied `broker_id`; a suppression entry's
    `consumer_id` and `originating_request_id` must share the same broker; an
    opt-out signal's `consumer_id` must belong to the supplied `broker_id` —
    otherwise `ERR_CROSS_BROKER_REFERENCE` (422). Applies to `POST
    /deletion-requests`, `POST /suppression-entries`, `POST /opt-out-signals`,
    and `POST /consumers/{id}/collections`."
    PRD §2.9: "A request that mixes brokers is rejected with
    `ERR_CROSS_BROKER_REFERENCE`, which is a tenancy violation rather than a
    missing-record problem and therefore answers 422 rather than 404."
    PRD §3.4: "The broker's `request_intake_total` and `request_open_count`
    each increase by one."

    Design: Corner/entities/deletion_request_referencing_another_brokers_consumer_rejected
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
    beta_consumer = record_consumer(beta["broker_id"], state_code="CA")

    response = api_client.create_deletion_request(
        create_deletion_request_payload(
            alpha["broker_id"],
            beta_consumer["id"],
            beta_consumer["version"],
            intake_channel="EMAIL",
            requested_scope="DELETE_ALL",
        ),
        INTAKE_AGENT_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_CROSS_BROKER_REFERENCE.value, 422)

    _, by_broker_meta = validate_paginated(
        api_client.list_deletion_requests(
            PLATFORM_ADMIN_HEADERS, params={"broker_id": alpha["broker_id"]}
        )
    )
    assert by_broker_meta["total_count"] == 0

    _, by_consumer_meta = validate_paginated(
        api_client.list_deletion_requests(
            PLATFORM_ADMIN_HEADERS, params={"consumer_id": beta_consumer["id"]}
        )
    )
    assert by_consumer_meta["total_count"] == 0

    alpha_broker = fetch_broker(
        alpha["broker_id"], make_broker_admin_headers(alpha["broker_id"])
    )
    assert alpha_broker["request_intake_total"] == 0
    assert alpha_broker["request_open_count"] == 0
