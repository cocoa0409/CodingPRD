"""Propagation follow-through, the weighted completion join, and its counters."""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_ALPHA_HEADERS,
    REVIEWER_BETA_HEADERS,
    ApiErrorId,
    api_client,
    assert_propagation_counters_conserved,
    assert_ratio_equals,
    assert_score_equals,
    decide_verification,
    dispatch_and_ack_task,
    dispatch_task,
    execute_deletion_request,
    fail_task,
    fetch_broker,
    fetch_consumer,
    fetch_deletion_request,
    fetch_propagation_task,
    fetch_recipient,
    find_task,
    open_deletion_request,
    record_consumer,
    record_verification_attempt,
    set_recipient_status,
    setup_executing_deletion_request,
    validate_error,
    validate_success,
    waive_task,
)

def _execute_another_request_for_a_new_consumer(ctx: dict) -> dict:
    """A second consumer of the same broker carried through to EXECUTING."""
    consumer = record_consumer(
        ctx["broker_id"], state_code=ctx["consumer"]["state_code"]
    )
    request = open_deletion_request(ctx["broker_id"], consumer)
    record_verification_attempt(request["id"])
    decide_verification(request["id"], "VERIFIED", headers=REVIEWER_ALPHA_HEADERS)
    execute_deletion_request(request["id"], headers=REVIEWER_BETA_HEADERS)
    return {
        "consumer": consumer,
        "consumer_id": consumer["id"],
        "request_id": request["id"],
    }


def _setup_one_request_at_the_threshold_and_one_below_it() -> dict:
    """Two executing requests sharing one downstream recipient.

    The first has both internal obligations acknowledged; the second has its
    active-database obligation acknowledged and its backup obligation failed and
    then waived. Neither downstream task has been worked, so terminating the
    shared recipient abandons one task in each request and closes both joins.
    """
    ctx = setup_executing_deletion_request(recipient_count=1, clock=CLOCK_TEST_INSTANT)
    broker_headers = ctx["broker_headers"]

    dispatch_and_ack_task(
        ctx["tasks_by_kind"]["ACTIVE_DATABASE"]["id"], broker_headers
    )
    dispatch_and_ack_task(
        ctx["tasks_by_kind"]["BACKUP_ARCHIVE"]["id"], broker_headers
    )

    second = _execute_another_request_for_a_new_consumer(ctx)
    dispatch_and_ack_task(
        find_task(
            second["request_id"], broker_headers, target_kind="ACTIVE_DATABASE"
        )["id"],
        broker_headers,
    )
    archive = find_task(
        second["request_id"], broker_headers, target_kind="BACKUP_ARCHIVE"
    )
    dispatch_task(archive["id"], broker_headers)
    fail_task(archive["id"], broker_headers, failure_code="SCHEMA_MISMATCH")
    waive_task(archive["id"], broker_headers)

    ctx["second"] = second
    return ctx


