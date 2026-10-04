"""Boundary precision: strict at-or-above gates on a ticket count and a failure duration."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, first_screening, get_line, make_theater_headers,
    make_distributor_headers, setup_presale_boundary_scene,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_presale_checkpoint_advances_both_bookings_to_on_sale():
    """PRD §3.3: "the on-sale sweep walks every `APPROVED` booking whose `on_sale_at`
    has been reached and whose committed screen total still meets its `min_screens`,
    moves each to `ON_SALE`, and recomputes each one's presale ticket count from the
    recorded presale ledger."

    Design: Difficulty/boundary_precision_check/presale_threshold_exact_equality_boundary
    """
    scene = setup_presale_boundary_scene(5000, 4999)
    assert scene["exact"]["booking"]["status"] == "ON_SALE"
    assert scene["short"]["booking"]["status"] == "ON_SALE"

    set_clock("2026-10-15T00:00:00Z")
    exact = get_success_data(api_client.run_presale_checkpoint(
        scene["exact"]["booking"]["id"], scene["exact"]["booking"]["version"], OPS))
    short = get_success_data(api_client.run_presale_checkpoint(
        scene["short"]["booking"]["id"], scene["short"]["booking"]["version"], OPS))
    assert exact["status"] == "ON_SALE"
    assert short["status"] == "CANCELLED"


def test_presale_checkpoint_exact_threshold_survives_and_one_short_cancels():
    """PRD §3.3: "it compares the presale ticket count against the booking's
    `pre_sale_threshold`. The comparison is at-or-above, not strictly-above: a booking
    whose threshold is zero passes having sold nothing, and a booking that sold exactly
    its threshold passes."

    Design: Difficulty/boundary_precision_check/presale_threshold_exact_equality_boundary
    """
    scene = setup_presale_boundary_scene(5000, 4999)
    set_clock("2026-10-15T00:00:00Z")
    exact = get_success_data(api_client.run_presale_checkpoint(
        scene["exact"]["booking"]["id"], scene["exact"]["booking"]["version"], OPS))
    short = get_success_data(api_client.run_presale_checkpoint(
        scene["short"]["booking"]["id"], scene["short"]["booking"]["version"], OPS))
    assert exact["pre_sale_tickets"] == 5000
    assert exact["status"] == "ON_SALE", "the exact-equality booking survives"
    assert short["pre_sale_tickets"] == 4999
    assert short["status"] == "CANCELLED", "one ticket short is not enough"


def test_presale_shortfall_cascade_releases_the_short_bookings_screens():
    """PRD §3.3: "A booking that falls short self-cancels: it moves to `CANCELLED`,
    every `COMMITTED` line is released, every `SCHEDULED` screening is marked
    `SKIPPED_CANCELLED`".

    Design: Difficulty/boundary_precision_check/presale_threshold_exact_equality_boundary
    """
    scene = setup_presale_boundary_scene(5000, 4999)
    set_clock("2026-10-15T00:00:00Z")
    api_client.run_presale_checkpoint(scene["short"]["booking"]["id"],
                                      scene["short"]["booking"]["version"], OPS)
    assert get_booking(scene["short"]["booking"]["id"])["committed_screens_total"] == 0
    assert get_line(scene["short"]["line"]["id"])["exhibit_state"] == "RELEASED"


def _feed_event_scene(with_screening=True):
    """ON_SALE booking with a 120-minute screening starting 19:00 UTC."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=400)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": get_booking(booking["id"]), "line": line,
            "screening": first_screening(booking["id"])}


def test_feed_event_confirm_accepts_an_outage_of_exactly_five_minutes():
    """PRD §3.5: "A `DETECTED` event may be confirmed only when its observed outage
    lasted at least 5 minutes and when at least one screening of the parent booking is
    in `SCHEDULED` or `SCREENED` and started at or before the detection instant."

    Design: Difficulty/boundary_precision_check/feed_outage_minimum_five_minutes_boundary
    """
    scene = _feed_event_scene()
    event = get_success_data(api_client.create_feed_event({
        "booking_id": scene["booking"]["id"], "failure_type": "FEED_LOSS",
        "detected_at_utc": "2026-12-01T19:05:00Z", "outage_minutes": 5}, OPS))
    confirmed = get_success_data(api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["affected_screening_count"] == 1, (
        "the one screening already running at detection is the affected one"
    )


def test_feed_event_confirm_rejects_an_outage_of_four_minutes():
    """PRD §3.5: "An outage shorter than 5 minutes is refused with
    `ERR_FEED_OUTAGE_TOO_SHORT`."

    Design: Difficulty/boundary_precision_check/feed_outage_minimum_five_minutes_boundary
    """
    scene = _feed_event_scene()
    event = get_success_data(api_client.create_feed_event({
        "booking_id": scene["booking"]["id"], "failure_type": "SATELLITE_OUTAGE",
        "detected_at_utc": "2026-12-01T19:05:00Z", "outage_minutes": 4}, OPS))
    resp = api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"])
    validate_error(resp, ApiErrorId.ERR_FEED_OUTAGE_TOO_SHORT, 422)
    assert get_success_data(
        api_client.get_feed_event(event["id"], OPS))["state"] == "DETECTED", (
        "the refused event never changes state"
    )


def test_feed_event_confirmation_records_the_affected_screening_count():
    """PRD §3.5: "Confirmation records the event's `affected_screening_count`, the
    count of the booking's screenings that had already started by the detection
    instant".

    Design: Difficulty/boundary_precision_check/feed_outage_minimum_five_minutes_boundary
    """
    scene = _feed_event_scene()
    event = get_success_data(api_client.create_feed_event({
        "booking_id": scene["booking"]["id"], "failure_type": "FEED_LOSS",
        "detected_at_utc": "2026-12-01T19:05:00Z", "outage_minutes": 5}, OPS))
    confirmed = get_success_data(api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    assert confirmed["affected_screening_count"] == 1
    assert get_booking(scene["booking"]["id"])["live_feed_event_count"] == 1, (
        "the booking's live feed event count is recomputed on confirmation"
    )