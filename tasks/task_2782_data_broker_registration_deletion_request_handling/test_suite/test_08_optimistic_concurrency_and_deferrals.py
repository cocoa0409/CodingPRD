"""Stale-view protection on broker and consumer writes, and deferred signal honoring.

Every test builds its own state from scratch: the harness restarts the API server
and wipes the database before each individual test.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_score_equals,
    create_deletion_request_payload,
    create_fee_deposit_payload,
    create_opt_out_signal,
    create_opt_out_signal_payload,
    create_registration_payload,
    fetch_consumer,
    get_success_data,
    make_consumer_headers,
    make_state_platform_headers,
    onboard_broker,
    record_consumer,
    run_sweep,
    set_clock,
    setup_consumer_of_broker,
    validate_error,
    validate_paginated,
    validate_success,
)

SIGNAL_HONOR_DEADLINE = "2026-10-16T00:00:00Z"
DAY_BEFORE_HONOR_DEADLINE = "2026-10-15T00:00:00Z"


def _broker_moved_to_version_two() -> dict:
    """A broker created at version 1 and moved to version 2 by a 500000-cent
    fee deposit."""
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    assert ctx["broker"]["version"] == 1
    ctx["broker"] = get_success_data(
        api_client.create_fee_deposit(
            ctx["broker_id"],
            create_fee_deposit_payload(amount_cents=500000),
            ctx["broker_headers"],
        )
    )
    assert ctx["broker"]["version"] == 2
    return ctx


def _consumer_moved_to_version_two(**collection_overrides) -> dict:
    """A consumer of a broker holding an ACCEPTED CA filing, created at version 1
    and moved to version 2 by one recorded collection event."""
    ctx = setup_consumer_of_broker(clock=CLOCK_TEST_INSTANT)
    assert ctx["consumer"]["version"] == 1
    payload = {"source_label": "OWNERSHIP_FEED_E"}
    payload.update(collection_overrides)
    ctx["consumer"] = get_success_data(
        api_client.record_collection(
            ctx["consumer_id"], payload, ctx["broker_headers"]
        )
    )
    assert ctx["consumer"]["version"] == 2
    return ctx


def _signal_awaiting_its_honor_deadline() -> dict:
    """One RECEIVED WRITTEN_REQUEST signal of scope SALE, created at
    2026-09-01T00:00:00Z, with both consumer opt-out flags still false."""
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK_TEST_INSTANT)
    consumer = record_consumer(ctx["broker_id"])
    signal = create_opt_out_signal(
        ctx["broker_id"], consumer, signal_type="WRITTEN_REQUEST", scope="SALE"
    )
    assert signal["status"] == "RECEIVED"
    assert signal["honored_at"] is None
    assert_instant_equals(
        signal["honor_deadline_at"], SIGNAL_HONOR_DEADLINE, "honor_deadline_at"
    )
    ctx["consumer"] = consumer
    ctx["consumer_id"] = consumer["id"]
    ctx["signal"] = signal
    ctx["signal_id"] = signal["id"]
    return ctx


def test_a_filing_presenting_a_stale_broker_version_is_rejected_and_creates_nothing():
    """PRD §2.4: "`version`, an integer that begins at 1 when the resource is created
    and increases by one on every mutation of that resource"
    PRD §2.5: "Creating a registration filing requires `expected_broker_version`,
    carrying the client's last observed `version` of the parent `DataBroker`. If that
    value does not equal the broker's current `version`, the create is rejected with
    `ERR_STALE_BROKER_VERSION` (HTTP 412)."
    PRD §2.6: "`expected_broker_version` equals the addressed broker's current
    `version` — otherwise `ERR_STALE_BROKER_VERSION` (412). Applies to
    `POST /registrations`."
    PRD §3.2: "The filing is created in `DRAFT` with a `disclosure_completeness_score`
    of 0.00, a `revision_count` of 0, a `charged_fee_cents` of 0, a
    `provisional_filing_fee_cents` of 0, a null `final_filing_fee_cents`, null
    `submitted_at` and `accepted_at`, and a null `rejection_reason_code`."

    Design: Corner/cross_cutting_complexity_layers/stale_broker_version_on_registration_create_rejected
    """
    ctx = _broker_moved_to_version_two()

    stale = api_client.create_registration(
        create_registration_payload(ctx["broker_id"], 1), ctx["broker_headers"]
    )

    validate_error(stale, ApiErrorId.ERR_STALE_BROKER_VERSION, 412)
    _, meta = validate_paginated(
        api_client.list_registrations(
            ctx["broker_headers"], params={"broker_id": ctx["broker_id"]}
        )
    )
    assert meta["total_count"] == 0

    fresh = validate_success(
        api_client.create_registration(
            create_registration_payload(ctx["broker_id"], 2), ctx["broker_headers"]
        ),
        201,
    )
    assert fresh["status"] == "DRAFT"
    assert_score_equals(
        fresh["disclosure_completeness_score"], 0.00, "disclosure_completeness_score"
    )
    assert fresh["version"] == 1


def test_a_deletion_request_presenting_a_stale_consumer_version_is_rejected():
    """PRD §2.5: "Creating a deletion request requires `expected_consumer_version`,
    carrying the client's last observed `version` of the referenced `Consumer`. A
    mismatch with the consumer's current `version` is rejected with
    `ERR_STALE_CONSUMER_VERSION` (HTTP 412)."
    PRD §2.6: "`expected_consumer_version` equals the referenced consumer's current
    `version` — otherwise `ERR_STALE_CONSUMER_VERSION` (412). Applies to
    `POST /deletion-requests` and `POST /opt-out-signals`."
    PRD §3.3: "a newly recorded consumer starts `ACTIVE` with `collection_event_count`
    set to 1, counting the creating call itself"
    PRD §3.3: "Its payload is deliberately small: a `source_label`, plus an optional
    `derived_profile_count` which, when supplied, replaces the stored value."
    PRD §3.3: "On success, `collection_event_count` increases by one, `source_label` is
    replaced by the submitted value, and a `CONSUMER_COLLECTION_RECORDED` audit event is
    appended."
    PRD §3.4: "An accepted request is created in `RECEIVED` with `intake_user_id` set to
    the acting `X-User-ID`, `identity_assurance_score` at 0.00"

    Design: Corner/cross_cutting_complexity_layers/stale_consumer_version_on_deletion_request_create_rejected
    """
    ctx = _consumer_moved_to_version_two(derived_profile_count=2)
    assert ctx["consumer"]["collection_event_count"] == 2
    assert ctx["consumer"]["derived_profile_count"] == 2
    platform_headers = make_state_platform_headers("ca-deletion-platform")

    stale = api_client.create_deletion_request(
        create_deletion_request_payload(
            ctx["broker_id"],
            ctx["consumer_id"],
            1,
            intake_channel="STATE_PLATFORM",
            requested_scope="DELETE_ALL",
        ),
        platform_headers,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_CONSUMER_VERSION, 412)
    _, meta = validate_paginated(
        api_client.list_deletion_requests(
            ctx["broker_headers"], params={"consumer_id": ctx["consumer_id"]}
        )
    )
    assert meta["total_count"] == 0

    fresh = validate_success(
        api_client.create_deletion_request(
            create_deletion_request_payload(
                ctx["broker_id"],
                ctx["consumer_id"],
                2,
                intake_channel="STATE_PLATFORM",
                requested_scope="DELETE_ALL",
            ),
            platform_headers,
        ),
        201,
    )
    assert fresh["status"] == "RECEIVED"
    assert_score_equals(
        fresh["identity_assurance_score"], 0.00, "identity_assurance_score"
    )


def test_an_opt_out_signal_presenting_a_stale_consumer_version_leaves_the_flags_false():
    """PRD §2.5: "Recording an opt-out signal likewise requires
    `expected_consumer_version` against the referenced `Consumer`, and a mismatch is
    rejected with `ERR_STALE_CONSUMER_VERSION` (HTTP 412)."
    PRD §2.6: "`expected_consumer_version` equals the referenced consumer's current
    `version` — otherwise `ERR_STALE_CONSUMER_VERSION` (412). Applies to
    `POST /deletion-requests` and `POST /opt-out-signals`."
    PRD §3.3: "Creation also sets `opt_out_sale` and `opt_out_sharing` to false and
    `last_purged_at` to null, and appends a `CONSUMER_RECORDED` audit event."
    PRD §3.7: "Two mechanisms are honored **inside the creating request** rather than
    deferred: a `GPC_BROWSER` signal carrying the value `1`, and any `PLATFORM_BULK`
    signal"
    PRD §3.7: "For those the signal moves `RECEIVED → HONORED` immediately, `honored_at`
    is set to the current clock instant, the consumer's `opt_out_sale` is set true when
    `scope` is `SALE` or `SALE_AND_SHARING`, the consumer's `opt_out_sharing` is set true
    when `scope` is `SHARING` or `SALE_AND_SHARING`"

    Design: Corner/cross_cutting_complexity_layers/stale_consumer_version_on_opt_out_signal_create_rejected
    """
    ctx = _consumer_moved_to_version_two()
    consumer_headers = make_consumer_headers(ctx["consumer_id"])

    stale = api_client.create_opt_out_signal(
        create_opt_out_signal_payload(
            ctx["broker_id"],
            ctx["consumer_id"],
            1,
            signal_type="GPC_BROWSER",
            scope="SALE",
            gpc_header_value="1",
        ),
        consumer_headers,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_CONSUMER_VERSION, 412)
    _, meta = validate_paginated(
        api_client.list_opt_out_signals(
            ctx["broker_headers"], params={"consumer_id": ctx["consumer_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fetch_consumer(ctx["consumer_id"], consumer_headers)["opt_out_sale"] is False

    fresh = validate_success(
        api_client.create_opt_out_signal(
            create_opt_out_signal_payload(
                ctx["broker_id"],
                ctx["consumer_id"],
                2,
                signal_type="GPC_BROWSER",
                scope="SALE",
                gpc_header_value="1",
            ),
            consumer_headers,
        ),
        201,
    )
    assert fresh["status"] == "HONORED"
    consumer = fetch_consumer(ctx["consumer_id"], consumer_headers)
    assert consumer["opt_out_sale"] is True
    assert consumer["opt_out_sharing"] is False


def test_a_deferred_written_request_signal_is_not_honored_before_its_deadline():
    """PRD §3.7: "An accepted signal is created in `RECEIVED` with `honored_at` null and
    `honor_deadline_at` set to the creation clock instant advanced by 45 whole days"
    PRD §3.7: "A `WRITTEN_REQUEST` or `AGENT_SUBMITTED` signal instead stays in
    `RECEIVED` with the consumer's flags untouched until the compliance sweep reaches its
    `honor_deadline_at`"
    PRD §3.9: "**Step 4** honors deferred preference signals: every `RECEIVED` opt-out
    signal whose `honor_deadline_at` is at or before the clock moves
    `RECEIVED → HONORED`, `honored_at` is set to the clock instant, the consumer's
    `opt_out_sale` and `opt_out_sharing` are set per the signal's `scope`, and
    `OPT_OUT_HONORED` is appended."
    PRD §3.9: "Each counter counts only the rows that step actually moved, so a second
    sweep at the same clock instant reports all zeros."

    Design: Corner/cross_cutting_complexity_layers/deferred_signal_honoring_fires_only_once_the_deadline_is_reached
    """
    ctx = _signal_awaiting_its_honor_deadline()

    set_clock(DAY_BEFORE_HONOR_DEADLINE)
    summary = run_sweep()

    assert summary["honored_signal_count"] == 0
    signal = get_success_data(
        api_client.get_opt_out_signal(ctx["signal_id"], ctx["broker_headers"])
    )
    assert signal["status"] == "RECEIVED"
    assert signal["honored_at"] is None
    assert (
        fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])["opt_out_sale"]
        is False
    )


def test_a_deferred_written_request_signal_is_honored_by_the_sweep_at_its_deadline():
    """PRD §3.7: "A `WRITTEN_REQUEST` or `AGENT_SUBMITTED` signal instead stays in
    `RECEIVED` with the consumer's flags untouched until the compliance sweep reaches its
    `honor_deadline_at`"
    PRD §3.9: "**Step 4** honors deferred preference signals: every `RECEIVED` opt-out
    signal whose `honor_deadline_at` is at or before the clock moves
    `RECEIVED → HONORED`, `honored_at` is set to the clock instant, the consumer's
    `opt_out_sale` and `opt_out_sharing` are set per the signal's `scope`, and
    `OPT_OUT_HONORED` is appended."
    PRD §3.9: "The sweep answers with a summary of what it did: `swept_at` carrying the
    clock instant the sweep ran at"

    Design: Corner/cross_cutting_complexity_layers/deferred_signal_honoring_fires_only_once_the_deadline_is_reached
    """
    ctx = _signal_awaiting_its_honor_deadline()

    set_clock(SIGNAL_HONOR_DEADLINE)
    summary = run_sweep()

    assert summary["honored_signal_count"] == 1
    assert_instant_equals(summary["swept_at"], SIGNAL_HONOR_DEADLINE, "swept_at")
    signal = get_success_data(
        api_client.get_opt_out_signal(ctx["signal_id"], ctx["broker_headers"])
    )
    assert signal["status"] == "HONORED"
    assert_instant_equals(signal["honored_at"], SIGNAL_HONOR_DEADLINE, "honored_at")
    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["opt_out_sale"] is True
    assert consumer["opt_out_sharing"] is False
    _, meta = validate_paginated(
        api_client.list_audit_events(
            ctx["broker_id"],
            ctx["broker_headers"],
            params={"event_type": "OPT_OUT_HONORED"},
        )
    )
    assert meta["total_count"] == 1