def test_completion_ratio_at_exactly_the_breach_threshold_is_not_a_breach():
    """PRD §3.6: "When it is below 1.0000 the request moves `EXECUTING → PARTIALLY_COMPLETED`, and `compliance_breach` is set true only when the ratio is strictly below 0.7500: a ratio of exactly 0.7500 is not a breach, while 0.7499 is."
    PRD §3.6: "The numerator is the sum of `weight` over tasks in `ACKED`, plus one half of the sum of `weight` over tasks in `WAIVED`."
    PRD §3.6: "The denominator is the sum of `weight` over **every** task of the request, with no status filter, so `ABANDONED` tasks remain in the denominator and contribute nothing to the numerator — which is precisely what makes the ratio fall when the sweep abandons work."
    PRD §3.6: "The ratio is rounded half up to four decimal places, and is 1.0000 by definition when the denominator is zero."
    PRD §3.6: "The join is evaluated only when no task of the request remains in `PENDING`, `DISPATCHED`, `DEFERRED`, or `FAILED` — that is, when every task has reached `ACKED`, `WAIVED`, or `ABANDONED`."
    PRD §3.6: "Termination is allowed from `ACTIVE` and from `SUSPENDED`, is terminal, and abandons the recipient's remaining work: every task whose `status` is `PENDING`, `DISPATCHED`, `DEFERRED`, or `FAILED` moves to `ABANDONED`, each owning request's `abandoned_task_count` increases while `outstanding_task_count` decreases, each recomputes its `completion_ratio`, and each re-evaluates its join."
    PRD §3.5: "An internal task records its `target_kind`, a null `recipient_id`, a `weight` of 40 for `ACTIVE_DATABASE`, 20 for `BACKUP_ARCHIVE`, and 20 for `DERIVED_DATASET`, and an `sla_days` of 5 for `ACTIVE_DATABASE`, 45 for `BACKUP_ARCHIVE`, and 15 for `DERIVED_DATASET` — the live database must be scrubbed within five days while backup rewriting is allowed forty-five."
    PRD §3.6: "The consumer's collection dimension moves `PURGE_PENDING → PURGED` and `last_purged_at` is set to the current clock instant."

    Design: Difficulty/boundary_precision_check/completion_ratio_at_exactly_the_breach_threshold_is_not_a_breach
    """
    ctx = _setup_one_request_at_the_threshold_and_one_below_it()

    set_recipient_status(ctx["recipient_id"], "TERMINATED", ctx["broker_headers"])

    request = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    assert request["status"] == "PARTIALLY_COMPLETED"
    assert_ratio_equals(request["completion_ratio"], "0.7500", "completion_ratio")
    assert request["compliance_breach"] is False
    assert request["acked_task_count"] == 2
    assert request["waived_task_count"] == 0
    assert request["abandoned_task_count"] == 1
    assert request["outstanding_task_count"] == 0
    assert_propagation_counters_conserved(request)

    consumer = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "PURGED"


def test_a_waived_obligation_at_half_credit_lands_below_the_threshold_and_breaches():
    """PRD §3.6: "When it is below 1.0000 the request moves `EXECUTING → PARTIALLY_COMPLETED`, and `compliance_breach` is set true only when the ratio is strictly below 0.7500: a ratio of exactly 0.7500 is not a breach, while 0.7499 is."
    PRD §3.6: "The owning request's `waived_task_count` increases by one, `outstanding_task_count` decreases by one, and `completion_ratio` is recomputed with this task's `weight` counted at half credit."
    PRD §3.6: "The numerator is the sum of `weight` over tasks in `ACKED`, plus one half of the sum of `weight` over tasks in `WAIVED`."
    PRD §3.6: "When `compliance_breach` becomes true, the broker's `open_breach_count` increases by one and registry standing is re-derived, which forces `DELINQUENT` because a non-zero `open_breach_count` outranks the coverage clause."
    PRD §3.6: "Either branch increments the broker's `request_completed_count` and decrements `request_open_count` for this request — a partially completed request is closed, not abandoned."
    PRD §3.6: "The consumer's collection dimension moves `PURGE_PENDING → PURGED` and `last_purged_at` is set to the current clock instant."

    Design: Difficulty/boundary_precision_check/completion_ratio_at_exactly_the_breach_threshold_is_not_a_breach
    """
    ctx = _setup_one_request_at_the_threshold_and_one_below_it()

    set_recipient_status(ctx["recipient_id"], "TERMINATED", ctx["broker_headers"])

    second = fetch_deletion_request(
        ctx["second"]["request_id"], ctx["broker_headers"]
    )
    assert second["status"] == "PARTIALLY_COMPLETED"
    assert_ratio_equals(second["completion_ratio"], "0.6250", "completion_ratio")
    assert second["compliance_breach"] is True
    assert second["acked_task_count"] == 1
    assert second["waived_task_count"] == 1
    assert second["abandoned_task_count"] == 1
    assert second["outstanding_task_count"] == 0
    assert_propagation_counters_conserved(second)

    consumer = fetch_consumer(ctx["second"]["consumer_id"], ctx["broker_headers"])
    assert consumer["collection_status"] == "PURGED"

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert broker["open_breach_count"] == 1
    assert broker["registry_standing"] == "DELINQUENT"
    assert broker["request_open_count"] == 0
    assert broker["request_completed_count"] == 2


