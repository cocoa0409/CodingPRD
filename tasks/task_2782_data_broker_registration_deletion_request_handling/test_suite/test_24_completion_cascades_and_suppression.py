"""The completion join, the withdrawal cascade, and the suppression buffer.

Every test builds its own estate from scratch: the harness restarts the API and
wipes the database before each test function.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_ALPHA_HEADERS,
    ApiErrorId,
    api_client,
    assert_broker_ledger_conserved,
    assert_cents_equals,
    assert_instant_equals,
    assert_propagation_counters_conserved,
    assert_ratio_equals,
    assert_score_equals,
    assert_suppression_entry,
    decide_verification,
    dispatch_and_ack_task,
    dispatch_task,
    execute_deletion_request,
    fetch_broker,
    fetch_consumer,
    fetch_deletion_request,
    fetch_propagation_task,
    fetch_recipient,
    find_task,
    get_success_data,
    open_deletion_request,
    record_verification_attempt,
    setup_completed_deletion_request,
    setup_consumer_of_broker,
    setup_executing_deletion_request,
    suppression_for_request,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = CLOCK_TEST_INSTANT
JOIN_WINDOW_END = "2028-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Local composite setups
# ---------------------------------------------------------------------------


def _executing_request_with_open_sibling() -> dict:
    """One EXECUTING request whose ACTIVE_DATABASE task is already ACKED and whose
    BACKUP_ARCHIVE task is DISPATCHED, plus a second still-RECEIVED request for
    the same consumer."""
    ctx = setup_executing_deletion_request(clock=CLOCK)
    ctx["sibling"] = open_deletion_request(
        ctx["broker_id"],
        fetch_consumer(ctx["consumer_id"], ctx["broker_headers"]),
        intake_channel="EMAIL",
    )
    ctx["sibling_id"] = ctx["sibling"]["id"]
    ctx["db_task"] = ctx["tasks_by_kind"]["ACTIVE_DATABASE"]
    ctx["backup_task"] = ctx["tasks_by_kind"]["BACKUP_ARCHIVE"]
    dispatch_and_ack_task(ctx["db_task"]["id"], ctx["broker_headers"])
    dispatch_task(ctx["backup_task"]["id"], ctx["broker_headers"])
    return ctx


def _ack(task_id: str, headers) -> dict:
    """Acknowledge a DISPATCHED task, pinning the 200 an action endpoint owes."""
    return validate_success(api_client.ack_propagation_task(task_id, headers), 200)


def _purged_consumer_with_granted_consent() -> dict:
    """A HEALTH-category consumer whose consent was granted, whose deletion was
    then executed and whose two internal tasks were both acknowledged, so the
    collection dimension has walked ACTIVE -> PURGE_PENDING -> PURGED while the
    consent dimension sits at CONSENT_GRANTED."""
    ctx = setup_consumer_of_broker(clock=CLOCK, sensitive_categories=["HEALTH"])
    ctx["consumer"] = get_success_data(
        api_client.record_consent_action(
            ctx["consumer_id"], {"action": "GRANT"}, ctx["consumer_headers"]
        )
    )
    request = open_deletion_request(ctx["broker_id"], ctx["consumer"])
    ctx["request_id"] = request["id"]
    record_verification_attempt(ctx["request_id"])
    decide_verification(ctx["request_id"], "VERIFIED", headers=REVIEWER_ALPHA_HEADERS)
    ctx["request"] = execute_deletion_request(ctx["request_id"])
    ctx["consumer_after_execute"] = fetch_consumer(
        ctx["consumer_id"], ctx["broker_headers"]
    )
    for target_kind in ("ACTIVE_DATABASE", "BACKUP_ARCHIVE"):
        task = find_task(
            ctx["request_id"], ctx["broker_headers"], target_kind=target_kind
        )
        dispatch_and_ack_task(task["id"], ctx["broker_headers"])
    return ctx


# ---------------------------------------------------------------------------
# The final acknowledgement and the four links it sets off
# ---------------------------------------------------------------------------


def test_final_acknowledgement_completes_the_request_and_purges_the_consumer():
    """PRD §3.6: "Acknowledgement sets `acknowledged_at` to the current clock
    instant and sets `ack_was_late` true exactly when `acknowledged_at` is
    strictly after `due_at` — an acknowledgement landing exactly on `due_at` is on
    time."
    PRD §3.6: "The task moves `DISPATCHED → ACKED`, which is terminal, the owning
    request's `acked_task_count` increases by one and `outstanding_task_count`
    decreases by one, its `completion_ratio` is recomputed, and a
    `PROPAGATION_ACKED` audit event is appended."
    PRD §3.6: "When `completion_ratio` is at least 1.0000 the request moves
    `EXECUTING → COMPLETED` and `compliance_breach` stays false."
    PRD §3.6: "The consumer's collection dimension moves `PURGE_PENDING → PURGED`
    and `last_purged_at` is set to the current clock instant."

    Design: Difficulty/transitive_cascade/final_ack_completes_request_purges_consumer_mints_suppression_supersedes_sibling
    """
    ctx = _executing_request_with_open_sibling()

    task = _ack(ctx["backup_task"]["id"], ctx["broker_headers"])

    assert task["status"] == "ACKED"
    assert task["ack_was_late"] is False
    assert_instant_equals(task["acknowledged_at"], CLOCK, "acknowledged_at")

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "COMPLETED"
    assert_ratio_equals(request["completion_ratio"], "1.0000")
    assert request["compliance_breach"] is False
    assert request["acked_task_count"] == 2
    assert request["outstanding_task_count"] == 0
    assert_propagation_counters_conserved(request)

    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "PURGED"
    assert_instant_equals(consumer["last_purged_at"], CLOCK, "last_purged_at")


def test_completion_join_mints_the_two_year_suppression_entry():
    """PRD §3.6: "One `SuppressionEntry` is created for that broker and consumer
    with `status` `ACTIVE`, `source_scope` `ALL_SOURCES`, `window_start` at the
    current clock instant, `window_end` at `window_start` advanced by 730 whole
    days, `originating_request_id` set to the completing request's `id`, and
    `blocked_recollection_count` at zero — a completed deletion automatically buys
    the consumer two years of protection from re-collection from any source."
    PRD §2.7: "Adding n days to an instant advances it by exactly n times
    twenty-four hours and preserves the time-of-day component of the base instant;
    the result is stored as ISO 8601 UTC with three fractional digits."

    Design: Difficulty/transitive_cascade/final_ack_completes_request_purges_consumer_mints_suppression_supersedes_sibling
    """
    ctx = _executing_request_with_open_sibling()

    _ack(ctx["backup_task"]["id"], ctx["broker_headers"])

    entry = suppression_for_request(ctx["request_id"], ctx["broker_headers"])
    assert_suppression_entry(entry)
    assert entry["status"] == "ACTIVE"
    assert entry["source_scope"] == "ALL_SOURCES"
    assert_instant_equals(entry["window_start"], CLOCK, "window_start")
    assert_instant_equals(entry["window_end"], JOIN_WINDOW_END, "window_end")
    assert entry["originating_request_id"] == ctx["request_id"]
    assert entry["blocked_recollection_count"] == 0


def test_completion_join_supersedes_the_consumers_other_open_request():
    """PRD §3.6: "Then, caused by the suppression entry rather than by the
    completion itself, every **other** deletion request of the same consumer whose
    `status` is `RECEIVED`, `VERIFICATION_PENDING`, or `VERIFICATION_FAILED` moves
    to `SUPERSEDED`, and for each one the broker's `request_open_count` decreases
    by one while `request_terminated_count` increases by one."
    PRD §3.6: "Either branch increments the broker's `request_completed_count` and
    decrements `request_open_count` for this request — a partially completed
    request is closed, not abandoned."
    PRD §2.7: "On a broker, `request_intake_total` always equals
    `request_open_count` plus `request_completed_count` plus
    `request_terminated_count`"

    Design: Difficulty/transitive_cascade/final_ack_completes_request_purges_consumer_mints_suppression_supersedes_sibling
    """
    ctx = _executing_request_with_open_sibling()
    sibling_before = fetch_deletion_request(ctx["sibling_id"], ctx["broker_headers"])
    assert sibling_before["status"] == "RECEIVED"

    _ack(ctx["backup_task"]["id"], ctx["broker_headers"])

    sibling = fetch_deletion_request(ctx["sibling_id"], ctx["broker_headers"])
    assert sibling["status"] == "SUPERSEDED"

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["request_intake_total"] == 2
    assert broker["request_open_count"] == 0
    assert broker["request_completed_count"] == 1
    assert broker["request_terminated_count"] == 1


# ---------------------------------------------------------------------------
# The withdrawal cascade: refund, standing, recipient posture, parked work
# ---------------------------------------------------------------------------


def _broker_mid_propagation_with_one_recipient() -> dict:
    """An EXECUTING request whose plan covers ACTIVE_DATABASE, BACKUP_ARCHIVE and
    one propagation-obligated recipient, with every task still PENDING."""
    ctx = setup_executing_deletion_request(clock=CLOCK, recipient_count=1)
    ctx["db_task"] = ctx["tasks_by_kind"]["ACTIVE_DATABASE"]
    ctx["downstream_task"] = find_task(
        ctx["request_id"], ctx["broker_headers"], recipient_id=ctx["recipient_id"]
    )
    return ctx


def _withdraw(registration_id: str, headers) -> dict:
    return validate_success(
        api_client.withdraw_registration(registration_id, headers), 200
    )


def test_withdrawal_refunds_the_charged_fee_and_flips_standing_to_delinquent():
    """PRD §3.2: "Withdrawal moves the filing to `WITHDRAWN`, which is terminal,
    and runs the identical four-link cascade as rejection: refund
    `charged_fee_cents` from `fee_paid_cents` into `fee_credit_cents` and zero it;
    re-derive standing, setting `delinquent_since` and appending
    `STANDING_CHANGED` on a flip from `COMPLIANT` to `DELINQUENT`; on a genuine
    standing change, suspend every `ACTIVE` recipient of the broker whose
    `contract_propagation_required` is true and append a
    `RECIPIENT_STATUS_CHANGED` event for each; and for each recipient so
    suspended, defer its `PENDING` and `DISPATCHED` tasks with `deferral_reason`
    `BROKER_DELINQUENT`, appending a `PROPAGATION_DEFERRED` event for each."
    PRD §3.1: "On a transition into `DELINQUENT` or `SUSPENDED` from `COMPLIANT`,
    `delinquent_since` is set to the current clock instant."

    Design: Difficulty/transitive_cascade/registration_withdraw_refunds_fee_flips_standing_suspends_recipient_defers_task
    """
    ctx = _broker_mid_propagation_with_one_recipient()

    registration = _withdraw(ctx["registration_id"], ctx["broker_headers"])

    assert registration["status"] == "WITHDRAWN"
    assert_cents_equals(registration["charged_fee_cents"], 0, "charged_fee_cents")

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 500000, "fee_credit_cents")
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_broker_ledger_conserved(broker)
    assert broker["registry_standing"] == "DELINQUENT"
    assert_instant_equals(broker["delinquent_since"], CLOCK, "delinquent_since")


def test_withdrawal_suspends_the_obligated_recipient_and_defers_only_its_task():
    """PRD §3.2: "Withdrawal moves the filing to `WITHDRAWN`, which is terminal,
    and runs the identical four-link cascade as rejection: refund
    `charged_fee_cents` from `fee_paid_cents` into `fee_credit_cents` and zero it;
    re-derive standing, setting `delinquent_since` and appending
    `STANDING_CHANGED` on a flip from `COMPLIANT` to `DELINQUENT`; on a genuine
    standing change, suspend every `ACTIVE` recipient of the broker whose
    `contract_propagation_required` is true and append a
    `RECIPIENT_STATUS_CHANGED` event for each; and for each recipient so
    suspended, defer its `PENDING` and `DISPATCHED` tasks with `deferral_reason`
    `BROKER_DELINQUENT`, appending a `PROPAGATION_DEFERRED` event for each."
    PRD §3.5: "Every minted task starts in `PENDING` with `dispatched_at`,
    `acknowledged_at`, `failure_code`, `deferral_reason`, and
    `waiver_justification` all null, `ack_was_late` false, and `dispatch_count`
    zero, and carries the `deletion_request_id` of its owning request."

    Design: Difficulty/transitive_cascade/registration_withdraw_refunds_fee_flips_standing_suspends_recipient_defers_task
    """
    ctx = _broker_mid_propagation_with_one_recipient()

    _withdraw(ctx["registration_id"], ctx["broker_headers"])

    recipient = fetch_recipient(ctx["recipient_id"], ctx["broker_headers"])
    assert recipient["status"] == "SUSPENDED"
    assert_score_equals(recipient["reliability_score"], "90.00", "reliability_score")

    downstream_task = fetch_propagation_task(
        ctx["downstream_task"]["id"], ctx["broker_headers"]
    )
    assert downstream_task["status"] == "DEFERRED"
    assert downstream_task["deferral_reason"] == "BROKER_DELINQUENT"

    internal_task = fetch_propagation_task(ctx["db_task"]["id"], ctx["broker_headers"])
    assert internal_task["status"] == "PENDING"
    assert internal_task["deferral_reason"] is None


def test_withdrawal_leaves_the_executing_requests_obligation_set_untouched():
    """PRD §3.5: "Because `propagation_required_count` is fixed at the fork and
    never re-derived, adding or suspending a recipient afterwards does not change
    the obligation set of a request already executing."
    PRD §3.6: "The join is evaluated only when no task of the request remains in
    `PENDING`, `DISPATCHED`, `DEFERRED`, or `FAILED` — that is, when every task has
    reached `ACKED`, `WAIVED`, or `ABANDONED`."
    PRD §3.6: "Neither `DEFERRED` nor `FAILED` reduces `outstanding_task_count`;
    only the three terminal task statuses do."

    Design: Difficulty/transitive_cascade/registration_withdraw_refunds_fee_flips_standing_suspends_recipient_defers_task
    """
    ctx = _broker_mid_propagation_with_one_recipient()

    _withdraw(ctx["registration_id"], ctx["broker_headers"])

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "EXECUTING"
    assert request["propagation_required_count"] == 3
    assert request["downstream_task_count"] == 1
    assert request["outstanding_task_count"] == 3
    assert_ratio_equals(request["completion_ratio"], "0.0000")
    assert_propagation_counters_conserved(request)


# ---------------------------------------------------------------------------
# The symmetric 30-day re-collection buffer around an ACTIVE window
# ---------------------------------------------------------------------------


def _suppression_payload(ctx: dict, window_start: str, window_end: str) -> dict:
    return {
        "broker_id": ctx["broker_id"],
        "consumer_id": ctx["consumer_id"],
        "originating_request_id": ctx["request_id"],
        "source_scope": "SINGLE_SOURCE",
        "window_start": window_start,
        "window_end": window_end,
    }


def test_window_starting_exactly_on_the_buffered_boundary_conflicts():
    """PRD §3.7: "And the new window, widened by a symmetric 30-day re-collection
    buffer on both sides, must not touch any `ACTIVE` entry for the same consumer,
    or `ERR_SUPPRESSION_WINDOW_CONFLICT` answers; the buffered test treats the new
    window as conflicting when its `window_start` is at or before the other
    entry's `window_end` advanced by 30 days **and** its `window_end` advanced by
    30 days is at or after the other entry's `window_start`."
    PRD §3.6: "One `SuppressionEntry` is created for that broker and consumer with
    `status` `ACTIVE`, `source_scope` `ALL_SOURCES`, `window_start` at the current
    clock instant, `window_end` at `window_start` advanced by 730 whole days,
    `originating_request_id` set to the completing request's `id`, and
    `blocked_recollection_count` at zero — a completed deletion automatically buys
    the consumer two years of protection from re-collection from any source."

    Design: Difficulty/resource_temporal_overlap/suppression_window_symmetric_thirty_day_buffer_is_inclusive_on_the_boundary
    """
    ctx = setup_completed_deletion_request(clock=CLOCK)

    minted = ctx["suppression"]
    assert minted["status"] == "ACTIVE"
    assert minted["source_scope"] == "ALL_SOURCES"
    assert_instant_equals(minted["window_start"], CLOCK, "window_start")
    assert_instant_equals(minted["window_end"], JOIN_WINDOW_END, "window_end")

    response = api_client.create_suppression_entry(
        _suppression_payload(ctx, "2028-09-30T00:00:00Z", "2029-09-30T00:00:00Z"),
        REVIEWER_ALPHA_HEADERS,
    )

    validate_error(
        response, ApiErrorId.ERR_SUPPRESSION_WINDOW_CONFLICT.value, 409
    )


def test_window_starting_one_day_past_the_buffer_is_accepted():
    """PRD §3.7: "And the new window, widened by a symmetric 30-day re-collection
    buffer on both sides, must not touch any `ACTIVE` entry for the same consumer,
    or `ERR_SUPPRESSION_WINDOW_CONFLICT` answers; the buffered test treats the new
    window as conflicting when its `window_start` is at or before the other
    entry's `window_end` advanced by 30 days **and** its `window_end` advanced by
    30 days is at or after the other entry's `window_start`."
    PRD §3.7: "The entry is created `ACTIVE` with `blocked_recollection_count` at
    zero and `lift_justification` null, and a `SUPPRESSION_CREATED` audit event is
    appended."

    Design: Difficulty/resource_temporal_overlap/suppression_window_symmetric_thirty_day_buffer_is_inclusive_on_the_boundary
    """
    ctx = setup_completed_deletion_request(clock=CLOCK)

    entry = validate_success(
        api_client.create_suppression_entry(
            _suppression_payload(ctx, "2028-10-01T00:00:00Z", "2029-10-01T00:00:00Z"),
            REVIEWER_ALPHA_HEADERS,
        ),
        201,
    )

    assert_suppression_entry(entry)
    assert entry["status"] == "ACTIVE"
    assert_instant_equals(entry["window_start"], "2028-10-01T00:00:00Z", "window_start")
    assert entry["blocked_recollection_count"] == 0

    _, meta = validate_paginated(
        api_client.list_suppression_entries(
            ctx["broker_headers"], params={"consumer_id": ctx["consumer_id"]}
        )
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Two independent state dimensions on one consumer row
# ---------------------------------------------------------------------------


def test_execution_moves_collection_to_purge_pending_leaving_consent_granted():
    """PRD §3.3: "A consumer carries **two independent state dimensions on the
    same record**, and they advance separately."
    PRD §3.3: "When a deletion is executed for the consumer, the dimension moves
    `ACTIVE → PURGE_PENDING`, or `REACQUIRED → PURGE_PENDING` if the person had
    previously been re-acquired; in either case `consent_status` is untouched,
    because the two dimensions advance independently."

    Design: Difficulty/non_linear_state_machine/consumer_collection_and_consent_dimensions_advance_independently
    """
    ctx = _purged_consumer_with_granted_consent()

    mid_flight = ctx["consumer_after_execute"]
    assert mid_flight["collection_status"] == "PURGE_PENDING"
    assert mid_flight["consent_status"] == "CONSENT_GRANTED"


def test_completion_join_purges_the_consumer_without_touching_its_consent():
    """PRD §3.3: "When the owning deletion request's propagation work all reaches a
    terminal status, the dimension moves `PURGE_PENDING → PURGED` and
    `last_purged_at` is set to the current clock instant."
    PRD §3.6: "When `completion_ratio` is at least 1.0000 the request moves
    `EXECUTING → COMPLETED` and `compliance_breach` stays false."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or before
    the current clock instant while its `coverage_period_end` is strictly after it,
    the standing is `COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/consumer_collection_and_consent_dimensions_advance_independently
    """
    ctx = _purged_consumer_with_granted_consent()

    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "PURGED"
    assert consumer["consent_status"] == "CONSENT_GRANTED"
    assert_instant_equals(consumer["last_purged_at"], CLOCK, "last_purged_at")

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "COMPLETED"
    assert_ratio_equals(request["completion_ratio"], "1.0000")
    assert request["compliance_breach"] is False

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["registry_standing"] == "COMPLIANT"


def test_revoking_consent_on_a_purged_consumer_leaves_it_purged():
    """PRD §3.3: "The consumer themselves grants consent, moving `CONSENT_PENDING →
    CONSENT_GRANTED`, and revokes it, moving `CONSENT_GRANTED → CONSENT_REVOKED`;
    both acts require that the acting `X-User-ID` equal the addressed consumer's
    own `id` when the caller's role is `Consumer`, or the act is refused with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.3: "Every accepted consent act leaves `collection_status` completely
    untouched and appends a `CONSENT_CHANGED` audit event."
    PRD §3.3: "a newly recorded consumer starts `ACTIVE` with
    `collection_event_count` set to 1, counting the creating call itself"

    Design: Difficulty/non_linear_state_machine/consumer_collection_and_consent_dimensions_advance_independently
    """
    ctx = _purged_consumer_with_granted_consent()

    consumer = validate_success(
        api_client.record_consent_action(
            ctx["consumer_id"], {"action": "REVOKE"}, ctx["consumer_headers"]
        ),
        200,
    )

    assert consumer["consent_status"] == "CONSENT_REVOKED"
    assert consumer["collection_status"] == "PURGED"
    assert_instant_equals(consumer["last_purged_at"], CLOCK, "last_purged_at")
    assert consumer["collection_event_count"] == 1
