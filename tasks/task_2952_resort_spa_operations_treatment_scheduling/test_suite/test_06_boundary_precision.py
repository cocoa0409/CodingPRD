"""Boundary precision: the inclusive 24-hour free-cancellation edge tested at
exactly the edge and one minute inside it, and the attachment-rate report tested
at a zero denominator and above one hundred percent.
"""

from test_helpers import (
    assert_folio_contents,
    assert_list_count,
    assert_percent_2dp,
    assert_same_instant,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import (
    CANON_ACTUAL_DURATION_MINUTES,
    CANON_GRATUITY_CENTS,
    CANON_RETAIL_AMOUNT_CENTS,
    CANON_START_AT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

FREE_EDGE_CLOCK = "2026-08-09T17:00:00.000Z"
LATE_EDGE_CLOCK = "2026-08-09T19:01:00.000Z"
LATE_CANCEL_CHARGE_CENTS = 29960


def _two_appointment_world():
    """One therapist, two HYDRO rooms and two CONFIRMED peak appointments —
    17:00Z in HYDRO-1 and 19:00Z in HYDRO-2 — with the clock exactly 24 hours
    before the first one starts."""
    world = fx.build_world(room_codes=("HYDRO-1", "HYDRO-2"))
    for key, code, start_at in (("a", "HYDRO-1", CANON_START_AT),
                                ("b", "HYDRO-2", "2026-08-10T19:00:00.000Z")):
        appointment = fx.book_appointment(
            world.guest_id, world.treatment_type_id, world.room_of(code),
            start_at, world.therapist_id)
        world.appointments[key] = fx.confirm(appointment["id"])
    fx.set_clock(FREE_EDGE_CLOCK)
    return world


def test_cancelling_at_exactly_twenty_four_hours_is_free_and_posts_nothing():
    """The inclusive edge: 24h00m out cancels for zero with no folio row at all.

    PRD §3.8: "When that figure is 24 hours or more — the boundary is inclusive —
    the appointment moves `REQUESTED → CANCELLED` or `CONFIRMED → CANCELLED`,
    `cancellation_charge_cents` is 0 and **no folio posting is made at all**."

    PRD §3.8: "On the free path the clearance dimension is left exactly as it
    stood — `clearance_status` and `clearance_block_reason` freeze at their current
    values rather than being reset — and nothing else happens."

    Design: Difficulty/boundary_precision_check/free_cancel_window_exact_24_hour_boundary
    """
    world = _two_appointment_world()

    cancelled = validate_success(api_client.cancel_appointment(
        world.appointments["a"]["id"], f.cancel_payload("flight change"),
        world.guest_headers))
    assert cancelled["schedule_status"] == "CANCELLED", (
        "the clock is exactly 24h00m before the 17:00Z start, so the inclusive "
        f"free band applies; got {cancelled['schedule_status']}")
    assert cancelled["cancellation_charge_cents"] == 0
    assert cancelled["clearance_status"] == "CLEARED", (
        "the free path freezes the clearance dimension where it stood")
    assert cancelled["clearance_block_reason"] is None

    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings after a free cancellation")
    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == 0
    assert guest["late_cancel_count"] == 0
    assert guest["booking_privilege"] == "OPEN"

    assert world.fetch_room("HYDRO-1")["booked_minutes_total"] == 0
    assert world.fetch_room("HYDRO-2")["booked_minutes_total"] == 120, (
        "the surviving appointment in the other room keeps its committed minutes")
    assert world.fetch_therapist()["assigned_minutes_total"] == 90


def test_cancelling_one_minute_inside_the_window_charges_the_uplifted_late_band():
    """23h59m out crosses into LATE_CANCELLED at 7,000 basis points.

    PRD §3.8: "The band rate is 5,000 basis points when the figure is 4 hours or
    more (again inclusive) and 10,000 basis points when it is under 4 hours, which
    includes every negative figure."

    PRD §3.8: "When the appointment's `high_demand_slot` is true, an uplift of
    2,000 basis points is added to whichever band was selected, and the resulting
    rate is then capped at 10,000 basis points — so a short-notice cancellation of
    a high-demand slot is charged the whole quote rather than 120 percent of it,
    while a late cancellation of a high-demand slot is charged 70 percent."

    Design: Difficulty/boundary_precision_check/free_cancel_window_exact_24_hour_boundary
    """
    world = _two_appointment_world()
    validate_success(api_client.cancel_appointment(
        world.appointments["a"]["id"], f.cancel_payload("flight change"),
        world.guest_headers))

    fx.set_clock(LATE_EDGE_CLOCK)
    late = validate_success(api_client.cancel_appointment(
        world.appointments["b"]["id"], f.cancel_payload("flight change"),
        world.guest_headers))
    assert late["schedule_status"] == "LATE_CANCELLED", (
        "23h59m before the 19:00Z start is one minute inside the free window, so "
        f"the late band applies; got {late['schedule_status']}")
    assert late["cancellation_charge_cents"] == LATE_CANCEL_CHARGE_CENTS, (
        "round_half_up(42800 * 7000 / 10000) with 5000 bp plus the 2000 bp "
        f"uplift: expected 29960, got {late['cancellation_charge_cents']}")

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings")
    assert_folio_contents(postings, [("LATE_CANCEL", LATE_CANCEL_CHARGE_CENTS)],
                          "guest folio")

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == LATE_CANCEL_CHARGE_CENTS
    assert guest["late_cancel_count"] == 1
    assert guest["booking_privilege"] == "OPEN", (
        "one late cancellation is below the restriction threshold of 2")

    assert world.fetch_room("HYDRO-1")["booked_minutes_total"] == 0
    assert world.fetch_room("HYDRO-2")["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


# ---------------------------------------------------------------------------
# The attachment-rate numeric boundaries
# ---------------------------------------------------------------------------

def _completed_world_with_two_purchases():
    """The canonical appointment completed at 105 minutes after two 4595c retail
    lines were recommended and purchased."""
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    appointment_id = world.appointments["a"]["id"]
    for sku in ("MARINE-SERUM-30", "MARINE-BALM-50"):
        attachment = validate_success(api_client.create_retail_attachment(
            appointment_id,
            f.retail_attachment_payload(
                product_sku=sku, amount_cents=CANON_RETAIL_AMOUNT_CENTS),
            world.therapist_headers), 201)
        validate_success(api_client.resolve_retail_attachment(
            attachment["id"], f.resolve_payload("PURCHASED"),
            world.guest_headers))
    fx.start_service(appointment_id, world.therapist_id)
    world.appointments["a"] = fx.complete_service(
        appointment_id, world.therapist_id, CANON_ACTUAL_DURATION_MINUTES,
        CANON_GRATUITY_CENTS)
    return world


def test_attach_rate_exceeds_one_hundred_percent_without_being_clamped():
    """Two purchases on one eligible appointment is a legal 200.00.

    PRD §3.10: "It is a per-appointment attachment ratio and is deliberately
    **not** capped at 100.00: two purchased products on a single completed
    appointment yield `200.00`."

    PRD §3.10: "`commission_cents` is computed per line and then summed — each
    attachment's `amount_cents` multiplied by 1,200 basis points, divided by ten
    thousand and rounded half up, with those per-line figures added together."

    Design: Difficulty/boundary_precision_check/retail_attach_rate_zero_denominator_and_above_one_hundred
    """
    _world = _completed_world_with_two_purchases()

    report = validate_success(api_client.get_retail_attachment_report(
        fx.DIRECTOR,
        params=f.report_window("2026-08-10T00:00:00.000Z",
                               "2026-08-11T00:00:00.000Z")))

    assert report["eligible_appointment_count"] == 1
    assert report["purchased_count"] == 2
    assert_percent_2dp(report["attach_rate_pct"], "attach_rate_pct")
    assert float(report["attach_rate_pct"]) == 200.00, (
        "2 purchases over 1 eligible appointment is 200.00 and must not be "
        f"clamped to 100.00; got {report['attach_rate_pct']}")
    assert report["purchased_amount_cents"] == 9190
    assert report["commission_cents"] == 1102, (
        "551 + 551 per line, not round_half_up(9190 * 1200 / 10000) = 1103; got "
        f"{report['commission_cents']}")
    assert_same_instant(report["from_at"], "2026-08-10T00:00:00.000Z", "from_at")
    assert_same_instant(report["to_at"], "2026-08-11T00:00:00.000Z", "to_at")


def test_attach_rate_short_circuits_a_zero_denominator_to_exactly_zero():
    """An empty window answers with a complete object, not an error or a null.

    PRD §3.10: "`attach_rate_pct` is exactly `0.00` when
    `eligible_appointment_count` is 0 — never an error — and is otherwise
    `purchased_count` multiplied by 100 and divided by `eligible_appointment_count`,
    rounded half up to two decimal places."

    PRD §3.10: "The response echoes `from_at` and `to_at` alongside the five
    figures."

    Design: Difficulty/boundary_precision_check/retail_attach_rate_zero_denominator_and_above_one_hundred
    """
    _world = _completed_world_with_two_purchases()

    report = validate_success(api_client.get_retail_attachment_report(
        fx.DIRECTOR,
        params=f.report_window("2026-08-01T00:00:00.000Z",
                               "2026-08-02T00:00:00.000Z")))

    for field in ("eligible_appointment_count", "purchased_count",
                  "attach_rate_pct", "purchased_amount_cents", "commission_cents",
                  "from_at", "to_at"):
        assert field in report and report[field] is not None, (
            f"the empty-window response must carry {field} rather than omitting "
            "it or nulling it")
    assert report["eligible_appointment_count"] == 0
    assert report["purchased_count"] == 0
    assert_percent_2dp(report["attach_rate_pct"], "attach_rate_pct")
    assert float(report["attach_rate_pct"]) == 0.00, (
        "the zero denominator is short-circuited to exactly 0.00; got "
        f"{report['attach_rate_pct']}")
    assert report["purchased_amount_cents"] == 0
    assert report["commission_cents"] == 0
    assert_same_instant(report["from_at"], "2026-08-01T00:00:00.000Z", "from_at")
    assert_same_instant(report["to_at"], "2026-08-02T00:00:00.000Z", "to_at")
