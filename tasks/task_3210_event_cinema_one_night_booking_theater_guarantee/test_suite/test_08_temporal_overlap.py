"""Resource temporal overlap: two different interval semantics on two resources."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, first_screening, confirm_booking, make_distributor_headers,
    make_exhibitor_headers, setup_booking_approved, setup_verified_delivery,
    create_screening_payload, get_line,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
OFFICER = TEST_USERS["content_officer_headers"]


def _adjacent_auditorium_scene():
    """Booking A runs 19:00-21:00 in AUD-1; booking B is scheduled to start at 21:00."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="A", settlement_terms="NET_30",
                             screen_pool_total=400)
    theater = create_theater(circuit["id"], seats_total=200,
                             showtime_buffer_minutes=0)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")

    def drive(plan, screens, attendance, confirm_it):
        booking = create_booking(title["id"], circuit["id"],
                                 guarantee_cents=1000000, revenue_share_pct=0.40,
                                 showtime_plan=plan)
        line = add_line(booking["id"], circuit["id"], theater["id"],
                        booking["version"], committed_screens=screens,
                        expected_attendance=attendance)
        booking = submit_booking(booking["id"], circuit["id"], line["version"])
        booking = approve_booking(booking["id"], distributor["id"],
                                  booking["version"], line["id"])
        line = get_line(line["id"])
        booking = get_booking(booking["id"])
        if confirm_it:
            set_clock(booking["on_sale_at"])
            run_on_sale_sweep()
            booking = get_booking(booking["id"])
            booking = confirm_booking(booking["id"], booking["version"])
        return booking, line

    plan_a = [{"index": 1, "date_utc": "2026-12-01T00:00:00Z",
               "start_minute_utc": 1140, "auditorium": "AUD-1"}]
    booking_a, line_a = drive(plan_a, 60, 100, True)

    plan_b = [{"index": 1, "date_utc": "2026-12-01T00:00:00Z",
               "start_minute_utc": 1260, "auditorium": "AUD-1"}]
    booking_b, line_b = drive(plan_b, 40, 80, False)
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking_a": booking_a, "line_a": line_a,
            "booking_b": booking_b, "line_b": line_b}


def test_adjacent_auditorium_slots_are_allowed_so_the_second_booking_confirms():
    """PRD §3.3: "Adjacency is allowed: a candidate starting exactly at an existing
    screening's end instants no conflict, and neither does one ending exactly at an
    existing screening's start."

    Design: Difficulty/resource_temporal_overlap/cross_booking_auditorium_overlap_half_open
    """
    scene = _adjacent_auditorium_scene()
    booking_b = scene["booking_b"]
    # PRD §3.3: confirmation is an `ON_SALE` move, and the on-sale sweep only walks
    # bookings whose own `on_sale_at` has been reached. Booking B was opened after
    # booking A's checkpoint, so it still needs its own sweep before confirmation.
    set_clock(booking_b["on_sale_at"])
    run_on_sale_sweep()
    booking_b = get_booking(booking_b["id"])
    confirmed = confirm_booking(booking_b["id"], booking_b["version"])
    assert confirmed["status"] == "CONFIRMED"
    assert get_booking(scene["booking_a"]["id"])["status"] == "CONFIRMED"


