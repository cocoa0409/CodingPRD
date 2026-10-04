"""Calculation corners: allocation, encore pricing, delivery lead and key-window alignment."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, get_line, get_key,
    create_settlement_payload, make_exhibitor_headers,
    setup_circuit_venue_title, create_content_delivery_payload,
    create_encryption_key_payload, create_encore_window_payload, report_screening,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def test_guarantee_allocation_gives_the_remainder_to_the_earliest_created_line():
    """PRD §3.2: "Because truncation leaves a residual, the difference between the
    guarantee and the sum of the truncated shares is distributed one cent at a time,
    walking the committed lines in the same ordered sequence and giving each successive
    line one additional cent, wrapping back to the head of the sequence for as long as
    residual cents remain."

    Design: Corner/calculations/guarantee_allocation_splits_pro_rata_and_distributes_remainder
    """
    c = setup_circuit_venue_title(
        dist_overrides={"guarantee_floor_cents": 100})
    venues = [
        c["theater"],
        _new_venue(c, "Trellis Oakland", "Oakland"),
        _new_venue(c, "Trellis Stockton", "Stockton"),
    ]
    booking = create_booking(c["title"]["id"], c["circuit"]["id"], guarantee_cents=100)
    lines = []
    for venue in venues:
        line = add_line(booking["id"], c["circuit"]["id"], venue["id"],
                        booking["version"], committed_screens=40,
                        expected_attendance=1)
        booking = get_booking(booking["id"])
        lines.append(line)
    booking = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    for line in lines:
        get_success_data(api_client.approve_booking(
            booking["id"], booking["version"], _dist_headers(c), line["id"]))
        booking = get_booking(booking["id"])
    allocated = [get_line(line["id"])["guarantee_applied_cents"] for line in lines]
    assert booking["committed_screens_total"] == 120
    assert allocated == [34, 33, 33], (
        "equal forecasts give 33 each and the single leftover cent goes to the "
        "earliest-created_at line"
    )
    assert sum(allocated) == 100 == booking["guarantee_cents"]


def _new_venue(c, name, city):
    from test_helpers import create_theater
    return create_theater(c["circuit"]["id"], theater_name=name, city=city,
                          state_code="CA")


def _dist_headers(c):
    from test_helpers import make_distributor_headers
    return make_distributor_headers(c["distributor"]["id"])


def test_guarantee_allocation_pro_rata_never_drifts_from_the_whole():
    """PRD §3.2: "Otherwise each line receives the guarantee multiplied by that line's
    expected attendance and divided by the total expected attendance, truncated to
    whole cents."

    Design: Corner/calculations/guarantee_allocation_splits_pro_rata_and_distributes_remainder
    """
    c = setup_circuit_venue_title(
        dist_overrides={"guarantee_floor_cents": 100})
    second = _new_venue(c, "Trellis Oakland", "Oakland")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"], guarantee_cents=100)
    first = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                     booking["version"], committed_screens=40,
                     expected_attendance=70)
    booking = get_booking(booking["id"])
    second_line = add_line(booking["id"], c["circuit"]["id"], second["id"],
                           booking["version"], committed_screens=40,
                           expected_attendance=30)
    booking = get_booking(booking["id"])
    booking = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    for line in (first, second_line):
        get_success_data(api_client.approve_booking(
            booking["id"], booking["version"], _dist_headers(c), line["id"]))
        booking = get_booking(booking["id"])
    shares = [get_line(line["id"])["guarantee_applied_cents"]
              for line in (first, second_line)]
    assert shares == [70, 30], "a 70/30 forecast splits with no remainder"


def test_encore_price_derivation_takes_the_larger_of_the_two_discount_arms():
    """PRD §3.7: "Alongside the price the venue chooses, the system derives a reference
    encore price of its own: it takes the larger of the standard price less 500 cents
    and the standard price multiplied by 0.55 and rounded half up to a whole cent, with
    the comparison taken after the relative arm has been rounded."

    Design: Corner/calculations/encore_price_takes_the_max_of_two_discount_arms
    """
    c = _confirmed_reported_scene()
    window = get_success_data(api_client.create_encore_window(
        create_encore_window_payload(c["booking"]["id"], c["booking"]["version"],
                                     standard_ticket_price_cents=1500,
                                     encore_ticket_price_cents=1000), _dist_headers(c)))
    assert window["derived_encore_price_cents"] == 1000, (
        "the absolute arm 1500 - 500 = 1000 beats round_half_up(1500 x 0.55) = 825"
    )


def test_encore_window_opens_in_draft_with_no_screenings_attached():
    """PRD §3.7: "A window begins `DRAFT` with an encore screening count of zero, and
    creating it advances the parent booking's version."

    Design: Corner/calculations/encore_price_takes_the_max_of_two_discount_arms
    """
    c = _confirmed_reported_scene()
    before = c["booking"]["version"]
    window = get_success_data(api_client.create_encore_window(
        create_encore_window_payload(c["booking"]["id"], c["booking"]["version"]),
        _dist_headers(c)))
    assert window["status"] == "DRAFT"
    assert window["encore_screening_count"] == 0
    assert get_booking(c["booking"]["id"])["version"] == before + 1


def test_encore_window_rejects_an_encore_price_not_below_the_standard_price():
    """PRD §3.7: "A window whose encore price is not strictly below its standard
    price, or which closes after the title's rights end, or whose end is not after its
    start, is refused with `ERR_ENCORE_WINDOW_INVALID`".

    Design: Corner/calculations/encore_price_takes_the_max_of_two_discount_arms
    """
    c = _confirmed_reported_scene()
    resp = api_client.create_encore_window(
        create_encore_window_payload(c["booking"]["id"], c["booking"]["version"],
                                     standard_ticket_price_cents=1500,
                                     encore_ticket_price_cents=1500), _dist_headers(c))
    validate_error(resp, ApiErrorId.ERR_ENCORE_WINDOW_INVALID, 422)


def _confirmed_reported_scene(showtime_start_minute=1140):
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(booking["id"])
    booking = get_success_data(api_client.confirm_booking(
        booking["id"], booking["version"], OPS))
    screening = first_screening(booking["id"])
    report_screening(screening["id"], c["theater"]["id"], 175, "SCREENED",
                     at_instant="2026-12-01T21:30:00Z")
    c.update({"booking": get_booking(booking["id"]), "line": get_line(line["id"]),
              "screening": screening})
    return c


def _onsite_booking_with_delivery(method, scheduled_delivery_utc):
    """APPROVED booking whose single screening runs 19:00-21:00 on 2026-12-01."""
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    late = get_success_data(api_client.create_content_delivery(
        create_content_delivery_payload(booking["id"], booking["version"],
                                       delivery_method=method,
                                       content_checksum="sha256:11aa22bb",
                                       scheduled_delivery_utc=scheduled_delivery_utc),
        OPS))
    late = get_success_data(api_client.mark_delivery_delivered(
        late["id"], "sha256:11aa22bb", OPS))
    # §2.6: registering a package advances the booking's version, so the second
    # package must attest the freshly observed version rather than the pre-approval one.
    booking = get_booking(booking["id"])
    ok = get_success_data(api_client.create_content_delivery(
        create_content_delivery_payload(booking["id"], booking["version"],
                                       delivery_method=method,
                                       content_checksum="sha256:33cc44dd",
                                       scheduled_delivery_utc=scheduled_delivery_utc),
        OPS))
    c.update({"booking": booking, "line": line, "late_delivery": late,
              "ok_delivery": ok, "screening": first_screening(booking["id"])})
    return c


def test_delivery_lead_verification_rejects_a_package_inside_the_lead_window():
    """PRD §3.4: "That requirement is that the package's `scheduled_delivery_utc` plus
    the lead time for its delivery method must land at or before the earliest start
    among the booking's `SCHEDULED` screenings; exact equality passes, so a package
    scheduled precisely at that cutoff is accepted."

    Design: Corner/calculations/delivery_lead_verification_rejects_a_late_package
    """
    c = _onsite_booking_with_delivery("FILE", "2026-12-01T12:00:00Z")
    resp = api_client.verify_delivery(c["late_delivery"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_LEAD_VIOLATION, 422)


def test_delivery_lead_verification_accepts_a_package_outside_the_lead_window():
    """PRD §3.4: "When the venue takes delivery, an operator records the
    `delivered_checksum` actually received; the package moves to `DELIVERED`".

    Design: Corner/calculations/delivery_lead_verification_rejects_a_late_package
    """
    c = _onsite_booking_with_delivery("FILE", "2026-11-25T00:00:00Z")
    get_success_data(api_client.mark_delivery_delivered(
        c["ok_delivery"]["id"], "sha256:33cc44dd", OPS))
    verified = get_success_data(api_client.verify_delivery(c["ok_delivery"]["id"], OPS))
    assert verified["status"] == "VERIFIED"


def test_delivery_lead_is_method_specific_for_a_satellite_package():
    """PRD §3.4: "The lead time is 48 hours for `SATELLITE`, 24 hours for `FILE`, and
    48 hours for `BOTH`, and a live title adds 12 hours on top of whichever applies."

    Design: Corner/calculations/delivery_lead_verification_rejects_a_late_package
    """
    # 2026-11-30T12:00 + 48h (SATELLITE) lands at 2026-12-02T12:00, past the
    # 2026-12-01T19:00 screening start, while the same instant + 24h (FILE) lands
    # at 2026-12-01T12:00 and satisfies the rule — so this instant is what makes
    # the test discriminate between the two lead times.
    c = _onsite_booking_with_delivery("SATELLITE", "2026-11-30T12:00:00Z")
    resp = api_client.verify_delivery(c["late_delivery"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_LEAD_VIOLATION, 422)


def test_key_validity_state_is_computed_on_inclusive_bounds():
    """PRD §3.4: "The alignment test asks whether the key's interval covers its
    screening end to end: the key must open at or before the screening starts and close
    at or after the screening ends, with both boundaries inclusive, so a key opening
    exactly at the start and closing exactly at the end is aligned."

    Design: Corner/calculations/key_window_alignment_requires_both_inclusive_bounds
    """
    c = _key_alignment_scene()
    key_id = c["key"]["id"]
    set_clock("2026-12-01T18:59:59Z")
    assert get_key(key_id)["validity_state"] == "NOT_YET_VALID"
    set_clock("2026-12-01T19:00:00Z")
    assert get_key(key_id)["validity_state"] == "VALID"
    set_clock("2026-12-01T21:00:00Z")
    assert get_key(key_id)["validity_state"] == "VALID"
    set_clock("2026-12-01T21:00:01Z")
    assert get_key(key_id)["validity_state"] == "EXPIRED"


def test_key_aligned_exactly_to_the_screening_window_is_accepted():
    """PRD §3.4: "The instantaneous test asks, for whatever instant is currently being
    read, whether that instant falls before the key's opening boundary, inside the
    closed interval between the two boundaries, or after the closing boundary".

    Design: Corner/calculations/key_window_alignment_requires_both_inclusive_bounds
    """
    c = _key_alignment_scene()
    assert c["key"]["not_valid_before_utc"].startswith("2026-12-01T19:00:00")
    assert c["key"]["not_valid_after_utc"].startswith("2026-12-01T21:00:00")
    set_clock("2026-12-01T19:00:00Z")
    assert get_key(c["key"]["id"])["validity_state"] == "VALID"


def _key_alignment_scene():
    c = _onsite_booking_with_delivery("FILE", "2026-11-25T00:00:00Z")
    get_success_data(api_client.mark_delivery_delivered(
        c["ok_delivery"]["id"], "sha256:33cc44dd", OPS))
    get_success_data(api_client.verify_delivery(c["ok_delivery"]["id"], OPS))
    set_clock(c["booking"]["on_sale_at"])
    run_on_sale_sweep()
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(c["screening"]["id"],
                                      not_valid_before_utc="2026-12-01T19:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    c["key"] = key
    c["booking"] = get_booking(c["booking"]["id"])
    return c