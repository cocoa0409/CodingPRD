"""The fee ledger, the append-only audit trail, and the deferred-action sweep.

Every test builds its own estate from scratch: the harness restarts the API and
wipes the database before each test function.
"""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    add_disclosures,
    api_client,
    assert_audit_event,
    assert_audit_trail_sequenced,
    assert_broker_ledger_conserved,
    assert_cents_equals,
    assert_instant_equals,
    fetch_broker,
    fetch_registration,
    get_success_data,
    make_platform_admin_headers,
    make_regulator_headers,
    onboard_broker,
    open_draft_registration,
    record_consumer,
    run_sweep,
    set_clock,
    setup_accepted_registration,
    submit_registration,
    validate_paginated,
    validate_success,
)

CLOCK = CLOCK_TEST_INSTANT
COVERAGE_END = "2027-03-01T00:00:00Z"
PROVISIONAL_FEE_CENTS = 47000
FINAL_FEE_CENTS = 23307
PLATFORM_ADMIN = make_platform_admin_headers()


def _deposit(broker_id: str, amount_cents: int, headers) -> dict:
    """Credit the filing-fee account and return the updated broker record."""
    return get_success_data(
        api_client.create_fee_deposit(
            broker_id, {"amount_cents": amount_cents}, headers
        )
    )


def _audit_page(broker_id: str, headers, **params):
    """One page of the broker's trail as (events, meta)."""
    return validate_paginated(
        api_client.list_audit_events(broker_id, headers, params=params or None)
    )


def _audit_total(broker_id: str, headers, **params) -> int:
    _, meta = _audit_page(broker_id, headers, **params)
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Fee deposits accumulate into the uncommitted half of the ledger
# ---------------------------------------------------------------------------