def _setup_failed_downstream_task() -> dict:
    """One executing request whose single downstream obligation has failed once."""
    ctx = setup_executing_deletion_request(recipient_count=1, clock=CLOCK_TEST_INSTANT)
    task = find_task(
        ctx["request_id"], ctx["broker_headers"], recipient_id=ctx["recipient_id"]
    )
    dispatch_task(task["id"], ctx["broker_headers"])
    fail_task(task["id"], ctx["broker_headers"], failure_code="RECIPIENT_UNREACHABLE")
    ctx["downstream_task_id"] = task["id"]
    return ctx


def test_a_failed_downstream_task_cannot_be_redispatched_while_its_recipient_is_suspended():
    """PRD §3.6: "Dispatch is allowed from `PENDING` and from `FAILED`, and when the task's `target_kind` is `DOWNSTREAM_RECIPIENT` the referenced recipient must be `ACTIVE`, or `ERR_RECIPIENT_NOT_ACTIVE` answers."
    PRD §3.6: "The task moves `DISPATCHED → FAILED` with the code stored; when `recipient_id` is not null the recipient's `fail_count` increments and its reliability is re-scored."
    PRD §3.6: "The raw score starts at 90.00, gains 2.00 for each `on_time_ack_count`, loses 5.00 for each `late_ack_count`, loses 20.00 for each `fail_count`, and loses 25.00 for each `waive_count`."
    PRD §3.6: "Auto-suspension is strict: a re-scored recipient whose `reliability_score` falls strictly below 70.00 while its `status` is `ACTIVE` is moved `ACTIVE → SUSPENDED`; a score of exactly 70.00 stays `ACTIVE`, and 69.99 suspends."
    PRD §3.6: "Suspension is allowed from `ACTIVE` and defers the recipient's open work: every task of that recipient whose `status` is `PENDING` or `DISPATCHED` moves to `DEFERRED` with `deferral_reason` set to `RECIPIENT_SUSPENDED`, and each deferral appends a `PROPAGATION_DEFERRED` audit event."
    PRD §3.6: "The owning request's `outstanding_task_count` does **not** change, because `FAILED` is still an outstanding status — the obligation has not gone away, it has merely failed once."

    Design: Difficulty/cross_entity_state_dependency/failed_downstream_task_redispatch_gated_on_recipient_being_active
    """
    ctx = _setup_failed_downstream_task()
    broker_headers = ctx["broker_headers"]

    recipient = fetch_recipient(ctx["recipient_id"], broker_headers)
    assert recipient["fail_count"] == 1
    assert_score_equals(recipient["reliability_score"], "70.00", "reliability_score")
    assert recipient["status"] == "ACTIVE"

    set_recipient_status(ctx["recipient_id"], "SUSPENDED", broker_headers)

    validate_error(
        api_client.dispatch_propagation_task(ctx["downstream_task_id"], broker_headers),
        ApiErrorId.ERR_RECIPIENT_NOT_ACTIVE,
        409,
    )

    task = fetch_propagation_task(ctx["downstream_task_id"], broker_headers)
    assert task["status"] == "FAILED"
    assert task["failure_code"] == "RECIPIENT_UNREACHABLE"
    assert task["dispatch_count"] == 1

    request = fetch_deletion_request(ctx["request_id"], broker_headers)
    assert request["status"] == "EXECUTING"
    assert request["outstanding_task_count"] == 3