def test_candidate_overlapping_by_one_minute_is_refused():
    """PRD §3.3: "The test is that the candidate's start is strictly before the
    existing screening's end and the candidate's end is strictly after the existing
    screening's start."

    Design: Difficulty/resource_temporal_overlap/cross_booking_auditorium_overlap_half_open
    """
    scene = _adjacent_auditorium_scene()
    resp = api_client.create_screening(
        create_screening_payload(scene["booking_b"]["id"], scene["theater"]["id"],
                                 auditorium="AUD-1",
                                 starts_at="2026-12-01T20:59:00Z",
                                 ends_at="2026-12-01T22:59:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_SCREEN_OVERLAP_CONFLICT, 409)


def test_overlap_rejection_is_raw_half_open_arithmetic_not_the_buffer():
    """PRD §3.3: "A conflict is reported as `ERR_SCREEN_OVERLAP_CONFLICT`. Note that a
    screening belonging to a booking in a non-live status is simply not considered by
    this rule at all."

    Design: Difficulty/resource_temporal_overlap/cross_booking_auditorium_overlap_half_open
    """
    scene = _adjacent_auditorium_scene()
    assert scene["theater"]["showtime_buffer_minutes"] == 0, (
        "the venue carries no buffer, so the rejection can only come from the raw "
        "half-open comparison against the live booking's screening"
    )
    resp = api_client.create_screening(
        create_screening_payload(scene["booking_b"]["id"], scene["theater"]["id"],
                                 auditorium="AUD-1",
                                 starts_at="2026-12-01T20:59:00Z",
                                 ends_at="2026-12-01T22:59:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_SCREEN_OVERLAP_CONFLICT, 409)


def _key_overlap_scene(screening_starts="2026-12-01T19:00:00Z",
                       screening_ends="2026-12-01T21:00:00Z"):
    """ON_SALE booking with one screening and a verified satellite package."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=2000)
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
    ctx = {"distributor": distributor, "circuit": circuit, "theater": theater,
           "title": title, "booking": get_booking(booking["id"]), "line": line,
           "screening": first_screening(booking["id"])}
    assert (ctx["screening"]["starts_at"].startswith(screening_starts[:16])
            and ctx["screening"]["ends_at"].startswith(screening_ends[:16])), (
        f"the synthesized screening must span {screening_starts} to {screening_ends}"
    )
    setup_verified_delivery(ctx, method="SATELLITE", checksum="sha256:99aabbcc")
    return ctx


def test_key_window_touching_a_live_key_is_refused_on_inclusive_bounds():
    """PRD §3.4: "A new key's interval may not intersect that of another key already
    bound to the same screening unless that other key has been revoked; a collision is
    refused with `ERR_KEY_WINDOW_OVERLAP`, which prevents two live keys from covering
    the same slot and thereby makes rotation well defined."

    Design: Difficulty/resource_temporal_overlap/same_booking_key_window_overlap_on_screening
    """
    ctx = _key_overlap_scene()
    screening_id = ctx["screening"]["id"]
    first = get_success_data(api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T18:00:00Z",
         "not_valid_after_utc": "2026-12-01T20:00:00Z"}, OPS))
    resp = api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T20:00:00Z",
         "not_valid_after_utc": "2026-12-01T22:00:00Z"}, OPS)
    validate_error(resp, ApiErrorId.ERR_KEY_WINDOW_OVERLAP, 409)
    assert first["issuance_status"] == "PENDING"


def test_key_window_moved_one_minute_clear_of_the_live_key_is_accepted():
    """PRD §3.4: "a collision is refused with `ERR_KEY_WINDOW_OVERLAP`, which prevents
    two live keys from covering the same slot".

    Design: Difficulty/resource_temporal_overlap/same_booking_key_window_overlap_on_screening
    """
    ctx = _key_overlap_scene()
    screening_id = ctx["screening"]["id"]
    get_success_data(api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T18:00:00Z",
         "not_valid_after_utc": "2026-12-01T20:00:00Z"}, OPS))
    clear = get_success_data(api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T20:01:00Z",
         "not_valid_after_utc": "2026-12-01T22:00:00Z"}, OPS))
    assert clear["issuance_status"] == "PENDING"


def test_revoked_key_no_longer_holds_its_instants_so_the_window_can_be_reissued():
    """PRD §3.4: "unless that other key has been revoked".

    Design: Difficulty/resource_temporal_overlap/same_booking_key_window_overlap_on_screening
    """
    ctx = _key_overlap_scene()
    screening_id = ctx["screening"]["id"]
    first = get_success_data(api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T18:00:00Z",
         "not_valid_after_utc": "2026-12-01T20:00:00Z"}, OPS))
    get_success_data(api_client.revoke_key(first["id"], "FEED_LOSS", OFFICER))
    reused = get_success_data(api_client.create_encryption_key(
        {"screening_id": screening_id,
         "not_valid_before_utc": "2026-12-01T18:00:00Z",
         "not_valid_after_utc": "2026-12-01T20:00:00Z"}, OPS))
    assert isinstance(reused["id"], str) and reused["id"] != first["id"], (
        "once the first key is revoked the same window can be reissued"
    )