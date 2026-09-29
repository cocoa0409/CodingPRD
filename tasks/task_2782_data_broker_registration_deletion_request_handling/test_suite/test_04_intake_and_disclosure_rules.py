"""Intake, disclosure and adjudication validation rules.

Every test builds its own broker, filing, consumer and request from scratch: the
harness restarts the API and wipes the database before each individual test.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_ALPHA_HEADERS,
    TEST_USERS,
    ApiErrorId,
    add_disclosures,
    api_client,
    assert_cents_equals,
    assert_score_equals,
    create_suppression_entry,
    fetch_broker,
    fetch_consumer,
    fetch_deletion_request,
    fetch_registration,
    fetch_suppression_entry,
    onboard_broker,
    open_deletion_request,
    open_draft_registration,
    record_consumer,
    record_verification_attempt,
    setup_consumer_of_broker,
    setup_received_deletion_request,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE_AGENT_HEADERS = TEST_USERS["intake_agent_headers"]


def _audit_event_count(broker_id, headers, event_type):
    """total_count of one broker's audit events narrowed to a single type."""
    _, meta = validate_paginated(
        api_client.list_audit_events(
            broker_id, headers, params={"event_type": event_type}
        )
    )
    return meta["total_count"]


def _list_total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def test_second_disclosure_in_the_same_category_is_refused():
    """PRD §3.2: "At most one disclosure may exist per category per filing; a
    second attempt in the same category is refused with
    `ERR_DUPLICATE_DISCLOSURE_CATEGORY`."
    PRD §3.2: "From `DRAFT` the filing stays in `DRAFT` — the transition is
    `DRAFT → DRAFT` — and only the new item plus the recomputed completeness
    score change."
    PRD §3.2: "The six category weights are 20.00 for `SOURCES`, 25.00 for
    `RECIPIENTS`, 15.00 for `RETENTION`, 20.00 for `OPT_OUT_MECHANISM`, 12.00 for
    `SENSITIVE_CATEGORIES`, and 8.00 for `MINORS_DATA`."
    PRD §3.2: "The filing's `disclosure_completeness_score` is the sum of every
    item's `weight_credit`, rounded half up to two decimal places."

    Design: Corner/validations/duplicate_disclosure_category_on_the_same_registration_rejected
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)
    registration = open_draft_registration(ctx["broker_id"], ctx["broker_headers"])
    add_disclosures(registration["id"], ctx["broker_headers"], categories=["SOURCES"])

    response = api_client.create_disclosure(
        registration["id"],
        {
            "category": "SOURCES",
            "content": (
                "Second attempt at the same category with completely different "
                "wording of the source list."
            ),
            "covers_sensitive_categories": False,
        },
        ctx["broker_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DISCLOSURE_CATEGORY, 409)

    refreshed = fetch_registration(registration["id"], ctx["broker_headers"])
    assert_score_equals(
        refreshed["disclosure_completeness_score"],
        20.00,
        "disclosure_completeness_score",
    )
    assert refreshed["status"] == "DRAFT"
    assert (
        _list_total_count(
            api_client.list_disclosures(
                registration["id"],
                ctx["broker_headers"],
                params={"category": "SOURCES"},
            )
        )
        == 1
    )


def test_identity_hash_collides_inside_the_broker_but_not_across_brokers():
    """PRD §3.3: "The `identity_hash` must be unique within the broker across
    consumers whose `collection_status` is not `PURGED`, so a hash freed by a
    purge may be re-used while a live one may not; a collision answers
    `ERR_IDENTITY_HASH_DUPLICATE`."

    Design: Corner/validations/identity_hash_uniqueness_is_scoped_to_the_broker
    """
    alpha = onboard_broker(
        clock=CLOCK_TEST_INSTANT,
        deposit_cents=0,
        legal_name="Alpha Attribute Works",
        primary_contact_email="office@alpha.example",
    )
    beta = onboard_broker(
        deposit_cents=0,
        legal_name="Beta Household Index",
        primary_contact_email="office@beta.example",
    )
    shared_hash = "sha256:dup00001dup00001"
    alpha_consumer = record_consumer(
        alpha["broker_id"],
        identity_hash=shared_hash,
        source_label="AGENCY_FEED_A",
        derived_profile_count=0,
    )

    duplicate = api_client.create_consumer(
        {
            "broker_id": alpha["broker_id"],
            "identity_hash": shared_hash,
            "state_code": "CA",
            "source_label": "AGENCY_FEED_B",
            "derived_profile_count": 0,
        },
        INTAKE_AGENT_HEADERS,
    )
    validate_error(duplicate, ApiErrorId.ERR_IDENTITY_HASH_DUPLICATE, 409)

    accepted = api_client.create_consumer(
        {
            "broker_id": beta["broker_id"],
            "identity_hash": shared_hash,
            "state_code": "CA",
            "source_label": "BETA_FEED",
            "derived_profile_count": 0,
        },
        INTAKE_AGENT_HEADERS,
    )
    beta_consumer = validate_success(accepted, 201)
    assert beta_consumer["broker_id"] == beta["broker_id"]

    for broker_id in (alpha["broker_id"], beta["broker_id"]):
        assert (
            _list_total_count(
                api_client.list_consumers(
                    INTAKE_AGENT_HEADERS, params={"broker_id": broker_id}
                )
            )
            == 1
        )
    assert (
        fetch_consumer(alpha_consumer["id"], INTAKE_AGENT_HEADERS)["source_label"]
        == "AGENCY_FEED_A"
    )


def test_all_sources_suppression_blocks_recollection_and_records_the_attempt():
    """PRD §3.3: "No `ACTIVE` suppression entry for this broker-and-consumer pair
    may cover the current clock instant with a `source_scope` that covers the
    submitted `source_label`, or the collection is refused with
    `ERR_SUPPRESSION_ACTIVE`."
    PRD §3.7: "An `ALL_SOURCES` entry blocks every collection attempt for that
    consumer whatever the submitted `source_label`."
    PRD §3.7: "When an attempt is blocked, the entry's
    `blocked_recollection_count` increases by one and a `RECOLLECTION_BLOCKED`
    audit event is appended **even though the call itself is refused** with
    `ERR_SUPPRESSION_ACTIVE`; the registry requires the attempt itself to be on
    the record, so a rejected call is one of the few places where a 4xx response
    still leaves durable state behind."
    PRD §3.3: "On success, `collection_event_count` increases by one,
    `source_label` is replaced by the submitted value, and a
    `CONSUMER_COLLECTION_RECORDED` audit event is appended."

    Design: Corner/validations/active_all_sources_suppression_blocks_recollection
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)
    consumer = record_consumer(
        ctx["broker_id"],
        identity_hash="sha256:sup00001sup00001",
        source_label="OWNERSHIP_FEED_D",
        derived_profile_count=0,
    )
    request = open_deletion_request(
        ctx["broker_id"],
        consumer,
        intake_channel="EMAIL",
        requested_scope="DELETE_ALL",
    )
    entry = create_suppression_entry(
        ctx["broker_id"],
        consumer["id"],
        originating_request_id=request["id"],
        source_scope="ALL_SOURCES",
    )

    response = api_client.record_collection(
        consumer["id"],
        {"source_label": "OWNERSHIP_FEED_E", "derived_profile_count": 2},
        INTAKE_AGENT_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SUPPRESSION_ACTIVE, 409)

    refreshed_entry = fetch_suppression_entry(entry["id"], REVIEWER_ALPHA_HEADERS)
    assert refreshed_entry["blocked_recollection_count"] == 1
    assert refreshed_entry["status"] == "ACTIVE"

    refreshed_consumer = fetch_consumer(consumer["id"], ctx["broker_headers"])
    assert refreshed_consumer["collection_event_count"] == 1
    assert refreshed_consumer["source_label"] == "OWNERSHIP_FEED_D"
    assert refreshed_consumer["derived_profile_count"] == 0

    assert (
        _audit_event_count(
            ctx["broker_id"], ctx["broker_headers"], "RECOLLECTION_BLOCKED"
        )
        == 1
    )