def test_a_failed_downstream_task_redispatches_once_its_recipient_is_restored():
    """PRD §3.6: "Dispatch is allowed from `PENDING` and from `FAILED`, and when the task's `target_kind` is `DOWNSTREAM_RECIPIENT` the referenced recipient must be `ACTIVE`, or `ERR_RECIPIENT_NOT_ACTIVE` answers."
    PRD §3.6: "Restoration is allowed from `SUSPENDED` and additionally requires that the broker's `registry_standing` not be `SUSPENDED`, or `ERR_RECIPIENT_INVALID_STATE` answers — a broker in registry suspension cannot re-activate its data-sharing partners."
    PRD §3.6: "Dispatch sets `dispatched_at` to the current clock instant, increments `dispatch_count`, clears `failure_code` to null on the retry path from `FAILED`, and appends a `PROPAGATION_DISPATCHED` audit event."
    PRD §3.6: "The retry cycle is therefore `DISPATCHED → FAILED → DISPATCHED`, and `dispatch_count` accumulates across it."
    PRD §3.6: "Neither `DEFERRED` nor `FAILED` reduces `outstanding_task_count`; only the three terminal task statuses do."
    PRD §3.5: "`completion_ratio` is computed at the fork and is 0.0000, because nothing has been acknowledged yet."

    Design: Difficulty/cross_entity_state_dependency/failed_downstream_task_redispatch_gated_on_recipient_being_active
    """
    ctx = _setup_failed_downstream_task()
    broker_headers = ctx["broker_headers"]

    set_recipient_status(ctx["recipient_id"], "SUSPENDED", broker_headers)
    restored = set_recipient_status(ctx["recipient_id"], "ACTIVE", broker_headers)
    assert restored["status"] == "ACTIVE"

    validate_success(
        api_client.dispatch_propagation_task(ctx["downstream_task_id"], broker_headers)
    )

    task = fetch_propagation_task(ctx["downstream_task_id"], broker_headers)
    assert task["status"] == "DISPATCHED"
    assert task["dispatch_count"] == 2
    assert task["failure_code"] is None
    assert task["deferral_reason"] is None

    recipient = fetch_recipient(ctx["recipient_id"], broker_headers)
    assert recipient["status"] == "ACTIVE"
    assert recipient["fail_count"] == 1
    assert_score_equals(recipient["reliability_score"], "70.00", "reliability_score")

    request = fetch_deletion_request(ctx["request_id"], broker_headers)
    assert request["status"] == "EXECUTING"
    assert request["outstanding_task_count"] == 3
    assert_ratio_equals(request["completion_ratio"], "0.0000", "completion_ratio")
    assert_propagation_counters_conserved(request)


def _setup_waived_and_abandoned_obligations() -> dict:
    """Four obligations: two acknowledged, one failed then waived, one left for
    the recipient's termination to abandon."""
    ctx = setup_executing_deletion_request(
        recipient_count=1, derived_profile_count=2, clock=CLOCK_TEST_INSTANT
    )
    broker_headers = ctx["broker_headers"]

    dispatch_and_ack_task(
        ctx["tasks_by_kind"]["ACTIVE_DATABASE"]["id"], broker_headers
    )
    dispatch_and_ack_task(
        ctx["tasks_by_kind"]["DERIVED_DATASET"]["id"], broker_headers
    )

    archive = ctx["tasks_by_kind"]["BACKUP_ARCHIVE"]
    dispatch_task(archive["id"], broker_headers)
    fail_task(archive["id"], broker_headers, failure_code="LEGAL_HOLD")
    waive_task(archive["id"], broker_headers)
    ctx["waived_task_id"] = archive["id"]

    ctx["downstream_task_id"] = find_task(
        ctx["request_id"], broker_headers, recipient_id=ctx["recipient_id"]
    )["id"]
    return ctx


