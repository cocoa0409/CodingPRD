"""Corner queue B — calculations section instances."""

from test_helpers import (
    ApiErrorId,
    assert_instants_equal,
    make_recipient_headers,
    open_deletion_request,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cost_summary_medium_tier_units_below_free_allowance(api):
    """PRD §3.9: "under `MEDIUM`, 4 and 2... The summed units are then offset
    by a free allowance per rate class — 10 units for `LOW`, 20 for `MEDIUM`,
    40 for `HIGH`. Billable units are the excess of total units over the
    allowance, floored at zero, and the cost in cents is exactly 100 per
    billable unit."

    Design: Corner/calculations/cost_summary_medium_tier_units_below_free_allowance
    """
    stack = setup_active_stack(
        api,
        institution_name="Medium Bank",
        recipient_name="MediumApp",
        consumer_ref="cons_y",
        rate_class="MEDIUM",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    for _ in range(3):
        job = validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
        assert job["status"] == "SUCCEEDED"

    summary = validate_success(api.get_cost_summary(conn_id, consumer))
    assert summary["rate_class"] == "MEDIUM"
    # complete_auth's initial FULL + 3 explicit FULL = 4 jobs x 4 units.
    assert summary["units"] == 16, f"4 MEDIUM FULL jobs must total 16 units, got {summary['units']}"
    assert summary["billable_units"] == 0, (
        "16 units against the MEDIUM free allowance of 20 must bill 0"
    )
    assert summary["cost_cents"] == 0


def test_webhook_fanout_one_event_per_transaction_refresh(api):
    """PRD §3.7: "When the consent covers `TRANSACTIONS` and
    `new_transaction_count` is greater than zero, a `TRANSACTIONS_AVAILABLE`
    webhook is emitted to the recipient whose consent underlies the
    connection, carrying that count in its `payload`."

    Design: Corner/calculations/webhook_fanout_one_event_per_transaction_refresh
    """
    stack = setup_active_stack(
        api,
        institution_name="Webhook Bank",
        recipient_name="TxFeed",
        consumer_ref="cons_z",
        data_scopes=["TRANSACTIONS"],
        permitted_fields_by_scope={"TRANSACTIONS": ["amount_cents", "posted_at"]},
        tier_scopes=["TRANSACTIONS"],
        rate_class="HIGH",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "new_transaction_count": 7}, consumer
        )
    )
    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "new_transaction_count": 0}, consumer
        )
    )

    events, meta = validate_paginated(
        api.list_connection_webhook_events(
            conn_id, stack["admin"], params={"event_type": "TRANSACTIONS_AVAILABLE"}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the positive-count refresh may emit a webhook, got {meta['total_count']}"
    )
    assert events[0]["payload"]["new_transaction_count"] == 7
    assert events[0]["recipient_id"] == stack["recipient"]["id"]


def test_deletion_progress_completes_after_last_recipient_ack(api):
    """PRD §3.11: "Creation moves the new request straight from `PENDING` to
    `PROPAGATING`, stamps `requested_at` with the clock, and emits a
    `DATA_DELETED` webhook to every recipient that ever held the consent's
    data (the consent's recipient). If the consent is still `ACTIVE` at that
    moment, it is immediately revoked — `revoked_at` stamped, connections
    disconnected, the full revocation cascade of §3.5."
    PRD §3.11: "When the set of required recipients minus the acknowledged set
    becomes empty, the request moves to `ACKED_BY_ALL` and immediately on to
    `COMPLETED`, with `completed_at` stamped at the clock."

    Design: Corner/calculations/deletion_progress_completes_after_last_recipient_ack
    """
    stack = setup_active_stack(
        api,
        institution_name="Delete Bank",
        recipient_name="DeleteApp",
        consumer_ref="cons_aa",
    )
    consumer = stack["consumer"]
    consent_id = stack["consent"]["id"]

    request = validate_success(
        api.create_deletion_request(consent_id, consumer), expected_status=201
    )
    assert request["status"] == "PROPAGATING"

    consent = validate_success(api.get_consent(consent_id, consumer))
    assert consent["status"] == "REVOKED", (
        "opening a deletion request on an ACTIVE consent must revoke it immediately"
    )
    connection = validate_success(api.get_connection(stack["connection"]["id"], consumer))
    assert connection["status"] == "DISCONNECTED"

    completed = validate_success(
        api.ack_deletion_request(request["id"], make_recipient_headers(stack["recipient"]["id"]))
    )
    assert completed["status"] == "COMPLETED", (
        f"the last required ack must complete the request, got {completed['status']}"
    )
    assert_instants_equal(completed["completed_at"], "2026-09-01T00:00:00Z", "completed_at")

    events, meta = validate_paginated(
        api.list_recipient_webhook_events(
            stack["recipient"]["id"], stack["admin"], params={"event_type": "DATA_DELETED"}
        )
    )
    assert meta["total_count"] == 1

    dup = api.ack_deletion_request(request["id"], make_recipient_headers(stack["recipient"]["id"]))
    validate_error(dup, ApiErrorId.ERR_INVALID_STATE)