def test_sensitive_consumer_collection_requires_granted_consent():
    """PRD §3.3: "The consumer's `sensitive_categories` must be empty, or else
    `consent_status` must be `CONSENT_GRANTED`, or the collection is refused with
    `ERR_SENSITIVE_CONSENT_REQUIRED`."
    PRD §3.3: "a consumer created with an empty `sensitive_categories` array
    starts in `NOT_REQUIRED`, while a consumer created with a non-empty one is
    initialised directly in `CONSENT_PENDING`."
    PRD §3.3: "The consumer themselves grants consent, moving `CONSENT_PENDING →
    CONSENT_GRANTED`, and revokes it, moving `CONSENT_GRANTED →
    CONSENT_REVOKED`; both acts require that the acting `X-User-ID` equal the
    addressed consumer's own `id` when the caller's role is `Consumer`, or the
    act is refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.3: "On success, `collection_event_count` increases by one,
    `source_label` is replaced by the submitted value, and a
    `CONSUMER_COLLECTION_RECORDED` audit event is appended."

    Design: Corner/validations/sensitive_consumer_collection_requires_granted_consent
    """
    ctx = setup_consumer_of_broker(
        sensitive_categories=("PRECISE_GEOLOCATION", "HEALTH")
    )
    assert ctx["consumer"]["consent_status"] == "CONSENT_PENDING"

    blocked = api_client.record_collection(
        ctx["consumer_id"], {"source_label": "OWNERSHIP_FEED_E"}, INTAKE_AGENT_HEADERS
    )
    validate_error(blocked, ApiErrorId.ERR_SENSITIVE_CONSENT_REQUIRED, 422)
    assert (
        fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])[
            "collection_event_count"
        ]
        == 1
    )

    granted = validate_success(
        api_client.record_consent_action(
            ctx["consumer_id"], {"action": "GRANT"}, ctx["consumer_headers"]
        ),
        200,
    )
    assert granted["consent_status"] == "CONSENT_GRANTED"

    accepted = validate_success(
        api_client.record_collection(
            ctx["consumer_id"],
            {"source_label": "OWNERSHIP_FEED_E"},
            INTAKE_AGENT_HEADERS,
        ),
        200,
    )
    assert accepted["collection_event_count"] == 2
    assert accepted["source_label"] == "OWNERSHIP_FEED_E"
    assert accepted["collection_status"] == "ACTIVE"