def test_propagation_counters_reconcile_across_a_waiver_and_an_abandonment():
    """PRD §2.7: "On a deletion request, `propagation_required_count` always equals `acked_task_count` plus `waived_task_count` plus `abandoned_task_count` plus `outstanding_task_count`, where the outstanding bucket covers tasks whose `status` is `PENDING`, `DISPATCHED`, `DEFERRED`, or `FAILED`."
    PRD §2.7: "Waiving a failed obligation is a compensating action and must never change `propagation_required_count` — it moves one unit from the outstanding bucket to the waived bucket."
    PRD §3.6: "Waiving never alters `propagation_required_count`: the obligation is still counted, it is merely discharged at half value."
    PRD §3.6: "Termination is allowed from `ACTIVE` and from `SUSPENDED`, is terminal, and abandons the recipient's remaining work: every task whose `status` is `PENDING`, `DISPATCHED`, `DEFERRED`, or `FAILED` moves to `ABANDONED`, each owning request's `abandoned_task_count` increases while `outstanding_task_count` decreases, each recomputes its `completion_ratio`, and each re-evaluates its join."
    PRD §3.5: "The request's counters are then set from the minted set: `propagation_required_count` is the number of internal targets plus the number of eligible recipients, `downstream_task_count` is the number of eligible recipients alone, and `outstanding_task_count` starts equal to `propagation_required_count`."
    PRD §3.5: "`DERIVED_DATASET` is included only when the consumer's `derived_profile_count` is greater than zero."

    Design: Difficulty/compensating_invariant/propagation_task_count_invariant_holds_across_waiver_and_abandonment
    """
    ctx = _setup_waived_and_abandoned_obligations()
    broker_headers = ctx["broker_headers"]

    set_recipient_status(ctx["recipient_id"], "TERMINATED", broker_headers)

    assert (
        fetch_propagation_task(ctx["waived_task_id"], broker_headers)["status"]
        == "WAIVED"
    )
    assert (
        fetch_propagation_task(ctx["downstream_task_id"], broker_headers)["status"]
        == "ABANDONED"
    )

    request = fetch_deletion_request(ctx["request_id"], broker_headers)
    assert request["propagation_required_count"] == 4
    assert request["acked_task_count"] == 2
    assert request["waived_task_count"] == 1
    assert request["abandoned_task_count"] == 1
    assert request["outstanding_task_count"] == 0
    assert request["downstream_task_count"] == 1
    assert_propagation_counters_conserved(request)


def test_half_credit_and_abandonment_close_the_request_as_partially_completed():
    """PRD §3.6: "The numerator is the sum of `weight` over tasks in `ACKED`, plus one half of the sum of `weight` over tasks in `WAIVED`."
    PRD §3.6: "The denominator is the sum of `weight` over **every** task of the request, with no status filter, so `ABANDONED` tasks remain in the denominator and contribute nothing to the numerator — which is precisely what makes the ratio fall when the sweep abandons work."
    PRD §3.6: "The ratio is rounded half up to four decimal places, and is 1.0000 by definition when the denominator is zero."
    PRD §3.6: "When it is below 1.0000 the request moves `EXECUTING → PARTIALLY_COMPLETED`, and `compliance_breach` is set true only when the ratio is strictly below 0.7500: a ratio of exactly 0.7500 is not a breach, while 0.7499 is."
    PRD §3.6: "When `compliance_breach` becomes true, the broker's `open_breach_count` increases by one and registry standing is re-derived, which forces `DELINQUENT` because a non-zero `open_breach_count` outranks the coverage clause."
    PRD §3.6: "The consumer's collection dimension moves `PURGE_PENDING → PURGED` and `last_purged_at` is set to the current clock instant."

    Design: Difficulty/compensating_invariant/propagation_task_count_invariant_holds_across_waiver_and_abandonment
    """
    ctx = _setup_waived_and_abandoned_obligations()
    broker_headers = ctx["broker_headers"]

    set_recipient_status(ctx["recipient_id"], "TERMINATED", broker_headers)

    request = fetch_deletion_request(ctx["request_id"], broker_headers)
    assert request["status"] == "PARTIALLY_COMPLETED"
    assert_ratio_equals(request["completion_ratio"], "0.7000", "completion_ratio")
    assert request["compliance_breach"] is True

    consumer = fetch_consumer(ctx["consumer_id"], broker_headers)
    assert consumer["collection_status"] == "PURGED"

    broker = fetch_broker(ctx["broker_id"], broker_headers)
    assert broker["open_breach_count"] == 1
    assert broker["registry_standing"] == "DELINQUENT"
