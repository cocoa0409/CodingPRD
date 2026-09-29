"""Consistency corner: every derived figure is already settled in the write's own response."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_a_write_answers_with_its_own_derived_figures_and_the_ledgers_follow(client):
    """No second read is ever needed: the grade, the hold and the two ledgers settle at once.

    PRD 2.9: "Cascades in this system are always synchronous and always complete before
    the response is written; there is no eventual consistency and no background
    reconciliation job."

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    PRD 3.1: "Only the passing branch has consequences beyond the enrollment row: the
    course's `passed_count` rises by 1, the producer's `competency_codes` gains every
    code in that course's `grants_competency_codes`, the producer's
    `certification_level` is re-derived, and both the enrollment's `version` and the
    producer's `version` increment by 1."

    PRD 3.6: "A new reservation is created in `REQUESTED` status with `risk_bp`,
    `deposit_hold_cents`, `late_fee_cents`, `assessed_repair_cents`,
    `deposit_forfeited_cents`, `deposit_refunded_cents` and `uncovered_liability_cents`
    all at 0"

    PRD 3.6: "A successful confirmation freezes both `risk_bp` and `deposit_hold_cents`
    on the reservation — neither is ever recomputed afterwards, so a later suspension
    does not retroactively raise an existing hold — raises the producer's
    `deposit_held_cents` by the hold amount, raises the asset's `open_reservation_count`
    by 1, and increments the reservation's `version` by 1."

    PRD 3.6: "A clean comparison case, with no suspension points, a two-hour window and
    no live link, gives the base 12345 plus a duration line of 617, for a hold of 12962
    cents."

    PRD 2.9: "A producer's `deposit_held_cents` is the sum of `deposit_hold_cents` over
    that producer's reservations whose status is `CONFIRMED`, `CHECKED_OUT` or
    `DAMAGE_REVIEW`."

    Design: Corner/consistency_model/corner_immediate_consistency_derived_fields_in_same_response
    """
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    enrollment = fx.enroll(client, producer["id"], course["id"])
    fx.set_clock(client, "2026-08-06T00:00:00Z")
    fx.mark_attended(client, enrollment["id"], True)

    graded = fx.grade(client, enrollment["id"], 88)

    assert graded["status"] == "PASSED"
    assert graded["practical_score"] == 88
    settled_producer = fx.read_producer(client, producer["id"])
    assert settled_producer["certification_level"] == "BASIC"
    assert settled_producer["competency_codes"] == ["STUDIO_FLOOR"]
    a.assert_producer_counters(settled_producer, held=0)

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
    requested = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )

    assert requested["status"] == "REQUESTED"
    a.assert_cents(requested["deposit_hold_cents"], 0, "deposit_hold_cents")
    assert requested["risk_bp"] == 0
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=0)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 0

    confirmed = fx.confirm_reservation(client, requested["id"])

    assert confirmed["status"] == "CONFIRMED"
    a.assert_cents(confirmed["deposit_hold_cents"], 12962, "deposit_hold_cents")
    assert confirmed["risk_bp"] == 0

    producer_after = fx.read_producer(client, producer["id"])
    resource_after = fx.read_resource(client, resource["id"])

    a.assert_producer_counters(producer_after, held=12962)
    assert resource_after["open_reservation_count"] == 1

    assert fx.read_producer(client, producer["id"])["deposit_held_cents"] == producer_after[
        "deposit_held_cents"
    ]
    assert (
        fx.read_resource(client, resource["id"])["open_reservation_count"]
        == resource_after["open_reservation_count"]
    )
    a.assert_cents(
        fx.read_reservation(client, requested["id"])["deposit_hold_cents"],
        12962,
        "deposit_hold_cents",
    )