def test_fee_deposits_accumulate_into_the_credit_balance():
    """PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."
    PRD §2.7: "`fee_deposited_cents` always equals `fee_paid_cents` plus
    `fee_credit_cents`"
    PRD §3.1: "Because it holds no accepted filing anywhere yet, its
    `registry_standing` is initialised to `DELINQUENT` and its `delinquent_since` is
    set to the enrolment instant, which is also its `created_at`."

    Design: Corner/endpoints/fee_deposits_accumulate_and_bump_the_broker_version
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK)
    broker_id = ctx["broker_id"]
    broker_headers = ctx["broker_headers"]

    after_first = _deposit(broker_id, 500000, broker_headers)
    after_second = _deposit(broker_id, 250000, PLATFORM_ADMIN)

    assert_cents_equals(after_first["fee_credit_cents"], 500000, "fee_credit_cents")
    assert_cents_equals(after_second["fee_credit_cents"], 750000, "fee_credit_cents")

    broker = fetch_broker(broker_id, broker_headers)
    assert_cents_equals(broker["fee_deposited_cents"], 750000, "fee_deposited_cents")
    assert_cents_equals(broker["fee_paid_cents"], 0, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 750000, "fee_credit_cents")
    assert_broker_ledger_conserved(broker)
    assert broker["registry_standing"] == "DELINQUENT"


def test_each_fee_deposit_bumps_the_broker_version_and_appends_an_event():
    """PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"
    PRD §2.4: "Whenever the server changes any stored field of a resource, that
    resource's `updated_at` moves to the current clock instant and its `version`
    increases by one."
    PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."

    Design: Corner/endpoints/fee_deposits_accumulate_and_bump_the_broker_version
    """
    ctx = onboard_broker(deposit_cents=0, clock=CLOCK)
    broker_id = ctx["broker_id"]
    broker_headers = ctx["broker_headers"]
    assert ctx["broker"]["version"] == 1

    _deposit(broker_id, 500000, broker_headers)
    _deposit(broker_id, 250000, PLATFORM_ADMIN)

    broker = fetch_broker(broker_id, broker_headers)
    assert broker["version"] == 3
    assert_instant_equals(broker["updated_at"], CLOCK, "updated_at")
    assert _audit_total(broker_id, broker_headers, event_type="FEE_DEPOSITED") == 2


# ---------------------------------------------------------------------------
# Reading the append-only trail: filters, sequence order and pagination meta
# ---------------------------------------------------------------------------


def _broker_with_three_trail_entries() -> dict:
    """A broker whose trail holds exactly BROKER_REGISTERED, FEE_DEPOSITED and
    CONSUMER_RECORDED, in that order."""
    ctx = onboard_broker(clock=CLOCK, deposit_cents=500000)
    consumer = record_consumer(ctx["broker_id"])
    ctx["consumer"] = consumer
    ctx["consumer_id"] = consumer["id"]
    return ctx


def test_audit_trail_filtered_by_event_type_returns_the_single_matching_row():
    """PRD §2.10: "A broker's trail is readable in ascending `sequence_no` order and
    may be narrowed by `event_type`, by `subject_kind`, or by `subject_id`."
    PRD §2.10: "a `sequence_no` that is a per-broker monotonic counter starting at 1"
    PRD §2.10: "a `subject_kind` naming the entity family the event is about, a
    `subject_id` identifying the specific instance"
    PRD §3.1: "The enrolment appends a `BROKER_REGISTERED` audit event, which is
    therefore always sequence number 1 on that broker's trail."

    Design: Corner/endpoints/audit_event_listing_filters_by_event_type_and_subject
    """
    ctx = _broker_with_three_trail_entries()

    events, meta = _audit_page(
        ctx["broker_id"], make_regulator_headers(), event_type="CONSUMER_RECORDED"
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(events) == 1
    assert_audit_event(events[0])
    assert events[0]["event_type"] == "CONSUMER_RECORDED"
    assert events[0]["sequence_no"] == 3
    assert events[0]["subject_kind"] == "CONSUMER"
    assert events[0]["subject_id"] == ctx["consumer_id"]


def test_audit_trail_filtered_by_subject_returns_the_consumer_recorded_row():
    """PRD §2.10: "A broker's trail is readable in ascending `sequence_no` order and
    may be narrowed by `event_type`, by `subject_kind`, or by `subject_id`."
    PRD §3.3: "Creation also sets `opt_out_sale` and `opt_out_sharing` to false and
    `last_purged_at` to null, and appends a `CONSUMER_RECORDED` audit event."

    Design: Corner/endpoints/audit_event_listing_filters_by_event_type_and_subject
    """
    ctx = _broker_with_three_trail_entries()

    events, meta = _audit_page(
        ctx["broker_id"],
        make_regulator_headers(),
        subject_kind="CONSUMER",
        subject_id=ctx["consumer_id"],
    )

    assert meta["total_count"] == 1
    assert len(events) == 1
    assert events[0]["event_type"] == "CONSUMER_RECORDED"
    assert events[0]["subject_id"] == ctx["consumer_id"]


def test_audit_trail_pages_in_sequence_order_with_pagination_meta():
    """PRD §2.3: "The one endpoint that names a different key is the broker's audit
    trail, which is returned in ascending `sequence_no` order"
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts
    every record matching the applied filters before the page window is applied,
    and `has_more` states whether any record remains beyond the current window."
    PRD §3.1: "The enrolment appends a `BROKER_REGISTERED` audit event, which is
    therefore always sequence number 1 on that broker's trail."

    Design: Corner/endpoints/audit_event_listing_filters_by_event_type_and_subject
    """
    ctx = _broker_with_three_trail_entries()
    regulator = make_regulator_headers()

    first_page, first_meta = _audit_page(ctx["broker_id"], regulator, limit=2, offset=0)

    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_page) == 2
    assert_audit_trail_sequenced(first_page)
    assert first_page[0]["event_type"] == "BROKER_REGISTERED"
    assert first_page[0]["sequence_no"] == 1
    assert first_page[1]["event_type"] == "FEE_DEPOSITED"

    second_page, second_meta = _audit_page(
        ctx["broker_id"], regulator, limit=2, offset=2
    )

    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_page) == 1
    assert second_page[0]["event_type"] == "CONSUMER_RECORDED"


# ---------------------------------------------------------------------------
# The deferred-action sweep: a quiet run, an expiry run, and an idempotent rerun
# ---------------------------------------------------------------------------

SWEEP_COUNTERS = (
    "expired_registration_count",
    "expired_suppression_count",
    "abandoned_task_count",
    "honored_signal_count",
    "escalated_inquiry_count",
)


def _assert_every_counter_zero(summary: dict):
    for counter in SWEEP_COUNTERS:
        assert summary[counter] == 0, f"expected {counter} 0, got {summary[counter]}"


def test_sweep_at_a_quiet_instant_reports_every_counter_at_zero():
    """PRD §3.9: "The sweep answers with a summary of what it did: `swept_at` carrying
    the clock instant the sweep ran at, `expired_registration_count` from step 1,
    `expired_suppression_count` from step 2, `abandoned_task_count` from step 3,
    `honored_signal_count` from step 4, and `escalated_inquiry_count` from step 5."
    PRD §3.9: "Each counter counts only the rows that step actually moved, so a second
    sweep at the same clock instant reports all zeros."
    PRD §3.2: "`accepted_at` is set to the current clock instant, the standing
    derivation of §3.1 re-runs for the broker — a changed value appends a
    `STANDING_CHANGED` event and, when the new value is `COMPLIANT`, clears
    `delinquent_since` to null — and a `REGISTRATION_ACCEPTED` audit event is
    appended."

    Design: Corner/endpoints/compliance_sweep_expires_a_lapsed_filing_then_finds_nothing_on_rerun
    """
    ctx = setup_accepted_registration(clock=CLOCK)

    before = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert before["registry_standing"] == "COMPLIANT"
    assert before["delinquent_since"] is None

    summary = run_sweep()

    assert_instant_equals(summary["swept_at"], CLOCK, "swept_at")
    _assert_every_counter_zero(summary)
    assert fetch_registration(ctx["registration_id"], ctx["broker_headers"])[
        "status"
    ] == "ACCEPTED"


def test_sweep_expires_the_lapsed_filing_and_a_rerun_finds_nothing():
    """PRD §3.9: "**Step 1** expires filings: every `ACCEPTED` registration whose
    `coverage_period_end` is at or before the clock moves `ACCEPTED → EXPIRED`, its
    `charged_fee_cents` is zeroed, and a `REGISTRATION_EXPIRED` audit event is
    appended."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or before
    the current clock instant while its `coverage_period_end` is strictly after it,
    the standing is `COMPLIANT`."
    PRD §3.1: "On a transition into `DELINQUENT` or `SUSPENDED` from `COMPLIANT`,
    `delinquent_since` is set to the current clock instant."
    PRD §3.9: "Each counter counts only the rows that step actually moved, so a second
    sweep at the same clock instant reports all zeros."

    Design: Corner/endpoints/compliance_sweep_expires_a_lapsed_filing_then_finds_nothing_on_rerun
    """
    ctx = setup_accepted_registration(clock=CLOCK)
    broker_id = ctx["broker_id"]
    broker_headers = ctx["broker_headers"]

    run_sweep()
    set_clock(COVERAGE_END)
    live = run_sweep()

    assert_instant_equals(live["swept_at"], COVERAGE_END, "swept_at")
    assert live["expired_registration_count"] == 1

    registration = fetch_registration(ctx["registration_id"], broker_headers)
    assert registration["status"] == "EXPIRED"

    broker = fetch_broker(broker_id, broker_headers)
    assert broker["registry_standing"] == "DELINQUENT"
    assert_instant_equals(broker["delinquent_since"], COVERAGE_END, "delinquent_since")

    assert _audit_total(broker_id, broker_headers, event_type="REGISTRATION_EXPIRED") == 1
    assert _audit_total(broker_id, broker_headers, event_type="STANDING_CHANGED") == 2

    rerun = run_sweep()

    _assert_every_counter_zero(rerun)
    assert_instant_equals(rerun["swept_at"], COVERAGE_END, "swept_at")
    assert _audit_total(broker_id, broker_headers, event_type="REGISTRATION_EXPIRED") == 1


# ---------------------------------------------------------------------------
# Acceptance settles the fee inside the accepting request
# ---------------------------------------------------------------------------


def _submitted_filing() -> dict:
    """A funded broker with one SUBMITTED CA filing charged the provisional fee."""
    ctx = onboard_broker(clock=CLOCK, deposit_cents=500000)
    registration = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code="CA",
        coverage_period_start=CLOCK,
        coverage_period_end=COVERAGE_END,
    )
    add_disclosures(registration["id"], ctx["broker_headers"])
    ctx["registration"] = submit_registration(registration["id"], ctx["broker_headers"])
    ctx["registration_id"] = registration["id"]
    return ctx


def test_accept_response_body_already_carries_the_settled_fee():
    """PRD §3.2: "Both `provisional_filing_fee_cents` and `charged_fee_cents` are set
    to that amount, `fee_credit_cents` decreases by it while `fee_paid_cents`
    increases by the same amount (`fee_deposited_cents` does not move),
    `submitted_at` is set to the current clock instant, the parent broker's `version`
    increases by one, and a `REGISTRATION_SUBMITTED` audit event is appended."
    PRD §3.2: "On success, `final_filing_fee_cents` is set to the computed amount and
    `charged_fee_cents` is reset to it."
    PRD §2.8: "each link runs to completion inside the request that triggered the
    first link, in the order the workflow narrative in §3 gives, before the response
    is written."

    Design: Corner/consistency_model/acceptance_effects_are_visible_in_the_same_response
    """
    ctx = _submitted_filing()
    assert_cents_equals(
        ctx["registration"]["charged_fee_cents"],
        PROVISIONAL_FEE_CENTS,
        "charged_fee_cents",
    )

    accepted = validate_success(
        api_client.accept_registration(ctx["registration_id"], PLATFORM_ADMIN), 200
    )

    assert accepted["status"] == "ACCEPTED"
    assert_cents_equals(
        accepted["charged_fee_cents"], FINAL_FEE_CENTS, "charged_fee_cents"
    )
    assert_cents_equals(
        accepted["final_filing_fee_cents"], FINAL_FEE_CENTS, "final_filing_fee_cents"
    )


def test_the_read_after_acceptance_agrees_with_the_settled_ledger_and_standing():
    """PRD §3.2: "The settlement delta is the final fee minus the provisional fee:
    when that delta is negative, the broker's `fee_paid_cents` decreases by its
    magnitude and `fee_credit_cents` increases by the same magnitude (the over-charge
    is refunded to credit); when it is positive, the movement runs the other way,
    from credit into paid."
    PRD §3.2: "`fee_deposited_cents` never changes during settlement."
    PRD §3.1: "Third: if every code in `operating_state_codes` has at least one
    registration of this broker with a matching `state_code`, a `status` of
    `ACCEPTED`, and a coverage period whose `coverage_period_start` is at or before
    the current clock instant while its `coverage_period_end` is strictly after it,
    the standing is `COMPLIANT`."

    Design: Corner/consistency_model/acceptance_effects_are_visible_in_the_same_response
    """
    ctx = _submitted_filing()
    broker_id = ctx["broker_id"]

    validate_success(
        api_client.accept_registration(ctx["registration_id"], PLATFORM_ADMIN), 200
    )

    broker = fetch_broker(broker_id, PLATFORM_ADMIN)
    assert_cents_equals(broker["fee_paid_cents"], FINAL_FEE_CENTS, "fee_paid_cents")
    assert_cents_equals(broker["fee_credit_cents"], 476693, "fee_credit_cents")
    assert_cents_equals(broker["fee_deposited_cents"], 500000, "fee_deposited_cents")
    assert_broker_ledger_conserved(broker)
    assert broker["registry_standing"] == "COMPLIANT"
    assert broker["delinquent_since"] is None


def test_acceptance_appends_exactly_one_accepted_and_one_standing_event():
    """PRD §3.2: "`accepted_at` is set to the current clock instant, the standing
    derivation of §3.1 re-runs for the broker — a changed value appends a
    `STANDING_CHANGED` event and, when the new value is `COMPLIANT`, clears
    `delinquent_since` to null — and a `REGISTRATION_ACCEPTED` audit event is
    appended."
    PRD §3.1: "When the derived value actually differs from the stored one, a
    `STANDING_CHANGED` audit event is appended; when it comes out the same, nothing
    is appended and no downstream cascade fires."

    Design: Corner/consistency_model/acceptance_effects_are_visible_in_the_same_response
    """
    ctx = _submitted_filing()
    broker_id = ctx["broker_id"]
    broker_headers = ctx["broker_headers"]

    validate_success(
        api_client.accept_registration(ctx["registration_id"], PLATFORM_ADMIN), 200
    )

    assert (
        _audit_total(broker_id, broker_headers, event_type="REGISTRATION_ACCEPTED") == 1
    )
    assert _audit_total(broker_id, broker_headers, event_type="STANDING_CHANGED") == 1
