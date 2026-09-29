"""Compensating actions and the identities they must restore: payment reversal
against the obligation ledger, and report amendment against the departure
counters."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_departure_identity,
    assert_money,
    assert_obligation_identity,
    assert_period_balanced,
    assert_ratio,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PAYMENT_COMPUTED,
    PAYMENT_DISBURSED,
    PAYMENT_REVERSE,
    PAYMENT_REVERSED,
    PERIOD_CERTIFIED,
    PERIOD_PAID,
    PERIOD_REPORTED,
    REVERSAL_AUDIT_FINDING,
    REVERSAL_OVERPAYMENT,
    REVERSAL_REPORTING_ERROR,
)
from test_helpers.test_users import ADMIN, ADMIN_APPROVER, ADMIN_DISBURSER


# ─── payment_reversal_restores_the_obligation_identity ────────────────

def test_disbursement_and_reversal_both_preserve_the_obligation_identity(api: ApiClient):
    """Disbursing books the net payment against the ledger and reversing takes exactly the same amount back out.

    "Reversing a `DISBURSED` payment records the reason code, subtracts `net_payment_usd` back out of `disbursed_to_date_usd`, subtracts `hold_in_premium_usd` back out of `hold_in_premium_paid_usd`, recomputes `obligated_remaining_usd`, and moves the period `PAID → REPORTED`."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_the_obligation_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    assert_money(award.agreement["total_committed_usd"], 3200000.00, "total_committed_usd")

    month = fx.certified_month(api, award.agreement_id, award.carrier_id, "2026-08")
    payment = month["payment"]
    assert payment["status"] == PAYMENT_COMPUTED
    assert payment["variant_used"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert_money(payment["monthly_entitlement_usd"], 133333.33, "monthly_entitlement_usd")
    assert_money(payment["per_departure_rate_usd"], 1282.05, "per_departure_rate_usd")
    assert payment["credited_departures"] == 96
    assert_money(payment["gross_subsidy_usd"], 123076.80, "gross_subsidy_usd")
    assert_money(
        payment["cancellation_adjustment_usd"], 1923.08, "cancellation_adjustment_usd"
    )
    assert_money(payment["withholding_pct"], 0.05, "withholding_pct")
    assert_money(
        payment["performance_withholding_usd"], 6057.69, "performance_withholding_usd"
    )
    assert_money(payment["net_payment_usd"], 115096.03, "net_payment_usd")
    assert_money(payment["hold_in_premium_usd"], 0.00, "hold_in_premium_usd")
    assert_money(payment["total_disbursement_usd"], 115096.03, "total_disbursement_usd")

    fx.approve_payment(api, payment["id"])
    disbursed = fx.disburse_payment(api, payment["id"])
    assert disbursed["status"] == PAYMENT_DISBURSED

    booked = award.reload()
    assert_money(booked["disbursed_to_date_usd"], 115096.03, "disbursed_to_date_usd")
    assert_money(
        booked["obligated_remaining_usd"], 3084903.97, "obligated_remaining_usd"
    )
    assert_money(booked["hold_in_premium_paid_usd"], 0.00, "hold_in_premium_paid_usd")
    assert_obligation_identity(booked)
    assert (
        validate_success(api.get_service_period(month["period"]["id"], ADMIN))["status"]
        == PERIOD_PAID
    )

    reversed_payment = validate_success(
        api.payment_action(
            payment["id"],
            f.payment_action_payload(
                PAYMENT_REVERSE, reversal_reason_code=REVERSAL_AUDIT_FINDING
            ),
            ADMIN,
        )
    )
    assert reversed_payment["status"] == PAYMENT_REVERSED
    assert reversed_payment["reversal_reason_code"] == REVERSAL_AUDIT_FINDING
    assert_money(reversed_payment["net_payment_usd"], 115096.03, "net_payment_usd")

    restored = award.reload()
    assert_money(restored["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_money(
        restored["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )
    assert_money(restored["hold_in_premium_paid_usd"], 0.00, "hold_in_premium_paid_usd")
    assert_obligation_identity(restored)
    assert restored["cumulative_scheduled_departures"] == 104
    assert restored["cumulative_completed_departures"] == 91
    assert_departure_identity(restored)

    period = validate_success(api.get_service_period(month["period"]["id"], ADMIN))
    assert period["status"] == PERIOD_REPORTED


def test_second_reversal_is_refused_without_double_crediting_the_ledger(api: ApiClient):
    """REVERSED is terminal, so a replayed reversal is refused and cannot credit the obligation twice.

    "A payment may be reversed from either `APPROVED` or `DISBURSED`; from any other status the refusal is `ERR_PAYMENT_NOT_REVERSIBLE`, and `REVERSED` is terminal."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_the_obligation_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    month = fx.settled_month(api, award.agreement_id, award.carrier_id, "2026-08")
    payment = month["payment"]
    assert payment["status"] == PAYMENT_DISBURSED

    validate_success(
        api.payment_action(
            payment["id"],
            f.payment_action_payload(
                PAYMENT_REVERSE, reversal_reason_code=REVERSAL_OVERPAYMENT
            ),
            ADMIN,
        )
    )
    once = award.reload()
    assert_money(once["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_money(once["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd")

    replay = api.payment_action(
        payment["id"],
        f.payment_action_payload(
            PAYMENT_REVERSE, reversal_reason_code=REVERSAL_OVERPAYMENT
        ),
        ADMIN,
    )
    validate_error(replay, E.ERR_PAYMENT_NOT_REVERSIBLE, 409)

    twice = award.reload()
    assert_money(twice["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_money(twice["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd")
    assert_obligation_identity(twice)

    still_reversed = validate_success(api.get_subsidy_payment(payment["id"], ADMIN))
    assert still_reversed["status"] == PAYMENT_REVERSED

    period = validate_success(api.get_service_period(month["period"]["id"], ADMIN))
    assert period["status"] == PERIOD_REPORTED


def test_recertifying_the_reversed_month_reproduces_the_identical_net_payment(
    api: ApiClient,
):
    """A reversed month lands back in REPORTED and certifying it afresh recomputes the very same net payment.

    "Certification creates a subsidy payment in `COMPUTED` status, bound to the certified period through `service_period_id`, and records in `variant_used` which of the two payment bases was in force on the agreement at that moment."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_the_obligation_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    month = fx.settled_month(api, award.agreement_id, award.carrier_id, "2026-08")
    period_id = month["period"]["id"]

    validate_success(
        api.payment_action(
            month["payment"]["id"],
            f.payment_action_payload(
                PAYMENT_REVERSE, reversal_reason_code=REVERSAL_REPORTING_ERROR
            ),
            ADMIN,
        )
    )

    recertified = fx.certify_period(api, period_id)
    assert recertified["status"] == PERIOD_CERTIFIED

    rows, _meta = validate_paginated(
        api.list_subsidy_payments(ADMIN, {"service_period_id": period_id})
    )
    assert len(rows) == 2
    statuses = sorted(row["status"] for row in rows)
    assert statuses == [PAYMENT_COMPUTED, PAYMENT_REVERSED]

    fresh = [row for row in rows if row["status"] == PAYMENT_COMPUTED][0]
    assert_money(fresh["net_payment_usd"], 115096.03, "net_payment_usd")
    assert_money(fresh["gross_subsidy_usd"], 123076.80, "gross_subsidy_usd")
    assert fresh["credited_departures"] == 96

    fx.approve_payment(api, fresh["id"], headers=ADMIN_APPROVER)
    fx.disburse_payment(api, fresh["id"], headers=ADMIN_DISBURSER)

    settled = award.reload()
    assert_money(settled["disbursed_to_date_usd"], 115096.03, "disbursed_to_date_usd")
    assert_money(
        settled["obligated_remaining_usd"], 3084903.97, "obligated_remaining_usd"
    )
    assert_obligation_identity(settled)


# ─── period_amendment_preserves_the_departure_identity ────────────────

def test_amendment_rebases_the_cumulative_departure_counters(api: ApiClient):
    """An amendment subtracts the month's old counts before adding the new ones, so the cumulative counters are re-based rather than doubled.

    "An accepted amendment increases `amendment_count` by 1, rewrites `period_completion_factor` from the new figures, and re-bases the agreement by first subtracting the period's previously stored four counts from the four cumulative counters and then adding the four new ones — never by adding alone."

    Design: Difficulty/compensating_invariant/period_amendment_preserves_the_departure_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")
    assert_ratio(period["period_completion_factor"], 0.8750, "period_completion_factor")

    before = award.reload()
    assert before["cumulative_scheduled_departures"] == 104
    assert before["cumulative_completed_departures"] == 91
    assert before["cumulative_cancelled_carrier_departures"] == 5
    assert before["cumulative_cancelled_weather_departures"] == 8

    amended = validate_success(
        api.amend_service_period(
            period["id"],
            f.amend_payload(
                before["version"],
                scheduled_departures=104,
                completed_departures=96,
                cancelled_carrier_departures=2,
                cancelled_weather_departures=6,
                seats_offered=1729,
                passengers_enplaned=620,
            ),
            award.carrier_headers,
        )
    )
    assert amended["status"] == PERIOD_REPORTED
    assert amended["amendment_count"] == 1
    assert_period_balanced(amended)
    assert_ratio(amended["period_completion_factor"], 0.9231, "period_completion_factor")

    after = award.reload()
    assert after["cumulative_scheduled_departures"] == 104
    assert after["cumulative_completed_departures"] == 96
    assert after["cumulative_cancelled_carrier_departures"] == 2
    assert after["cumulative_cancelled_weather_departures"] == 6
    assert after["version"] == before["version"] + 1
    assert_departure_identity(after)


def test_replayed_amendment_on_a_stale_agreement_version_is_refused(api: ApiClient):
    """Replaying an amendment with the version it already consumed is refused, so the re-base cannot be applied twice.

    "The amendment carries `expected_agreement_version` and is rejected with `ERR_STALE_VERSION` when it does not match the agreement's current `version`."

    Design: Difficulty/compensating_invariant/period_amendment_preserves_the_departure_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")
    stale_version = award.reload()["version"]

    amendment = f.amend_payload(
        stale_version,
        scheduled_departures=104,
        completed_departures=96,
        cancelled_carrier_departures=2,
        cancelled_weather_departures=6,
        seats_offered=1729,
        passengers_enplaned=620,
    )
    validate_success(
        api.amend_service_period(period["id"], amendment, award.carrier_headers)
    )

    replay = api.amend_service_period(period["id"], amendment, award.carrier_headers)
    validate_error(replay, E.ERR_STALE_VERSION, 412)

    agreement = award.reload()
    assert agreement["cumulative_scheduled_departures"] == 104
    assert agreement["cumulative_completed_departures"] == 96
    assert agreement["cumulative_cancelled_carrier_departures"] == 2
    assert agreement["cumulative_cancelled_weather_departures"] == 6
    assert agreement["version"] == stale_version + 1
    assert_departure_identity(agreement)

    reread = validate_success(api.get_service_period(period["id"], ADMIN))
    assert reread["amendment_count"] == 1


def test_unbalanced_amendment_is_refused_and_leaves_the_counters_rebased_once(
    api: ApiClient,
):
    """An amendment whose four counts do not add up is refused outright and touches neither the period nor the cumulative counters.

    "The completed departures plus the carrier-controllable cancellations plus the weather cancellations must add up to exactly the scheduled departures, and the passengers enplaned may not exceed the seats offered; either failure is refused with `ERR_DEPARTURE_COUNTS_UNBALANCED`."

    Design: Difficulty/compensating_invariant/period_amendment_preserves_the_departure_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")

    validate_success(
        api.amend_service_period(
            period["id"],
            f.amend_payload(
                award.reload()["version"],
                scheduled_departures=104,
                completed_departures=96,
                cancelled_carrier_departures=2,
                cancelled_weather_departures=6,
                seats_offered=1729,
                passengers_enplaned=620,
            ),
            award.carrier_headers,
        )
    )
    current_version = award.reload()["version"]

    unbalanced = api.amend_service_period(
        period["id"],
        f.amend_payload(
            current_version,
            scheduled_departures=104,
            completed_departures=90,
            cancelled_carrier_departures=5,
            cancelled_weather_departures=8,
            seats_offered=1729,
            passengers_enplaned=620,
        ),
        award.carrier_headers,
    )
    validate_error(unbalanced, E.ERR_DEPARTURE_COUNTS_UNBALANCED, 422)

    agreement = award.reload()
    assert agreement["cumulative_scheduled_departures"] == 104
    assert agreement["cumulative_completed_departures"] == 96
    assert agreement["cumulative_cancelled_carrier_departures"] == 2
    assert agreement["cumulative_cancelled_weather_departures"] == 6
    assert agreement["version"] == current_version
    assert_departure_identity(agreement)

    reread = validate_success(api.get_service_period(period["id"], ADMIN))
    assert reread["amendment_count"] == 1
    assert reread["completed_departures"] == 96


def test_amending_one_month_leaves_the_other_month_contribution_intact(api: ApiClient):
    """Re-basing September's counts removes only September's old contribution, leaving August's untouched.

    "It also increases the agreement's `version` by 1, which is precisely why the next amendment must re-read the agreement first."

    Design: Difficulty/compensating_invariant/period_amendment_preserves_the_departure_identity
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    august = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")
    september = fx.reported_period(
        api,
        award.agreement_id,
        award.carrier_id,
        "2026-09",
        scheduled_departures=100,
        completed_departures=95,
        cancelled_carrier_departures=3,
        cancelled_weather_departures=2,
        seats_offered=1600,
        passengers_enplaned=600,
    )

    both = award.reload()
    assert both["cumulative_scheduled_departures"] == 204
    assert both["cumulative_completed_departures"] == 186
    assert both["cumulative_cancelled_carrier_departures"] == 8
    assert both["cumulative_cancelled_weather_departures"] == 10
    assert_departure_identity(both)

    amended = validate_success(
        api.amend_service_period(
            september["id"],
            f.amend_payload(
                both["version"],
                scheduled_departures=100,
                completed_departures=90,
                cancelled_carrier_departures=8,
                cancelled_weather_departures=2,
                seats_offered=1600,
                passengers_enplaned=600,
            ),
            award.carrier_headers,
        )
    )
    assert amended["amendment_count"] == 1
    assert_ratio(amended["period_completion_factor"], 0.9000, "period_completion_factor")

    after = award.reload()
    assert after["cumulative_scheduled_departures"] == 204
    assert after["cumulative_completed_departures"] == 181
    assert after["cumulative_cancelled_carrier_departures"] == 13
    assert after["cumulative_cancelled_weather_departures"] == 10
    assert_departure_identity(after)

    unchanged = validate_success(api.get_service_period(august["id"], ADMIN))
    assert unchanged["amendment_count"] == 0
    assert unchanged["completed_departures"] == 91
    assert_ratio(
        unchanged["period_completion_factor"], 0.8750, "period_completion_factor"
    )