def test_verified_decision_below_the_assurance_threshold_is_refused():
    """PRD §3.4: "A decision of `VERIFIED` requires the request's
    `identity_assurance_score` to be at least 70.00, or it is refused with
    `ERR_ASSURANCE_BELOW_THRESHOLD`; a decision of `FAILED` has no score
    precondition at all."
    PRD §3.4: "The credited evidence points are the smaller of the supplied
    `evidence_points_count` and 4 — only the first four corroborating points are
    ever credited, so a consumer who supplies ten is not rewarded for nine and is
    not penalised either."
    PRD §3.4: "The `raw_score` is the method's base value plus 7.50 for each
    credited evidence point plus 0.20 times the `document_quality_score`."
    PRD §3.4: "The method base values are 55.00 for `GOVT_ID`, 30.00 for
    `TWO_DATA_POINTS`, 25.00 for `PLATFORM_ASSERTION`, and 35.00 for `AGENT_LOA`."
    PRD §3.4: "The request's `identity_assurance_score` is then set to the maximum
    `assurance_score` across every attempt on the request, with no status filter,
    so it never regresses when a later attempt scores worse than an earlier one."
    PRD §3.4: "From `RECEIVED` the request moves `RECEIVED →
    VERIFICATION_PENDING`."
    PRD §3.4: "An accepted request is created in `RECEIVED` with `intake_user_id`
    set to the acting `X-User-ID`, `identity_assurance_score` at 0.00,
    `verification_attempt_count` and `failed_attempt_count` at 0, every
    propagation counter (`propagation_required_count`, `downstream_task_count`,
    `acked_task_count`, `waived_task_count`, `abandoned_task_count`,
    `outstanding_task_count`) at 0, `completion_ratio` at 0.0000,
    `compliance_breach` false, and `verification_decided_by_user_id`,
    `executed_by_user_id`, `executed_at`, and `denial_reason_code` all null."
    PRD §3.4: "Either decision records `verification_decided_by_user_id` as the
    acting `X-User-ID` and appends a `VERIFICATION_DECIDED` audit event."

    Design: Corner/validations/decide_verification_below_the_assurance_threshold_rejected
    """
    ctx = setup_received_deletion_request(intake_channel="DIRECT_PORTAL")
    record_verification_attempt(
        ctx["request_id"],
        method="TWO_DATA_POINTS",
        evidence_points_count=1,
        document_quality_score=40,
    )

    response = api_client.decide_verification(
        ctx["request_id"], {"decision": "VERIFIED"}, REVIEWER_ALPHA_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ASSURANCE_BELOW_THRESHOLD, 422)

    refreshed = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert refreshed["status"] == "VERIFICATION_PENDING"
    assert_score_equals(
        refreshed["identity_assurance_score"], 45.50, "identity_assurance_score"
    )
    assert refreshed["verification_decided_by_user_id"] is None
    assert (
        _audit_event_count(
            ctx["broker_id"], ctx["broker_headers"], "VERIFICATION_DECIDED"
        )
        == 0
    )


