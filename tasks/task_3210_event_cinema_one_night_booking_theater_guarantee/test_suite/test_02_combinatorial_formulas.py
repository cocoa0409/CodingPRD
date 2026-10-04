"""Combinatorial formulas: the tiered make-good credit and its pinned aggregation order."""
import pytest
from test_helpers import (
    validate_success, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, first_screening, list_screenings, report_screening,
    get_line, make_theater_headers, make_distributor_headers,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def _makegood_scene(outage_minutes=10, attendance=100, showtimes=1,
                    duration_minutes=90, seats_total=60, ticket_price_cents=1500):
    """Confirmed booking with one reported-incomplete screening per showtime.

    The seat cap is seats_total x price x 0.5; the runtime that the lost fraction
    divides by is the title's duration_minutes.
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=400)
    theater = create_theater(circuit["id"], seats_total=seats_total,
                             screen_count=2)
    title = create_title(distributor["id"], content_type="LIVE_BROADCAST",
                         is_live=True, duration_minutes=duration_minutes,
                         ticket_price_cents=ticket_price_cents,
                         max_screen_commitment=40,
                         rights_end_utc="2027-03-01T00:00:00Z")
    plan = [{"index": i + 1, "date_utc": f"2026-12-0{i + 1}T00:00:00Z",
             "start_minute_utc": 1140, "auditorium": "AUD-1"}
            for i in range(showtimes)]
    booking = create_booking(title["id"], circuit["id"], showtime_count=showtimes,
                             showtime_plan=plan, guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=40,
                    expected_attendance=attendance)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(booking["id"])
    event = get_success_data(api_client.create_feed_event({
        "booking_id": booking["id"],
        "failure_type": "FEED_LOSS",
        "detected_at_utc": "2026-12-01T19:05:00Z",
        "outage_minutes": outage_minutes,
    }, OPS))
    event = get_success_data(api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    screenings = list_screenings(booking["id"])
    reported = [report_screening(s["id"], theater["id"], attendance,
                                 "SKIPPED_INCOMPLETE",
                                 at_instant=f"2026-12-0{i + 2}T00:00:00Z")
                for i, s in enumerate(sorted(screenings, key=lambda x: x["starts_at"]))]
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": get_booking(booking["id"]),
            "line": get_line(line["id"]), "feed_event": event,
            "screenings": reported}


def test_makegood_credit_selects_the_quarter_rate_tier_for_a_ten_minute_outage():
    """PRD §3.5: "an outage of at least 5 minutes but less than 30 earns one
    quarter" and "The lost fraction is the outage length in minutes divided by the
    screening's runtime — which is the title's `duration_minutes`, the same for
    every screening of the title."

    Design: Difficulty/combinatorial_formula/makegood_credit_tiered_min_formula
    """
    scene = _makegood_scene(outage_minutes=10)
    booking = scene["booking"]
    result = get_success_data(api_client.apply_makegood(
        booking["id"], scene["line"]["id"], scene["feed_event"]["id"],
        booking["version"], TEST_USERS["platform_ops_headers"]))
    assert result["makegood_credit_cents"] == 4167, (
        "0.25 x 1500 x 100 x (10/90) = 4166.67 rounds half up to 4167"
    )
    line = get_line(scene["line"]["id"])
    assert line["credit_issued_cents"] == 4167


def test_makegood_credit_seat_cap_does_not_bind_at_this_attendance():
    """PRD §3.5: "Against that stands a ceiling equal to the venue's `seats_total`
    multiplied by the ticket price and then by one half. Each ruined screening's
    credit is the smaller of the rate multiplied by the price multiplied by that
    screening's reported attendance multiplied by the lost fraction, and that
    ceiling, taken after the product has been rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/makegood_credit_tiered_min_formula
    """
    scene = _makegood_scene(outage_minutes=10)
    booking = scene["booking"]
    result = get_success_data(api_client.apply_makegood(
        booking["id"], scene["line"]["id"], scene["feed_event"]["id"],
        booking["version"], OPS))
    cap_cents = 60 * 1500 * 0.5
    assert cap_cents == 45000
    assert result["makegood_credit_cents"] == 4167, (
        "the nested minimum does not bind: 4167 is far below the 45000 seat cap"
    )


def test_makegood_credit_selects_the_six_tenths_tier_for_a_thirty_minute_outage():
    """PRD §3.5: "an outage of at least 30 minutes but less than 90 earns six
    tenths".

    Design: Difficulty/combinatorial_formula/makegood_credit_tiered_min_formula
    """
    scene = _makegood_scene(outage_minutes=30)
    booking = scene["booking"]
    result = get_success_data(api_client.apply_makegood(
        booking["id"], scene["line"]["id"], scene["feed_event"]["id"],
        booking["version"], OPS))
    assert result["makegood_credit_cents"] == 30000, (
        "0.60 x 1500 x 100 x (30/90) = 30000 cents exactly"
    )


def test_makegood_credit_rounds_each_screening_before_summing():
    """PRD §3.5: "Each screening's credit is rounded to whole cents individually,
    and only the rounded values are summed — summing the unrounded products and
    rounding the total yields a different cent count whenever two screenings each
    fall on a half cent, and the system must not do that."

    Design: Difficulty/combinatorial_formula/makegood_credit_tiered_min_formula
    """
    scene = _makegood_scene(outage_minutes=10, showtimes=2)
    booking = scene["booking"]
    assert len(scene["screenings"]) == 2
    result = get_success_data(api_client.apply_makegood(
        booking["id"], scene["line"]["id"], scene["feed_event"]["id"],
        booking["version"], OPS))
    per_screening = 4167
    assert result["makegood_credit_cents"] == per_screening * 2, (
        "two screenings each rounding to 4167 sum to 8334, not round(8333.33) = 8333"
    )
    line = get_line(scene["line"]["id"])
    assert line["credit_issued_cents"] == 8334


def test_makegood_credit_lands_on_both_the_booking_and_the_line():
    """PRD §3.5: "The resulting sum lands on the booking as its make-good credit
    total, on the affected line as that line's issued credit, and the portion of the
    total attributable to screenings whose failure was specifically a `FEED_LOSS` is
    tracked separately as the booking's feed failure credit".

    Design: Difficulty/combinatorial_formula/makegood_credit_tiered_min_formula
    """
    scene = _makegood_scene(outage_minutes=30)
    booking = scene["booking"]
    result = get_success_data(api_client.apply_makegood(
        booking["id"], scene["line"]["id"], scene["feed_event"]["id"],
        booking["version"], OPS))
    assert result["makegood_credit_cents"] == 30000
    assert get_line(scene["line"]["id"])["credit_issued_cents"] == 30000
    assert get_booking(booking["id"])["makegood_credit_cents"] == 30000