"""Compensating actions that must restore a conserved quantity exactly."""

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import USER_FINANCE, make_producer_headers


# ---------------------------------------------------------------------------
# The deposit ledger: cancelling a confirmed reservation reverses its hold
# ---------------------------------------------------------------------------
def _two_confirmed_holds_on_one_studio(client):
    """A producer carrying 25924 cents across two future studio bookings."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _res, first = fx.setup_confirmed_reservation(
        client, producer["id"], resource,
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    second = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-09T10:00:00Z", end_at="2026-08-09T12:00:00Z",
    )
    second = fx.confirm_reservation(client, second["id"])
    return producer, resource, first, second


def test_cancelling_a_confirmed_reservation_reverses_its_hold_in_full(client):
    """The reversal is recorded as a refund; the hold itself is kept for audit.

    PRD 3.6: "From `CONFIRMED` it is a compensating action:
    `deposit_refunded_cents` is set to the full `deposit_hold_cents`,
    `deposit_forfeited_cents` is set to 0 and `uncovered_liability_cents` is set
    to 0, while `deposit_hold_cents` itself is retained for audit rather than
    zeroed."

    PRD 3.6: "Cancellation is available to the producer or to a
    `FacilitiesManager` and requires a `cancellation_reason`."

    Design: Difficulty/compensating_invariant/cancelling_confirmed_reservation_restores_deposit_ledger
    """
    producer, _resource, first, second = _two_confirmed_holds_on_one_studio(client)
    a.assert_cents(first["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_cents(second["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=25924)

    cancelled = a.data_of(
        client.cancel_reservation(
            first["id"],
            f.reservation_cancel_payload(cancellation_reason="Producer rescheduled the shoot"),
            make_producer_headers(producer["id"]),
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "Producer rescheduled the shoot"
    a.assert_cents(cancelled["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_cents(cancelled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_cents(cancelled["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")
    a.assert_cents(cancelled["uncovered_liability_cents"], 0, "uncovered_liability_cents")


def test_the_deposit_ledger_falls_back_to_the_sum_over_the_surviving_hold(client):
    """The invariant is restored exactly, and the untouched booking does not drift.

    PRD 3.6: "The producer's `deposit_held_cents` falls by the hold amount,
    restoring the invariant that it sums the holds of `CONFIRMED`, `CHECKED_OUT`
    and `DAMAGE_REVIEW` reservations only; the asset's `open_reservation_count`
    falls by 1; and the reservation's `version` increments by 1."

    PRD 2.9: "A producer's `deposit_held_cents` is the sum of
    `deposit_hold_cents` over that producer's reservations whose status is
    `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`."

    Design: Difficulty/compensating_invariant/cancelling_confirmed_reservation_restores_deposit_ledger
    """
    producer, resource, first, second = _two_confirmed_holds_on_one_studio(client)

    a.data_of(
        client.cancel_reservation(
            first["id"],
            f.reservation_cancel_payload(cancellation_reason="Producer rescheduled the shoot"),
            make_producer_headers(producer["id"]),
        )
    )

    after = fx.read_producer(client, producer["id"])
    a.assert_producer_counters(after, held=12962, forfeited_total=0, suspension_points=0)
    assert after["status"] == "ACTIVE"

    survivor = fx.read_reservation(client, second["id"])
    assert survivor["status"] == "CONFIRMED"
    a.assert_cents(survivor["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_cents(survivor["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


# ---------------------------------------------------------------------------
# The suspension-point balance: a waiver forgives the repair, not the lateness
# ---------------------------------------------------------------------------
def _late_major_return_awaiting_a_waiver(client):
    """A reservation in DAMAGE_REVIEW returned 65 minutes late with MAJOR damage."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _res, reservation, assessment = fx.setup_reservation_in_damage_review(
        client,
        producer["id"],
        resource,
        start_at="2026-08-08T10:00:00Z",
        end_at="2026-08-08T12:00:00Z",
        checkout_at="2026-08-08T10:00:00Z",
        return_at="2026-08-08T13:05:00Z",
        severity="MAJOR",
        repair_estimate_cents=60000,
    )
    return producer, resource, reservation, assessment