def test_missing_required_disclosure_outranks_completeness_and_fee_shortfalls():
    """PRD §2.6: "The compliance office resolves that deterministically: every
    rule below carries a priority, all applicable rules are considered, and the
    **lowest-numbered violated rule alone** determines the `error_id` and HTTP
    status returned."
    PRD §2.6: "Nothing later in the list can mask something earlier in it, and a
    request that reaches the end of the list without a violation is executed."
    PRD §3.2: "Five business conditions guard that transition, and they are
    evaluated in the priority order of §2.6."
    PRD §3.2: "Every mandatory category — `SOURCES`, `RECIPIENTS`, `RETENTION`,
    and `OPT_OUT_MECHANISM` — must already have a disclosure item on this filing,
    and additionally, if any consumer of this broker carries a non-empty
    `sensitive_categories` array, a disclosure item in the
    `SENSITIVE_CATEGORIES` category must exist as well; either gap is refused
    with `ERR_REQUIRED_DISCLOSURE_MISSING`."
    PRD §3.2: "The `disclosure_completeness_score` must be at least 80.00, or the
    submission is refused with `ERR_DISCLOSURE_INCOMPLETE`."
    PRD §3.2: "Finally, and last of all, the broker's `fee_credit_cents` must be
    at least the provisional filing fee this submission assesses, or the
    submission is refused with `ERR_FILING_FEE_UNPAID` (402)."

    Design: Corner/validations/missing_required_disclosure_outranks_completeness_and_fee_shortfalls
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)
    registration = open_draft_registration(ctx["broker_id"], ctx["broker_headers"])
    add_disclosures(
        registration["id"],
        ctx["broker_headers"],
        categories=["SOURCES", "RECIPIENTS", "RETENTION"],
    )

    response = api_client.submit_registration(registration["id"], ctx["broker_headers"])
    error = validate_error(response, ApiErrorId.ERR_REQUIRED_DISCLOSURE_MISSING, 422)
    assert error["error_id"] != ApiErrorId.ERR_DISCLOSURE_INCOMPLETE.value
    assert error["error_id"] != ApiErrorId.ERR_FILING_FEE_UNPAID.value

    refreshed = fetch_registration(registration["id"], ctx["broker_headers"])
    assert_score_equals(
        refreshed["disclosure_completeness_score"],
        60.00,
        "disclosure_completeness_score",
    )
    assert refreshed["status"] == "DRAFT"
    assert refreshed["submitted_at"] is None
    assert_cents_equals(refreshed["charged_fee_cents"], 0, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_credit_cents"], 0, "fee_credit_cents")