def test_waiving_a_filed_assessment_conserves_the_suspension_point_balance(client):
    """The repair charge is forgiven, so the balance returns to its pre-damage value.

    PRD 3.7: "A waiver leaves `assessed_repair_cents` at 0 and
    `suspension_points_assessed` at 0, records `waived_by_user_id` and
    `waiver_reason`, and increments the assessment's `version` by 1."

    PRD 3.7: "The producer's `suspension_points` is unchanged and they never leave
    `ACTIVE` on this path."

    PRD 3.7: "It requires the assessment to be `FILED`, the reservation to be in
    `DAMAGE_REVIEW`, a `waiver_reason`, and an acting `X-User-ID` different from
    the assessment's `filed_by_user_id`; the same person filing and forgiving is
    refused with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Difficulty/compensating_invariant/waived_assessment_conserves_suspension_points_and_settles_late_fee_only
    """
    producer, _resource, _reservation, assessment = _late_major_return_awaiting_a_waiver(client)
    assert assessment["status"] == "FILED"
    assert assessment["severity"] == "MAJOR"
    a.assert_cents(assessment["repair_estimate_cents"], 60000, "repair_estimate_cents")

    waived = fx.waive_assessment(
        client,
        assessment["id"],
        waiver_reason="Bend predated the checkout per archived condition photos",
    )

    assert waived["status"] == "WAIVED"
    a.assert_cents(waived["assessed_repair_cents"], 0, "assessed_repair_cents")
    assert waived["suspension_points_assessed"] == 0
    assert waived["waived_by_user_id"] == USER_FINANCE
    assert waived["waiver_reason"] == "Bend predated the checkout per archived condition photos"

    unpunished = fx.read_producer(client, producer["id"])
    a.assert_producer_counters(unpunished, suspension_points=0)
    assert unpunished["status"] == "ACTIVE"
    assert unpunished["certification_level"] == "BASIC"


def test_the_independent_late_fee_still_settles_and_the_deposit_is_conserved(client):
    """Forgiving the repair does not forgive the lateness, and the split stays exact.

    PRD 3.7: "The reservation still reaches `SETTLED` through the same join
    point, but with an assessed repair of 0, so only the late fee can be
    forfeited; the producer's `deposit_held_cents` falls,
    `deposit_forfeited_total_cents` rises by that late-fee forfeiture, and the
    asset's `open_reservation_count` falls by 1."

    PRD 3.6: "On a hold of 12962 cents returned one hour and five minutes late
    against a base deposit of 12345 with no damage, the per-hour fee is 926, the
    late fee is 1852, the forfeiture is 1852, the refund is 11110 and the
    uncovered liability is 0."

    PRD 3.6: "Two identities therefore hold on every settled reservation: the
    hold always equals the forfeited amount plus the refunded amount, and the
    forfeited amount plus the uncovered liability always equals the late fee plus
    the assessed repair."

    Design: Difficulty/compensating_invariant/waived_assessment_conserves_suspension_points_and_settles_late_fee_only
    """
    producer, resource, reservation, assessment = _late_major_return_awaiting_a_waiver(client)

    fx.waive_assessment(
        client,
        assessment["id"],
        waiver_reason="Bend predated the checkout per archived condition photos",
    )

    settled = fx.read_reservation(client, reservation["id"])
    assert settled["status"] == "SETTLED"
    a.assert_instant_equals(settled["returned_at"], "2026-08-08T13:05:00Z", "returned_at")
    a.assert_cents(settled["assessed_repair_cents"], 0, "assessed_repair_cents")
    a.assert_cents(settled["late_fee_cents"], 1852, "late_fee_cents")
    a.assert_cents(settled["deposit_forfeited_cents"], 1852, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 11110, "deposit_refunded_cents")
    a.assert_cents(settled["uncovered_liability_cents"], 0, "uncovered_liability_cents")
    a.assert_settlement_identities(settled)

    a.assert_producer_counters(
        fx.read_producer(client, producer["id"]), held=0, forfeited_total=1852
    )
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 0
